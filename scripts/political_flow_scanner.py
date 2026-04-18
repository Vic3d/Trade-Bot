#!/usr/bin/env python3
"""
Political Intelligence Flow Scanner (PIFS) — Albert / TradeMind
================================================================
Professioneller Multi-Asset Options Flow Scanner mit Scoring-System
à la Unusual Whales / FlowAlgo.

Sektoren: Energy, Defense, Bonds, Gold, Volatility, Tech
Scoring:  Vol/OI, Premium, Expiry, Moneyness, Sweep, Cluster, Congressional

Cron: alle 30 Min, 14:00-21:30 CET, Mo-Fr
"""

import json
import os
import sys
import urllib.request
import urllib.error
import sqlite3
import re
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')
from pathlib import Path

_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WORKSPACE = Path(os.getenv('TRADEMIND_HOME', _default_ws))
CONFIG_FILE  = WORKSPACE / 'trading_config.json'
OUTPUT_FILE  = WORKSPACE / 'memory/flow-scanner-data.json'
DB_FILE      = WORKSPACE / 'data/trading.db'

DISCORD_TARGET = "1475255728313864413"  # Victor DM

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Accept': 'application/json,text/html,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
}

# ── Config ────────────────────────────────────────────────────────────────────

def load_config():
    """Load config and return (flow_scanner_cfg, full_cfg)."""
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    default_flow = {
        "sectors": {
            "energy":     {"tickers": ["OXY","XOM","XLE","USO","CVX"], "weight": 1.5, "enabled": True},
            "defense":    {"tickers": ["LMT","RTX","NOC","GD","BA"],   "weight": 1.3, "enabled": True},
            "bonds":      {"tickers": ["TLT","TBT","IEF"],             "weight": 1.2, "enabled": True},
            "gold":       {"tickers": ["GLD","SLV","GDX"],             "weight": 1.1, "enabled": True},
            "volatility": {"tickers": ["UVXY","VXX"],                  "weight": 1.4, "enabled": True},
            "tech":       {"tickers": ["QQQ","NVDA","PLTR"],           "weight": 1.0, "enabled": True},
            "custom":     {"tickers": [],                              "weight": 1.0, "enabled": True},
            # Iran Peace Basket — Profiteure bei Hormuz-Öffnung / Iran-Deal
            # Wenn hier ungewöhnliches Kaufvolumen auftaucht VOR einem Trump-Deal → Frühwarnung
            "iran_peace_basket": {
                "tickers": ["DAL","UAL","AAL","LUV","BA","MAR","HLT","BKNG","EXPE","JETS"],
                "weight": 2.0,  # Doppelte Gewichtung — sehr hohes Signal
                "enabled": True,
                "description": "Airlines + Tourism + Boeing — profitieren von Iran-Deal (niedrigere Ölpreise)"
            },
            # Iran Peace Inverse — diese FALLEN bei Deal (Smart Money verkauft VOR Ankündigung)
            "iran_peace_inverse": {
                "tickers": ["FRO","DHT","STNG","INSW","TNK"],
                "weight": 1.8,
                "enabled": True,
                "description": "Tanker-Aktien — fallen wenn Hormuz öffnet (mehr Supply = niedrigere Raten)"
            },
        },
        "keywords": ["iran","trump","fed","tariffs","war","ukraine","ceasefire","sanctions","hormuz","peace","deal"],
        "min_score": 6,
        "auto_trade_threshold": 8,
        "congressional_check": True,
    }
    return cfg.get('flow_scanner', default_flow), cfg

# ── Yahoo Finance HTTP ────────────────────────────────────────────────────────

def fetch_json(url, timeout=12):
    """Fetch JSON from URL via urllib. Returns dict or None."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', errors='ignore'))
    except Exception:
        return None

def fetch_options_root(ticker):
    """Fetch options root (expiry dates + first chain) from Yahoo Finance v7."""
    url = f"https://query1.finance.yahoo.com/v7/finance/options/{ticker}"
    data = fetch_json(url)
    if not data:
        return None, []
    try:
        result = data['optionChain']['result'][0]
        quote  = result.get('quote', {})
        price  = quote.get('regularMarketPrice') or quote.get('ask') or 0
        expiry_dates = result.get('expirationDates', [])
        return float(price), expiry_dates
    except (KeyError, IndexError, TypeError):
        return None, []

def fetch_options_expiry(ticker, expiry_ts):
    """Fetch calls + puts for a specific expiry timestamp."""
    url = f"https://query1.finance.yahoo.com/v7/finance/options/{ticker}?date={expiry_ts}"
    data = fetch_json(url)
    if not data:
        return [], []
    try:
        opts = data['optionChain']['result'][0].get('options', [])
        if opts:
            return opts[0].get('calls', []), opts[0].get('puts', [])
    except (KeyError, IndexError, TypeError):
        pass
    return [], []

# ── Scoring ───────────────────────────────────────────────────────────────────

def score_option(contract, side, current_price, days_to_exp, sector_weight=1.0):
    """
    Score a single option contract using professional methodology.
    Returns (weighted_score, reasons_list, premium_usd).
    """
    score   = 0
    reasons = []

    vol  = int(contract.get('volume')       or 0)
    oi   = int(contract.get('openInterest') or 0)
    strike     = float(contract.get('strike',    0) or 0)
    last_price = float(contract.get('lastPrice', 0) or 0)
    ask_price  = float(contract.get('ask',       0) or 0)

    if vol < 50:
        return 0, [], 0

    # Premium estimate: option mid × 100 × volume
    mid  = last_price or ask_price or (strike * 0.01)
    premium = mid * 100 * vol

    # 1. Vol/OI Ratio ────────────────────────────────────────────────────────
    if oi > 0:
        ratio = vol / oi
        if ratio >= 10:
            score += 5
            reasons.append(f"Vol/OI={ratio:.1f}x EXTREME")
        elif ratio >= 3:
            score += 2
            reasons.append(f"Vol/OI={ratio:.1f}x unusual")
    elif vol >= 200:
        # OI≈0 and high vol = fresh sweep
        score += 2
        reasons.append(f"SWEEP Vol={vol:,} OI=0 (neue Position)")

    # 2. Premium Size ────────────────────────────────────────────────────────
    if premium >= 1_000_000:
        score += 3
        reasons.append(f"Premium ${premium/1e6:.2f}M institutional")
    elif premium >= 500_000:
        score += 2
        reasons.append(f"Premium ${premium/1e3:.0f}k institutional")

    # 3. Time to Expiry ──────────────────────────────────────────────────────
    if 1 <= days_to_exp <= 7:
        score += 2
        reasons.append(f"Aggressive {days_to_exp}d expiry")
    elif 8 <= days_to_exp <= 30:
        score += 1
        reasons.append(f"Tactical {days_to_exp}d expiry")

    # 4. Strike Moneyness OTM > 5% = aggressive ─────────────────────────────
    if current_price > 0 and strike > 0:
        if side == 'call':
            otm_pct = (strike - current_price) / current_price * 100
        else:
            otm_pct = (current_price - strike) / current_price * 100
        if otm_pct > 5:
            score += 2
            reasons.append(f"OTM {otm_pct:+.1f}% aggressive bet")

    if score == 0:
        return 0, [], 0

    weighted = round(score * sector_weight)
    return weighted, reasons, premium

# ── Congressional Trades ──────────────────────────────────────────────────────

def fetch_congressional_trades():
    """
    Fetch recent congressional trades from Capitol Trades.
    Returns list of ticker strings. Graceful on failure.
    """
    tickers = []
    urls = [
        "https://www.capitoltrades.com/trades?pageSize=10",
        "https://barchart.com/unusual-activity/stocks",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': HEADERS['User-Agent'],
                'Accept': 'text/html,application/xhtml+xml',
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode('utf-8', errors='ignore')

            # Extract ticker patterns - look for uppercase 2-5 char sequences
            # Capitol Trades: tickers appear in table cells
            found = re.findall(r'<(?:td|span)[^>]*>\s*([A-Z]{2,5})\s*</(?:td|span)>', html)
            # Filter out common HTML/text false positives
            stopwords = {'TD','TH','TR','AM','PM','US','EU','UK','NA','EM','PE','EV',
                         'CTA','CEO','CFO','COO','IPO','SEC','ETF','OTC','NYSE','NASDAQ'}
            found = [t for t in found if t not in stopwords and len(t) >= 2]
            tickers.extend(found[:15])
            if tickers:
                break
        except Exception:
            continue  # try next URL

    return list(dict.fromkeys(tickers))[:10]  # deduplicated, max 10

# ── Sector Active Check ───────────────────────────────────────────────────────

SECTOR_TICKER_MAP = {
    'energy':     ['OXY','XOM','CVX','XLE','USO','EQNR','TTE','FRO','DHT'],
    'defense':    ['LMT','RTX','NOC','GD','BA','RHM','HII','KTOS'],
    'bonds':      ['TLT','TBT','IEF','AGG'],
    'gold':       ['GLD','SLV','GDX','HL','PAAS','GOLD','NEM'],
    'volatility': ['UVXY','VXX','VIXY'],
    'tech':       ['QQQ','NVDA','PLTR','MSFT','ASML'],
}

def get_active_sectors(full_cfg):
    """Return set of sector names that have active strategies in trading_config.json."""
    active = set()
    for strat in full_cfg.get('strategies', []):
        status = str(strat.get('status', ''))
        is_active = ('🟢' in status or 'active' in status.lower() or
                     status.lower() == 'open' or 'OPEN' in status)
        if not is_active:
            continue
        for ticker in strat.get('tickers', []):
            t = ticker.upper().split('.')[0]  # strip exchange suffix
            for sector, mapped in SECTOR_TICKER_MAP.items():
                if t in mapped:
                    active.add(sector)
    return active

# ── Auto-Trade via SQLite ─────────────────────────────────────────────────────

def auto_trade(ticker, sector, score, side, entry_price):
    """Insert auto paper trade into SQLite. Returns True on success."""
    try:
        os.makedirs(DB_FILE.parent, exist_ok=True)
        conn = sqlite3.connect(str(DB_FILE))
        c    = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS paper_portfolio (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker          TEXT,
                strategy        TEXT,
                entry_price     REAL,
                entry_date      TEXT,
                shares          REAL,
                stop_price      REAL,
                target_price    REAL,
                status          TEXT    DEFAULT 'OPEN',
                fees            REAL    DEFAULT 0,
                notes           TEXT,
                style           TEXT    DEFAULT 'swing',
                conviction      INTEGER,
                regime_at_entry TEXT,
                sector          TEXT
            )
        """)
        stop   = round(entry_price * 0.95, 2)
        target = round(entry_price * 1.10, 2)
        conv   = min(95, score * 10)
        c.execute("""
            INSERT INTO paper_portfolio
            (ticker, strategy, entry_price, entry_date, shares, stop_price, target_price,
             status, fees, notes, style, conviction, regime_at_entry, sector)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ticker, 'PIFS', round(entry_price, 2),
            datetime.now(_BERLIN).strftime('%Y-%m-%d %H:%M:%S'),
            1.0, stop, target, 'OPEN', 0.0,
            f'PIFS Auto-Trade | Score={score} | Side={side} | Sektor={sector}',
            'swing', conv, 'UNKNOWN', sector,
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"  ⚠️ Auto-Trade Fehler: {e}", file=sys.stderr)
        return False

# ── Main Scanner ──────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    print(f"[PIFS] Political Intelligence Flow Scanner — {datetime.now(_BERLIN).strftime('%Y-%m-%d %H:%M')} CET")

    flow_cfg, full_cfg = load_config()
    sectors_cfg      = flow_cfg.get('sectors', {})
    min_score        = int(flow_cfg.get('min_score', 6))
    auto_threshold   = int(flow_cfg.get('auto_trade_threshold', 8))
    check_congress   = bool(flow_cfg.get('congressional_check', True))

    # ── Congressional Trades ──────────────────────────────────────────────
    congress_tickers = []
    if check_congress:
        print("  [Congressional] Fetching trades...")
        congress_tickers = fetch_congressional_trades()
        print(f"  → {len(congress_tickers)} tickers: {congress_tickers}")

    # ── Active strategies → sectors for auto-trade matching ──────────────
    active_sectors = get_active_sectors(full_cfg)
    print(f"  [Active sectors] {active_sectors}")

    # ── Per-Sector Scan ───────────────────────────────────────────────────
    all_signals    = []
    sector_results = {}

    for sector_name, sector_cfg in sectors_cfg.items():
        if not sector_cfg.get('enabled', True):
            continue
        tickers = [t for t in sector_cfg.get('tickers', []) if t]
        if not tickers:
            sector_results[sector_name] = _empty_sector()
            continue

        weight = float(sector_cfg.get('weight', 1.0))
        print(f"\n  [{sector_name.upper()}] Scanne {tickers}...")

        sector_signals       = []
        call_premium_total   = 0.0
        put_premium_total    = 0.0
        bullish_tickers_set  = set()

        for ticker in tickers:
            print(f"    {ticker}...", end=' ', flush=True)
            current_price, expiry_dates = fetch_options_root(ticker)
            if not current_price or not expiry_dates:
                print("n/v")
                continue

            # Filter: only expiries within 0-30 days
            near_expiries = [
                ts for ts in expiry_dates
                if 0 <= (datetime.fromtimestamp(ts, tz=timezone.utc) - now).days <= 30
            ][:4]   # max 4 expiries per ticker to stay fast

            ticker_signals = 0
            for exp_ts in near_expiries:
                exp_dt      = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
                days_to_exp = max(0, (exp_dt - now).days)
                exp_str     = exp_dt.strftime('%Y-%m-%d')

                calls, puts = fetch_options_expiry(ticker, exp_ts)
                time.sleep(0.1)  # gentle rate limit

                for side_str, contracts in [('call', calls), ('put', puts)]:
                    for contract in contracts:
                        raw_score, reasons, premium = score_option(
                            contract, side_str, current_price, days_to_exp, weight
                        )
                        if raw_score < 3:
                            continue

                        # Congressional bonus
                        c_bonus = 2 if ticker in congress_tickers else 0
                        total   = raw_score + c_bonus

                        if side_str == 'call':
                            call_premium_total += premium
                            bullish_tickers_set.add(ticker)
                        else:
                            put_premium_total += premium

                        sig = {
                            'ticker':          ticker,
                            'sector':          sector_name,
                            'side':            side_str.upper(),
                            'strike':          contract.get('strike'),
                            'expiry':          exp_str,
                            'days_to_exp':     days_to_exp,
                            'volume':          int(contract.get('volume')       or 0),
                            'oi':              int(contract.get('openInterest') or 0),
                            'last_price':      float(contract.get('lastPrice',  0) or 0),
                            'current_price':   current_price,
                            'premium':         round(premium),
                            'score':           total,
                            'score_raw':       raw_score,
                            'congress_bonus':  c_bonus,
                            'reasons':         reasons,
                            'timestamp':       now.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        }
                        sector_signals.append(sig)
                        ticker_signals += 1

            print(f"{ticker_signals} signals")

        # ── Cluster bonus: ≥3 bullish tickers in same sector ─────────────
        cluster_bonus = 3 if len(bullish_tickers_set) >= 3 else 0
        if cluster_bonus:
            for sig in sector_signals:
                sig['cluster_bonus'] = cluster_bonus
                sig['score'] += cluster_bonus
            print(f"  ⚡ Cluster {sector_name}: {len(bullish_tickers_set)} bullish tickers → +{cluster_bonus}")

        # ── Net Premium Flow → Direction ──────────────────────────────────
        net = call_premium_total - put_premium_total
        if net > 500_000:
            direction, emoji = 'BULLISH_STRONG', '🟢🟢'
        elif net > 100_000:
            direction, emoji = 'BULLISH', '🟢'
        elif net < -500_000:
            direction, emoji = 'BEARISH_STRONG', '🔴🔴'
        elif net < -100_000:
            direction, emoji = 'BEARISH', '🔴'
        else:
            direction, emoji = 'NEUTRAL', '⚪'

        top5 = sorted(sector_signals, key=lambda x: x['score'], reverse=True)[:5]

        sector_results[sector_name] = {
            'direction':            direction,
            'dir_emoji':            emoji,
            'net_flow':             round(net),
            'call_premium':         round(call_premium_total),
            'put_premium':          round(put_premium_total),
            'signal_count':         len(sector_signals),
            'bullish_ticker_count': len(bullish_tickers_set),
            'cluster':              cluster_bonus > 0,
            'top_signals':          top5,
        }
        all_signals.extend(sector_signals)
        print(f"  → {sector_name}: {emoji} {direction} | NetFlow ${net:+,.0f} | {len(sector_signals)} sigs")

    # ── Overall Direction ─────────────────────────────────────────────────
    total_net = sum(r['net_flow'] for r in sector_results.values())
    if total_net > 1_000_000:
        ov_dir, ov_emoji = 'BULLISH_STRONG', '🟢🟢'
    elif total_net > 200_000:
        ov_dir, ov_emoji = 'BULLISH', '🟢'
    elif total_net < -1_000_000:
        ov_dir, ov_emoji = 'BEARISH_STRONG', '🔴🔴'
    elif total_net < -200_000:
        ov_dir, ov_emoji = 'BEARISH', '🔴'
    else:
        ov_dir, ov_emoji = 'NEUTRAL', '⚪'

    top_all = sorted(all_signals, key=lambda x: x['score'], reverse=True)[:10]
    ov_score = max((s['score'] for s in all_signals), default=0)

    # ── Auto-Trade ────────────────────────────────────────────────────────
    auto_created = []
    for sig in top_all:
        if sig['score'] >= auto_threshold and sig['sector'] in active_sectors:
            ok = auto_trade(
                ticker=sig['ticker'],
                sector=sig['sector'],
                score=sig['score'],
                side=sig['side'],
                entry_price=sig.get('current_price', 0),
            )
            if ok:
                auto_created.append(sig['ticker'])
                print(f"  🤖 Auto-Trade: {sig['ticker']} ({sig['sector']}) score={sig['score']}")

    # ── Iran Peace Basket Cross-Signal Detection ─────────────────────────
    # Wenn Peace Basket BULLISH + Peace Inverse BEARISH → Super-Signal
    peace_basket = sector_results.get('iran_peace_basket', _empty_sector())
    peace_inverse = sector_results.get('iran_peace_inverse', _empty_sector())
    
    output_extra = {}
    iran_peace_cross_signal = False
    if (peace_basket.get('direction', 'NEUTRAL') in ('BULLISH', 'BULLISH_STRONG') and
        peace_inverse.get('direction', 'NEUTRAL') in ('BEARISH', 'BEARISH_STRONG')):
        iran_peace_cross_signal = True
        output_extra['iran_peace_cross_signal'] = True
        output_extra['iran_peace_cross_detail'] = {
            'basket_direction': peace_basket.get('direction'),
            'basket_net_flow': peace_basket.get('net_flow', 0),
            'inverse_direction': peace_inverse.get('direction'),
            'inverse_net_flow': peace_inverse.get('net_flow', 0),
            'interpretation': 'Smart Money kauft Airlines/Tourism UND verkauft Tanker — Iran-Deal wahrscheinlich imminent',
        }
        print("  🕊️ ⚡ IRAN PEACE CROSS-SIGNAL: Airlines BULLISH + Tanker BEARISH → Smart Money positioniert sich für Deal!")
    elif peace_basket.get('direction', 'NEUTRAL') in ('BULLISH', 'BULLISH_STRONG'):
        print("  🕊️ Iran Peace Basket: Airlines/Tourism BULLISH — mögliches Frühsignal")
    elif peace_inverse.get('direction', 'NEUTRAL') in ('BEARISH', 'BEARISH_STRONG'):
        print("  🕊️ Iran Peace Inverse: Tanker BEARISH — mögliches Frühsignal")

    # ── Write Output JSON ─────────────────────────────────────────────────
    output = {
        'timestamp':              now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'overall_direction':      ov_dir,
        'overall_emoji':          ov_emoji,
        'overall_score':          ov_score,
        'total_net_flow':         round(total_net),
        'sectors':                sector_results,
        'top_signals':            top_all,
        'congressional_tickers':  congress_tickers,
        'auto_trades_created':    auto_created,
        'scan_config':            {'min_score': min_score, 'auto_trade_threshold': auto_threshold},
    }
    output.update(output_extra)
    os.makedirs(OUTPUT_FILE.parent, exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Ergebnis → {OUTPUT_FILE}")

    # ── Discord Alert ─────────────────────────────────────────────────────
    qualifying = [s for s in top_all if s['score'] >= min_score]
    if qualifying or any(r['direction'] != 'NEUTRAL' for r in sector_results.values()):
        alert = _build_alert(qualifying, sector_results, ov_dir, ov_emoji,
                             ov_score, congress_tickers, auto_created)
        print("\n" + "="*62)
        print(alert)
        print("="*62)
        payload = json.dumps({
            "action": "send", "channel": "discord",
            "target": DISCORD_TARGET, "message": alert,
        })
        print(f"\nDISCORD_ALERT:{payload}")
    else:
        print(f"\nKeine qualifizierenden Signale (min_score={min_score}). Overall: {ov_dir}")

    return output

# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_sector():
    return {
        'direction': 'NEUTRAL', 'dir_emoji': '⚪',
        'net_flow': 0, 'call_premium': 0, 'put_premium': 0,
        'signal_count': 0, 'bullish_ticker_count': 0,
        'cluster': False, 'top_signals': [],
    }

def _build_alert(signals, sector_results, ov_dir, ov_emoji, ov_score,
                 congress_tickers, auto_created):
    lines = ["🔍 **PIFS — Political Intelligence Flow Scanner**\n"]
    lines.append(f"**Overall: {ov_emoji} {ov_dir}** | Max-Score: **{ov_score}**\n")

    # Sector summary (non-neutral)
    active = {k: v for k, v in sector_results.items() if v['direction'] != 'NEUTRAL'}
    if active:
        lines.append("**Sektor Flow:**")
        for sname, sd in active.items():
            nf = sd['net_flow']
            flow_str = f"${abs(nf)/1e6:.2f}M" if abs(nf) >= 1e6 else f"${abs(nf)/1e3:.0f}k"
            cluster_tag = " ⚡Cluster" if sd.get('cluster') else ""
            lines.append(f"  {sd['dir_emoji']} **{sname.upper()}** | Net: {flow_str} | {sd['signal_count']} signals{cluster_tag}")

    # Top 5 signals
    if signals:
        lines.append("\n**Top Signale:**")
        for s in signals[:5]:
            side_emoji = '📈' if s['side'] == 'CALL' else '📉'
            vol, oi = s.get('volume', 0), s.get('oi', 0)
            vol_oi_str = f"{vol/oi:.1f}x" if oi > 0 else f"SWEEP({vol:,})"
            prem = s.get('premium', 0)
            prem_str = f"${prem/1e6:.2f}M" if prem >= 1e6 else f"${prem/1e3:.0f}k" if prem >= 1e3 else f"${prem}"
            c_tag = " 🏛️" if s.get('congress_bonus', 0) > 0 else ""
            lines.append(f"  {side_emoji} **{s['ticker']}** {s['side']} ${s.get('strike',0)} exp {s.get('expiry','?')}{c_tag}")
            lines.append(f"    Score: **{s['score']}** | Vol/OI: {vol_oi_str} | Premia: {prem_str}")

    # Congressional
    if congress_tickers:
        lines.append(f"\n🏛️ **Congressional Trades:** {', '.join(congress_tickers[:6])}")

    # Iran Peace Basket Special Alert
    peace_basket_active = any(
        s['sector'] == 'iran_peace_basket' and s['side'] == 'CALL'
        for s in signals
    )
    peace_inverse_active = any(
        s['sector'] == 'iran_peace_inverse' and s['side'] == 'PUT'
        for s in signals
    )
    if peace_basket_active and peace_inverse_active:
        lines.append("\n🕊️⚡ **IRAN PEACE CROSS-SIGNAL!**")
        lines.append("Airlines/Tourism CALLS + Tanker PUTS gleichzeitig!")
        lines.append("→ Smart Money positioniert sich für Iran-Deal")
        lines.append("→ EQNR Stop prüfen, LHA Entry vorbereiten!")
    elif peace_basket_active:
        lines.append("\n🕊️ **Iran Peace Basket aktiv** — Airlines/Tourism CALLS detektiert")
    elif peace_inverse_active:
        lines.append("\n🕊️ **Iran Peace Inverse** — Tanker PUTS detektiert")

    # Auto-trades
    if auto_created:
        lines.append(f"\n🤖 **Auto-Trade ausgeführt:** {', '.join(auto_created)}")

    lines.append(f"\n_PIFS v1.0 — Scan: {datetime.now(_BERLIN).strftime('%H:%M')} CET_")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
