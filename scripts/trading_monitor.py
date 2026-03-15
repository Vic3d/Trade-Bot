#!/usr/bin/env python3
"""
Trading Monitor v2 — Pure Python, Zero AI Tokens
=================================================
Konsolidierter Price-/Alert-Monitor für alle Positionen + Watchlist.
Ersetzt 11 separate AI-Cron-Jobs (~500 Runs/Tag → 1 Script).

Läuft alle 15 Min via OpenClaw Cron (minimaler Haiku-Prompt, ~500 Tokens/Run).
Alerts werden direkt via `openclaw message send` an Discord geschickt.

Autor: Albert 🎩 | v2.0 | 15.03.2026
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── Pfade ───────────────────────────────────────────────────────────
WORKSPACE = Path('/data/.openclaw/workspace')
CONFIG_PATH = WORKSPACE / 'trading_config.json'
STATE_PATH = WORKSPACE / 'memory' / 'trading-monitor-state.json'
LOG_PATH = WORKSPACE / 'memory' / 'trading-monitor.log'
PRICES_PATH = WORKSPACE / 'memory' / 'latest-prices.json'  # Für AI-Jobs
SNAPSHOT_PATH = WORKSPACE / 'memory' / 'state-snapshot.md'
OVERNIGHT_PATH = WORKSPACE / 'memory' / 'overnight-context.md'
EMA_CACHE_PATH = WORKSPACE / 'memory' / 'ema-cache.json'
STRATEGIEN_PATH = WORKSPACE / 'memory' / 'strategien.md'

# trade_journal Modul einbinden
sys.path.insert(0, str(WORKSPACE / 'scripts'))
try:
    from trade_journal import log_alert as _journal_log_alert
    JOURNAL_AVAILABLE = True
except ImportError:
    JOURNAL_AVAILABLE = False
    def _journal_log_alert(data): pass

# ─── Helpers ─────────────────────────────────────────────────────────

def log(msg: str):
    """Append to log + print."""
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, 'a') as f:
            f.write(line + '\n')
        # Log rotieren: max 500 Zeilen
        lines = LOG_PATH.read_text().splitlines()
        if len(lines) > 500:
            LOG_PATH.write_text('\n'.join(lines[-300:]) + '\n')
    except Exception:
        pass


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default if default is not None else {}


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def send_alert(msg: str, target: str = None):
    """Schreibt Alert in Queue-Datei. Der Cron-Agent liest + sendet via message-Tool."""
    queue_path = WORKSPACE / 'memory' / 'alert-queue.json'
    queue = load_json(queue_path, [])
    queue.append({
        'message': msg,
        'target': target or '452053147620343808',
        'ts': datetime.now(timezone.utc).isoformat(),
    })
    save_json(queue_path, queue)
    log(f"ALERT QUEUED: {msg[:80]}...")


# ─── Yahoo Finance ───────────────────────────────────────────────────

def yahoo_price(ticker: str, timeout: int = 8) -> dict | None:
    """Holt Preis + Meta von Yahoo Finance. Returns dict oder None."""
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        result = data['chart']['result'][0]
        meta = result['meta']
        quote = result['indicators']['quote'][0]

        # Aktueller Preis
        price = meta.get('regularMarketPrice', 0)
        prev_close = meta.get('chartPreviousClose', meta.get('previousClose', price))

        # 5-Min-Kerzen für Candlestick-Analyse
        closes = [v for v in (quote.get('close') or []) if v is not None]
        opens = [v for v in (quote.get('open') or []) if v is not None]
        highs = [v for v in (quote.get('high') or []) if v is not None]
        lows = [v for v in (quote.get('low') or []) if v is not None]

        return {
            'price': price,
            'prev_close': prev_close,
            'change_pct': (price - prev_close) / prev_close * 100 if prev_close else 0,
            'closes': closes,
            'opens': opens,
            'highs': highs,
            'lows': lows,
        }
    except Exception as e:
        log(f"Yahoo FEHLER {ticker}: {e}")
        return None


def yahoo_batch(tickers: list[str]) -> dict:
    """Holt Preise für mehrere Ticker. Returns {ticker: data}."""
    results = {}
    for t in tickers:
        data = yahoo_price(t)
        if data:
            results[t] = data
        time.sleep(0.3)  # Rate limiting
    return results


# ─── Onvista ─────────────────────────────────────────────────────────

def onvista_price(url: str) -> float | None:
    """Holt Kurs von Onvista via HTML-Scraping."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode('utf-8', errors='ignore')
        matches = re.findall(r'"last":([0-9.]+)', html)
        return float(matches[0]) if matches else None
    except Exception as e:
        log(f"Onvista FEHLER: {e}")
        return None


# ─── Candlestick Pattern Detection ──────────────────────────────────

def detect_candlestick(data: dict) -> str | None:
    """Erkennt Umkehrkerzen in 5-Min-Daten. Returns Pattern-Name oder None."""
    closes = data.get('closes', [])
    opens = data.get('opens', [])
    highs = data.get('highs', [])
    lows = data.get('lows', [])

    if len(closes) < 2 or len(opens) < 2 or len(highs) < 2 or len(lows) < 2:
        return None

    # Letzte 2 Kerzen
    k1 = {'o': opens[-2], 'c': closes[-2], 'h': highs[-2], 'l': lows[-2]}
    k2 = {'o': opens[-1], 'c': closes[-1], 'h': highs[-1], 'l': lows[-1]}

    range_k2 = k2['h'] - k2['l']
    if range_k2 < 0.01:
        return None

    body_k2 = abs(k2['c'] - k2['o'])
    lower_wick = min(k2['o'], k2['c']) - k2['l']

    # Hammer: langer unterer Docht, kleiner Body oben
    if lower_wick > body_k2 * 2 and k2['c'] > k2['o']:
        return 'HAMMER'

    # Bullish Engulfing: aktuelle Kerze umschließt vorherige
    if (k2['c'] > k1['o'] and k2['o'] < k1['c'] and k2['c'] > k2['o']):
        return 'BULLISH_ENGULFING'

    # Close Near High: starker Schluss
    if k2['c'] > k2['o'] and (k2['c'] - k2['l']) / range_k2 > 0.75:
        return 'CLOSE_NEAR_HIGH'

    return None


# ─── Preis-Konvertierung ────────────────────────────────────────────

def to_eur(price: float, currency: str, fx: dict) -> float | None:
    """Konvertiert Preis in EUR."""
    if currency == 'EUR':
        return price
    if currency == 'USD' and fx.get('EURUSD'):
        return price / fx['EURUSD']
    if currency == 'NOK' and fx.get('EURNOK'):
        return price / fx['EURNOK']
    if currency == 'GBP' and fx.get('GBPEUR'):
        return (price / 100) * fx['GBPEUR']  # GBp → GBP → EUR
    return None


# ─── Check-Funktionen ───────────────────────────────────────────────

def check_positions(config: dict, prices: dict, fx: dict, state: dict,
                    strategy_statuses: dict = None,
                    conviction_cache: dict = None) -> list[str]:
    """Prüft alle Positionen auf Stop-Nähe, Ziel-Erreichung, Trailing Stops."""
    alerts = []
    settings = config.get('settings', {})
    stop_warn = settings.get('stop_warn_pct', 3.0)
    stop_crit = settings.get('stop_critical_pct', 1.5)
    trail_start = settings.get('trailing_start_pct', 5.0)
    trail_secure = settings.get('trailing_secure_pct', 10.0)
    sent_today = state.get('alerts_sent_today', [])
    if strategy_statuses is None:
        strategy_statuses = {}
    if conviction_cache is None:
        conviction_cache = {}

    # Macro-Daten für Journal/Conviction
    macro_wti = prices.get('CL=F', {}).get('price')
    macro_vix = prices.get('^VIX', {}).get('price')

    for key, pos in config.get('positions', {}).items():
        name = pos['name']
        ticker = f"{name} ({key})"
        stop = pos.get('stop_eur')
        entry = pos.get('entry_eur', 0)

        # Aktuellen EUR-Preis bestimmen
        yahoo_ticker = pos.get('yahoo')
        onvista_url = pos.get('onvista')
        price_eur = None

        if onvista_url:
            raw = onvista_price(onvista_url)
            if raw:
                price_eur = raw
        elif yahoo_ticker and yahoo_ticker in prices:
            raw = prices[yahoo_ticker]['price']
            price_eur = to_eur(raw, pos.get('currency', 'USD'), fx)

        if price_eur is None:
            continue

        # P&L
        pnl_pct = (price_eur - entry) / entry * 100 if entry else 0

        # --- Stop-Checks ---
        # Conviction für diese Position berechnen
        conv = conviction_score(
            key, 'check', price_eur, stop, entry,
            macro_vix, strategy_statuses
        )
        conviction_cache[key] = conv
        conv_str = f" [Conviction: {conv['score']}/100]"

        if stop:
            margin_pct = (price_eur - stop) / stop * 100
            alert_key = f"{key}_STOP_HIT"
            warn_key = f"{key}_STOP_WARN"
            crit_key = f"{key}_STOP_CRIT"

            if price_eur <= stop and alert_key not in sent_today:
                msg = f"🔴 STOP GETROFFEN: {ticker} @ {price_eur:.2f}€ | Stop: {stop}€ | SOFORT PRÜFEN!{conv_str}"
                alerts.append(msg)
                sent_today.append(alert_key)
                _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Stop-Breach',
                    'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                    'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})
            elif margin_pct < stop_crit and crit_key not in sent_today:
                msg = f"⚠️ STOP KRITISCH: {ticker} @ {price_eur:.2f}€ | Stop: {stop}€ | Nur noch {margin_pct:.1f}% Abstand!{conv_str}"
                alerts.append(msg)
                sent_today.append(crit_key)
                _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Stop-Warnung',
                    'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                    'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})
            elif margin_pct < stop_warn and warn_key not in sent_today:
                msg = f"⚡ Stop-Nähe: {ticker} @ {price_eur:.2f}€ | Stop: {stop}€ | {margin_pct:.1f}% Abstand{conv_str}"
                alerts.append(msg)
                sent_today.append(warn_key)
                _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Stop-Warnung',
                    'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                    'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})
            # Reset wenn Kurs sich erholt
            elif margin_pct > stop_warn + 2:
                for k in [warn_key, crit_key]:
                    if k in sent_today:
                        sent_today.remove(k)

        # --- Ziel-Checks ---
        for i, target in enumerate(pos.get('targets_eur', [])):
            tgt_key = f"{key}_ZIEL{i+1}"
            if price_eur >= target and tgt_key not in sent_today:
                msg = f"🎯 ZIEL {i+1} ERREICHT: {ticker} @ {price_eur:.2f}€ | Ziel: {target}€ | P&L: {pnl_pct:+.1f}% | Stop nachziehen?{conv_str}"
                alerts.append(msg)
                sent_today.append(tgt_key)
                _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Target-Reached',
                    'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                    'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})

        # --- Trailing Stop Trigger ---
        trail_key = f"{key}_TRAIL_{int(trail_start)}"
        if entry and pnl_pct >= trail_start and trail_key not in sent_today:
            msg = f"📈 Trailing Stop fällig: {ticker} @ {price_eur:.2f}€ | P&L: {pnl_pct:+.1f}% (>{trail_start}%) | Stop auf Breakeven ({entry:.2f}€) nachziehen!{conv_str}"
            alerts.append(msg)
            sent_today.append(trail_key)
            _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Trailing-Signal',
                'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})

        trail_key2 = f"{key}_TRAIL_{int(trail_secure)}"
        if entry and pnl_pct >= trail_secure and trail_key2 not in sent_today:
            secure_price = entry + (price_eur - entry) * 0.5
            msg = f"🔒 Gewinn sichern: {ticker} @ {price_eur:.2f}€ | P&L: {pnl_pct:+.1f}% (>{trail_secure}%) | 50% Gewinn sichern → Stop auf {secure_price:.2f}€{conv_str}"
            alerts.append(msg)
            sent_today.append(trail_key2)
            _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Trailing-Signal',
                'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})

        # --- Spezial-Alerts (NVDA Stufen) ---
        custom = pos.get('alerts', {})
        for alert_name, threshold in custom.items():
            ckey = f"{key}_{alert_name}"
            if ckey in sent_today:
                continue
            yahoo_t = pos.get('yahoo')
            if not yahoo_t or yahoo_t not in prices:
                continue
            raw_price = prices[yahoo_t]['price']

            if 'below' in alert_name and raw_price <= threshold:
                alerts.append(f"🔔 {ticker}: ${raw_price:.2f} — {alert_name.replace('_', ' ').title()} Zone ({threshold})! Setup beobachten.")
                sent_today.append(ckey)
            elif 'above' in alert_name and raw_price >= threshold:
                alerts.append(f"🔔 {ticker}: ${raw_price:.2f} — {alert_name.replace('_', ' ').title()} ({threshold})! Signal prüfen.")
                sent_today.append(ckey)

    state['alerts_sent_today'] = sent_today
    return alerts


def check_watchlist(config: dict, prices: dict, fx: dict, state: dict) -> list[str]:
    """Prüft Watchlist-Aktien auf Entry-Signale + Candlestick-Patterns."""
    alerts = []
    sent_today = state.get('alerts_sent_today', [])

    for key, watch in config.get('watchlist', {}).items():
        name = watch['name']
        ticker = f"{name} ({key})"

        yahoo_t = watch.get('yahoo')
        onvista_url = watch.get('onvista')
        price_raw = None
        price_eur = None

        if onvista_url:
            price_raw = onvista_price(onvista_url)
            price_eur = price_raw
        elif yahoo_t and yahoo_t in prices:
            price_raw = prices[yahoo_t]['price']
            price_eur = to_eur(price_raw, watch.get('currency', 'USD'), fx)

        if price_raw is None:
            continue

        # --- EUR-basierte Signale ---
        sig_a = watch.get('signal_a_above_eur')
        if sig_a and price_eur and price_eur >= sig_a:
            akey = f"WL_{key}_SIG_A"
            if akey not in sent_today:
                alerts.append(f"🔔 SIGNAL A: {ticker} @ {price_eur:.0f}€ — über {sig_a}€! Entry-Setup aktiv.")
                sent_today.append(akey)

        sig_b = watch.get('signal_b_below_eur')
        if sig_b and price_eur and price_eur <= sig_b:
            bkey = f"WL_{key}_SIG_B"
            if bkey not in sent_today:
                alerts.append(f"🔔 SIGNAL B: {ticker} @ {price_eur:.0f}€ — unter {sig_b}€! Rücklauf-Entry-Zone.")
                sent_today.append(bkey)

        entry_below = watch.get('entry_below_eur')
        if entry_below and price_eur and price_eur <= entry_below:
            ekey = f"WL_{key}_ENTRY"
            if ekey not in sent_today:
                alerts.append(f"🔔 ENTRY-ZONE: {ticker} @ {price_eur:.0f}€ — unter {entry_below}€! Setup prüfen.")
                sent_today.append(ekey)

        entry_b_below = watch.get('entry_b_below_eur')
        if entry_b_below and price_eur and price_eur <= entry_b_below:
            ekey = f"WL_{key}_ENTRY_B"
            if ekey not in sent_today:
                alerts.append(f"🔔 ENTRY B: {ticker} @ {price_eur:.2f}€ — unter {entry_b_below}€!")
                sent_today.append(ekey)

        # --- USD-basierte Signale ---
        ea_usd = watch.get('entry_a_above_usd')
        if ea_usd and price_raw >= ea_usd:
            akey = f"WL_{key}_ENTRY_A_USD"
            if akey not in sent_today:
                alerts.append(f"🔔 ENTRY A: {ticker} @ ${price_raw:.2f} (>{ea_usd}) — Breakout!")
                sent_today.append(akey)

        eb_usd = watch.get('entry_b_below_usd')
        if eb_usd and price_raw <= eb_usd:
            bkey = f"WL_{key}_ENTRY_B_USD"
            if bkey not in sent_today:
                alerts.append(f"🔔 ENTRY B: {ticker} @ ${price_raw:.2f} (<{eb_usd}) — Rücklauf-Zone!")
                sent_today.append(bkey)

        # --- Candlestick Detection ---
        if watch.get('candlestick_detect') and yahoo_t and yahoo_t in prices:
            pattern = detect_candlestick(prices[yahoo_t])
            if pattern:
                ckey = f"WL_{key}_CANDLE_{pattern}"
                if ckey not in sent_today:
                    alerts.append(f"🕯️ UMKEHRKERZE: {ticker} — {pattern} @ ${price_raw:.2f}! Entry-Bestätigung?")
                    sent_today.append(ckey)

    state['alerts_sent_today'] = sent_today
    return alerts


def check_macro(config: dict, prices: dict, state: dict) -> list[str]:
    """Prüft WTI-Öl und VIX auf Spikes."""
    alerts = []
    macro = config.get('macro', {})
    sent_today = state.get('alerts_sent_today', [])

    # WTI
    wti_t = macro.get('wti_ticker', 'CL=F')
    if wti_t in prices:
        wti = prices[wti_t]['price']
        wti_prev = state.get('prev_wti', wti)
        wti_open = state.get('wti_open', wti)

        # 30-Min-Momentum
        if wti_prev > 0:
            wti_30m = (wti - wti_prev) / wti_prev * 100
            threshold = macro.get('wti_30m_alert_pct', 3.0)
            if abs(wti_30m) >= threshold:
                mkey = 'MACRO_WTI_30M'
                if mkey not in sent_today:
                    direction = '📈' if wti_30m > 0 else '📉'
                    alerts.append(f"{direction} ÖL-MOMENTUM: WTI {wti_30m:+.1f}% in 30 Min (${wti_prev:.2f} → ${wti:.2f}) — EQNR + Öl-Thesis beachten!")
                    sent_today.append(mkey)

        # Tagesbewegung
        if wti_open > 0:
            wti_daily = (wti - wti_open) / wti_open * 100
            threshold_d = macro.get('wti_daily_alert_pct', 5.0)
            if abs(wti_daily) >= threshold_d:
                dkey = 'MACRO_WTI_DAILY'
                if dkey not in sent_today:
                    alerts.append(f"🛢️ ÖL TAGES-ALERT: WTI {wti_daily:+.1f}% (${wti_open:.2f} → ${wti:.2f})")
                    sent_today.append(dkey)

        state['prev_wti'] = wti
        if 'wti_open' not in state or state.get('date') != datetime.now(timezone.utc).strftime('%Y-%m-%d'):
            state['wti_open'] = wti

    # VIX
    vix_t = macro.get('vix_ticker', '^VIX')
    if vix_t in prices:
        vix = prices[vix_t]['price']
        vix_open = state.get('vix_open', vix)

        if 'vix_open' not in state or state.get('date') != datetime.now(timezone.utc).strftime('%Y-%m-%d'):
            state['vix_open'] = vix

        vix_delta = vix - vix_open
        threshold_v = macro.get('vix_spike_delta', 5.0)
        if vix_delta >= threshold_v:
            vkey = 'MACRO_VIX_SPIKE'
            if vkey not in sent_today:
                alerts.append(f"🔴 VIX SPIKE: +{vix_delta:.1f} Punkte ({vix_open:.1f} → {vix:.1f}) — Risk-Off! Alle Stops prüfen!")
                sent_today.append(vkey)

    state['alerts_sent_today'] = sent_today
    return alerts


# ─── EMA Cache ──────────────────────────────────────────────────────

def get_ema_data(ticker: str) -> dict | None:
    """
    Holt EMA20/EMA50 für einen Yahoo-Ticker.
    Gecacht für 1 Stunde in ema-cache.json — nicht bei jedem 15-Min-Run fetchen.
    Returns: {'ema20': float, 'ema50': float, 'price': float} oder None
    """
    cache = load_json(EMA_CACHE_PATH, {})
    now_ts = time.time()

    # Cache-Hit prüfen (< 1 Stunde alt)
    if ticker in cache:
        entry = cache[ticker]
        if now_ts - entry.get('fetched_at', 0) < 3600:
            return entry

    # Yahoo Finance — 3 Monate Tagesdaten für EMA50
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=3mo'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        result = data['chart']['result'][0]
        closes = [v for v in (result['indicators']['quote'][0].get('close') or []) if v is not None]

        if len(closes) < 20:
            return None

        def ema(prices: list, period: int) -> float:
            k = 2 / (period + 1)
            val = prices[0]
            for p in prices[1:]:
                val = p * k + val * (1 - k)
            return val

        entry = {
            'ema20': round(ema(closes, 20), 4),
            'ema50': round(ema(closes, min(50, len(closes))), 4),
            'price': closes[-1],
            'fetched_at': now_ts,
        }
        cache[ticker] = entry
        save_json(EMA_CACHE_PATH, cache)
        return entry

    except Exception as e:
        log(f"EMA FEHLER {ticker}: {e}")
        return None


# ─── Strategie-Status Parser ─────────────────────────────────────────

def get_strategy_statuses() -> dict:
    """
    Liest alle Strategie-Status aus strategien.md.
    Returns: {1: '🟢🔥', 2: '🟢', 3: '🟡', ...}
    """
    try:
        content = STRATEGIEN_PATH.read_text(encoding='utf-8')
    except FileNotFoundError:
        return {}

    result = {}
    for num in range(1, 8):
        pattern = rf'## STRATEGIE [S]?{num}[:\s].*?\*\*Status:\s*([^\*]+)\*\*'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            status_raw = match.group(1).strip()
            emoji_match = re.match(r'([\U0001F7E2\U0001F7E1\U0001F534🔥⬆️🚨]+)', status_raw)
            if emoji_match:
                result[num] = emoji_match.group(1)
            else:
                # Fallback: erstes Zeichen wenn Unicode-Match fehlschlägt
                result[num] = status_raw[:4]
    return result


_TICKER_TO_STRATEGY = {
    'EQNR': 1, 'EQNR.OL': 1, 'DR0.DE': 1, 'CL=F': 1, 'A3D42Y': 1, 'OIH': 1,
    'ISPA.DE': 1, 'AG': 1, 'A2QQ9R': 1, 'TAN': 1,
    'RHM.DE': 2, 'BAYN.DE': 2,
    'NVDA': 3, 'MSFT': 3, 'PLTR': 3, 'A14WU5': 3, 'CIBR': 3,
    'ISPA': 4, 'GLD': 4,
    'RIO.L': 5, 'BHP.L': 5,
    'A2DWAW': 7, 'IBB': 7,
}


def conviction_score(ticker: str, alert_type: str, price_eur: float,
                     stop_eur: float | None, entry_eur: float,
                     vix: float | None, strategy_statuses: dict) -> dict:
    """
    Berechnet einen 0–100 Conviction Score basierend auf 5 Faktoren.

    F1: Trend (Preis vs EMA20/50)   +20 über beide | 0 über eine | -20 unter beide
    F2: Volume (immer 0 — nicht von Yahoo 5m verfügbar ohne extra Call)
    F3: VIX Regime                  +20 <20 | 0 20-25 | -10 25-30 | -20 >30
    F4: Stop-Abstand                +20 >5% | 0 3-5% | -20 <3%
    F5: Strategie-Status            +20 🟢 | 0 🟡 | -20 🔴

    Returns: {'score': int, 'factors': dict, 'recommendation': str}
    """
    factors = {'trend': 0, 'volume': 0, 'vix': 0, 'stop_abstand': 0, 'strategie': 0}

    # F1: Trend (EMA)
    yahoo_ticker = ticker  # Für ETFs wäre das der ETF-Ticker, für Onvista-Stocks schwierig
    ema_data = get_ema_data(yahoo_ticker) if yahoo_ticker else None
    if ema_data and price_eur and ema_data.get('ema50'):
        # EMA in nativer Währung, Price in EUR — nur wenn USD-Position
        # Vereinfacht: Preis-Relation zum EMA-Verhältnis
        ema20 = ema_data['ema20']
        ema50 = ema_data['ema50']
        native_price = ema_data['price']
        if native_price > 0 and ema20 > 0 and ema50 > 0:
            if native_price > ema20 and native_price > ema50:
                factors['trend'] = 20
            elif native_price < ema20 and native_price < ema50:
                factors['trend'] = -20
            else:
                factors['trend'] = 0

    # F2: Volume — nicht zuverlässig verfügbar, immer 0
    factors['volume'] = 0

    # F3: VIX
    if vix is not None:
        if vix < 20:
            factors['vix'] = 20
        elif vix <= 25:
            factors['vix'] = 0
        elif vix <= 30:
            factors['vix'] = -10
        else:
            factors['vix'] = -20

    # F4: Stop-Abstand
    if stop_eur and price_eur and price_eur > 0:
        abstand_pct = (price_eur - stop_eur) / price_eur * 100
        if abstand_pct > 5:
            factors['stop_abstand'] = 20
        elif abstand_pct >= 3:
            factors['stop_abstand'] = 0
        else:
            factors['stop_abstand'] = -20
    else:
        # Kein Stop = kein Risikomanagement → neutral
        factors['stop_abstand'] = 0

    # F5: Strategie-Status
    s_num = _TICKER_TO_STRATEGY.get(ticker, 0)
    s_status = strategy_statuses.get(s_num, '🟡')
    if '🟢' in s_status:
        factors['strategie'] = 20
    elif '🔴' in s_status:
        factors['strategie'] = -20
    else:
        factors['strategie'] = 0

    score = max(0, min(100, 50 + sum(factors.values())))

    if score >= 80:
        recommendation = 'Starkes Signal'
    elif score >= 50:
        recommendation = 'Moderates Signal'
    elif score >= 20:
        recommendation = 'Schwaches Signal — Vorsicht'
    else:
        recommendation = 'Kein Entry / Exit prüfen'

    return {'score': score, 'factors': factors, 'recommendation': recommendation}


# ─── State Snapshot ──────────────────────────────────────────────────

def update_state_snapshot(config: dict, export: dict, strategy_statuses: dict,
                          conviction_scores: dict, all_alerts: list):
    """
    Schreibt memory/state-snapshot.md — der "Weckbrief" für den nächsten Agenten.
    Wird am Ende jeden Monitor-Laufs überschrieben.
    """
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    positions = export.get('positions', {})
    watchlist_data = export.get('watchlist', {})
    macro = export.get('macro', {})
    fx = export.get('fx', {})

    # ─── Portfolio-Tabelle ───
    portfolio_rows = []
    critical_alerts = []

    for key, p in positions.items():
        price = p.get('price_eur', 0)
        entry = p.get('entry_eur', 0)
        pnl = p.get('pnl_pct', 0)
        stop = p.get('stop_eur')
        name = p.get('name', key)
        conv = conviction_scores.get(key, {})
        conv_score = conv.get('score', '—')
        last_alert = _last_alert_for(key, all_alerts)

        pnl_str = f"{pnl:+.1f}%"
        price_str = f"{price:.2f}€"
        stop_str = f"{stop:.2f}€" if stop else "—"

        # Stop-Nähe berechnen für kritische Alerts
        if stop and price and price > 0:
            margin_pct = (price - stop) / price * 100
            if margin_pct < 3:
                critical_alerts.append(
                    f"⚠️ {name} ({key}): {margin_pct:.1f}% über Stop {stop_str} — Montag 09:00 beobachten"
                )

        portfolio_rows.append(
            f"| {name} ({key}) | {price_str} | {entry:.2f}€ | {pnl_str} | {stop_str} | {conv_score} | {last_alert} |"
        )

    portfolio_table = (
        "| Aktie | Kurs | Entry | P&L | Stop | Conviction | Letzter Alert |\n"
        "|---|---|---|---|---|---|---|\n"
        + "\n".join(portfolio_rows)
    )

    # ─── Watchlist-Tabelle ───
    watchlist_rows = []
    for key, w in watchlist_data.items():
        wconf = config.get('watchlist', {}).get(key, {})
        name = w.get('name', key)
        price_r = w.get('price_raw', w.get('price_eur', '?'))
        currency = wconf.get('currency', 'USD')
        signal = _watchlist_signal_text(wconf, w)
        watchlist_rows.append(f"| {name} ({key}) | {price_r} {currency} | {signal} | Beobachten |")

    watchlist_table = (
        "| Aktie | Kurs | Signal | Status |\n"
        "|---|---|---|---|\n"
        + "\n".join(watchlist_rows)
    ) if watchlist_rows else "_(keine Watchlist-Daten)_"

    # ─── Makro-Tabelle ───
    vix = macro.get('vix', 0)
    wti = macro.get('wti', 0)
    eurusd = fx.get('EURUSD', 0)

    vix_trend = '↑' if vix > 25 else ('→' if vix > 20 else '↓')
    vix_signal = '🔴 Panik' if vix > 30 else ('🟡 Erhöht' if vix > 20 else '🟢 Normal')
    wti_signal = '🔴 Nahe $100' if wti > 95 else ('🟡 Erhöht' if wti > 85 else '🟢 Normal')

    macro_table = (
        "| Indikator | Wert | Trend | Signal |\n"
        "|---|---|---|---|\n"
        f"| VIX | {vix:.1f} | {vix_trend} | {vix_signal} |\n"
        f"| WTI | ${wti:.2f} | ↑ | {wti_signal} |\n"
        f"| EUR/USD | {eurusd:.4f} | — | Neutral |"
    )

    # ─── Strategie-Status-Tabelle ───
    strategy_names = {
        1: 'Iran/Öl', 2: 'Rüstung', 3: 'KI-Halbleiter',
        4: 'Silber/Gold', 5: 'Rohstoffe/Kupfer', 6: 'Solar/Energie', 7: 'Biotech'
    }
    strat_rows = []
    for num in range(1, 8):
        status = strategy_statuses.get(num, '🟡')
        name = strategy_names.get(num, f'S{num}')
        strat_rows.append(f"| S{num} | {name} | {status} | Heute |")

    strat_table = (
        "| # | Strategie | Status | Letztes Update |\n"
        "|---|---|---|---|\n"
        + "\n".join(strat_rows)
    )

    # ─── Offene Alerts ───
    # Aus alert-queue.json + kritische Positionen
    queue_path = WORKSPACE / 'memory' / 'alert-queue.json'
    queue = load_json(queue_path, [])
    pending_alerts = [f"🔔 {q['message'][:100]}" for q in queue[-5:]] if queue else []

    all_action_items = critical_alerts + pending_alerts
    if not all_action_items:
        all_action_items = ['✅ Keine kritischen Alerts']

    action_list = '\n'.join(f"- {a}" for a in all_action_items)

    # ─── Conviction Scores Tabelle ───
    conv_rows = []
    for key, conv in conviction_scores.items():
        if conv:
            conv_rows.append(
                f"| {key} | {conv.get('score', '?')} | {conv.get('recommendation', '—')} |"
            )

    conv_table = (
        "| Ticker | Score | Empfehlung |\n"
        "|---|---|---|\n"
        + "\n".join(conv_rows)
    ) if conv_rows else "_(Conviction Scores noch nicht berechnet)_"

    # ─── Snapshot zusammenbauen ───
    pos_count = len(positions)
    snapshot = f"""# State Snapshot — Trading Bot
**Zuletzt aktualisiert:** {now}
**Positionen:** {pos_count} | **Alerts heute:** {len(all_alerts)} | **Queue:** {len(queue)} ausstehend

---

## Portfolio ({pos_count} Positionen)

{portfolio_table}

## Watchlist

{watchlist_table}

## Makro

{macro_table}

## Strategien-Status

{strat_table}

## Offene Alerts / Handlungsbedarf

{action_list}

## Letzte Conviction Scores

{conv_table}

---
*Wird automatisch bei jedem Monitor-Lauf (alle 15 Min) überschrieben.*
*Nächster Agent: Lies diese Datei zuerst — sie ist die Basis für Morgen-Briefing + Strategie-Checks.*
"""
    SNAPSHOT_PATH.write_text(snapshot, encoding='utf-8')
    log(f"State Snapshot geschrieben: {pos_count} Positionen, {len(all_alerts)} Alerts")


def _last_alert_for(ticker: str, alerts: list) -> str:
    """Gibt den letzten Alert-Typ für einen Ticker zurück."""
    for alert in reversed(alerts):
        if ticker in alert:
            if 'STOP' in alert.upper():
                return 'Stop-Warnung'
            if 'ZIEL' in alert.upper():
                return 'Ziel erreicht'
            if 'TRAIL' in alert.upper():
                return 'Trailing'
            return 'Signal'
    return '—'


def _watchlist_signal_text(wconf: dict, wdata: dict) -> str:
    """Gibt den aktuellen Signal-Status einer Watchlist-Position zurück."""
    price_eur = wdata.get('price_eur', 0)
    if not price_eur:
        return '—'

    sig_a = wconf.get('signal_a_above_eur')
    sig_b = wconf.get('signal_b_below_eur')
    entry_b = wconf.get('entry_b_below_eur')
    ea_usd = wconf.get('entry_a_above_usd')
    eb_usd = wconf.get('entry_b_below_usd')
    price_raw = wdata.get('price_raw', 0)

    if sig_a and price_eur >= sig_a:
        return f'Signal A aktiv (>{sig_a}€)'
    if sig_b and price_eur <= sig_b:
        return f'Signal B aktiv (<{sig_b}€)'
    if entry_b and price_eur <= entry_b:
        return f'Entry B Zone (<{entry_b}€)'
    if ea_usd and price_raw >= ea_usd:
        return f'Entry A aktiv (>${ea_usd})'
    if eb_usd and price_raw <= eb_usd:
        return f'Entry B aktiv (<${eb_usd})'
    return 'Kein Signal'


def write_overnight_context(export: dict, all_alerts: list, strategy_statuses: dict):
    """
    Schreibt memory/overnight-context.md — Tagesabschluss für Morgen-Briefing.
    Nur aufrufen wenn Tagesende (nach 22:00) oder explizit.
    """
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    today = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime('%d.%m.%Y')
    macro = export.get('macro', {})
    positions = export.get('positions', {})

    # Wichtigste Positionen nach P&L sortieren
    sorted_pos = sorted(positions.items(), key=lambda x: x[1].get('pnl_pct', 0))
    losers = [(k, v) for k, v in sorted_pos if v.get('pnl_pct', 0) < 0][:3]
    winners = [(k, v) for k, v in reversed(sorted_pos) if v.get('pnl_pct', 0) > 0][:3]

    # Kritische Stops
    crit_stops = []
    for key, p in positions.items():
        stop = p.get('stop_eur')
        price = p.get('price_eur', 0)
        if stop and price:
            margin = (price - stop) / price * 100
            if margin < 3:
                crit_stops.append(f"{p['name']} ({key}): {margin:.1f}% über Stop {stop:.2f}€")

    winners_str = '\n'.join(
        f"- {v['name']} ({k}): {v['price_eur']:.2f}€ ({v['pnl_pct']:+.1f}%)" for k, v in winners
    ) or '— keine'
    losers_str = '\n'.join(
        f"- {v['name']} ({k}): {v['price_eur']:.2f}€ ({v['pnl_pct']:+.1f}%)" for k, v in losers
    ) or '— keine'
    alerts_str = '\n'.join(f"- {a[:120]}" for a in all_alerts[-10:]) or '— keine Alerts heute'
    crit_str = '\n'.join(f"- ⚠️ {c}" for c in crit_stops) or '— alle Stops sicher'

    strat_names = {1: 'Iran/Öl', 2: 'Rüstung', 3: 'KI-Halbleiter',
                   4: 'Silber/Gold', 5: 'Rohstoffe', 6: 'Solar', 7: 'Biotech'}
    strat_str = '\n'.join(
        f"- S{n} ({strat_names.get(n, '?')}): {s}" for n, s in strategy_statuses.items()
    )

    content = f"""# Overnight Context — {today}
*Erstellt: {now} | Für Morgen-Briefing 08:00*

---

## Was heute passiert ist

### Wichtigste Alerts
{alerts_str}

### Top-Performer heute
{winners_str}

### Underperformer / Verlierer
{losers_str}

## Kritische Positionen (Stop <3% entfernt)

{crit_str}

## Geopolitik-Lage (aus Strategie-Status)

{strat_str}

## Makro-Schlusskurse

- VIX: {macro.get('vix', '?')}
- WTI: ${macro.get('wti', '?')}
- EUR/USD: {export.get('fx', {}).get('EURUSD', '?')}

## Entscheidungen die morgen anstehen

- [ ] Alle Stops in Trade Republic prüfen (besonders kritische oben)
- [ ] Morgen-Briefing: Geopolitik-Lage Iran checken (Kharg Island Reaktion)
- [ ] Conviction-Scores bei Stop-nahen Positionen neu bewerten

---
*Morgen-Agent: Lies state-snapshot.md + diese Datei → dann Morgen-Briefing ausführen*
"""
    OVERNIGHT_PATH.write_text(content, encoding='utf-8')
    log(f"Overnight Context geschrieben: {today}")


# ─── Main ────────────────────────────────────────────────────────────

def main():
    config = load_json(CONFIG_PATH)
    if not config:
        log("FEHLER: trading_config.json nicht gefunden oder leer!")
        print("FEHLER: Config nicht gefunden")
        return

    # State laden (tagesabhängig)
    state = load_json(STATE_PATH, {})
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if state.get('date') != today:
        # Neuer Tag → State zurücksetzen
        state = {
            'date': today,
            'alerts_sent_today': [],
            'run_count': 0,
        }

    state['run_count'] = state.get('run_count', 0) + 1

    # ─── Alle Yahoo-Ticker sammeln ───
    yahoo_tickers = set()

    # FX
    yahoo_tickers.update(['EURUSD=X', 'EURNOK=X', 'GBPEUR=X'])

    # Macro
    yahoo_tickers.add(config.get('macro', {}).get('wti_ticker', 'CL=F'))
    yahoo_tickers.add(config.get('macro', {}).get('vix_ticker', '^VIX'))

    # Positionen
    for pos in config.get('positions', {}).values():
        if pos.get('yahoo'):
            yahoo_tickers.add(pos['yahoo'])

    # Watchlist
    for watch in config.get('watchlist', {}).values():
        if watch.get('yahoo'):
            yahoo_tickers.add(watch['yahoo'])

    # ─── Batch-Fetch ───
    log(f"Fetching {len(yahoo_tickers)} Yahoo tickers + Onvista...")
    prices = yahoo_batch(list(yahoo_tickers))

    # FX-Rates extrahieren
    fx = {}
    for fx_key, fx_ticker in [('EURUSD', 'EURUSD=X'), ('EURNOK', 'EURNOK=X'), ('GBPEUR', 'GBPEUR=X')]:
        if fx_ticker in prices:
            fx[fx_key] = prices[fx_ticker]['price']

    if not fx.get('EURUSD'):
        log("WARNUNG: EUR/USD nicht verfügbar — Konvertierungen eingeschränkt")

    # ─── Strategie-Status laden ───
    strategy_statuses = get_strategy_statuses()

    # ─── Conviction Cache (wird in check_positions befüllt) ───
    conviction_cache = {}

    # ─── Alle Checks ausführen ───
    all_alerts = []
    all_alerts += check_positions(config, prices, fx, state, strategy_statuses, conviction_cache)
    all_alerts += check_watchlist(config, prices, fx, state)
    all_alerts += check_macro(config, prices, state)

    # ─── Alerts senden ───
    for alert in all_alerts:
        send_alert(alert)

    # ─── State speichern ───
    state['last_run'] = datetime.now(timezone.utc).isoformat()
    save_json(STATE_PATH, state)

    # ─── Preise für AI-Jobs exportieren ───
    # Die AI-Analyse-Jobs (Morgen-Briefing etc.) können diese Datei lesen
    # statt selbst Yahoo aufzurufen
    export = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'fx': fx,
        'macro': {},
        'positions': {},
        'watchlist': {},
    }

    # Macro
    wti_t = config.get('macro', {}).get('wti_ticker', 'CL=F')
    vix_t = config.get('macro', {}).get('vix_ticker', '^VIX')
    if wti_t in prices:
        export['macro']['wti'] = prices[wti_t]['price']
    if vix_t in prices:
        export['macro']['vix'] = prices[vix_t]['price']

    # Positionen
    for key, pos in config.get('positions', {}).items():
        yahoo_t = pos.get('yahoo')
        onvista_url = pos.get('onvista')
        price_eur = None
        price_raw = None

        if onvista_url:
            price_raw = onvista_price(onvista_url)
            price_eur = price_raw
        elif yahoo_t and yahoo_t in prices:
            price_raw = prices[yahoo_t]['price']
            price_eur = to_eur(price_raw, pos.get('currency', 'USD'), fx)

        if price_eur is not None:
            entry = pos.get('entry_eur', 0)
            pnl = (price_eur - entry) / entry * 100 if entry else 0
            export['positions'][key] = {
                'name': pos['name'],
                'price_eur': round(price_eur, 2),
                'price_raw': round(price_raw, 2) if price_raw else None,
                'entry_eur': entry,
                'pnl_pct': round(pnl, 2),
                'stop_eur': pos.get('stop_eur'),
            }

    # Watchlist
    for key, watch in config.get('watchlist', {}).items():
        yahoo_t = watch.get('yahoo')
        onvista_url = watch.get('onvista')
        price_raw = None
        price_eur = None

        if onvista_url:
            price_raw = onvista_price(onvista_url)
            price_eur = price_raw
        elif yahoo_t and yahoo_t in prices:
            price_raw = prices[yahoo_t]['price']
            price_eur = to_eur(price_raw, watch.get('currency', 'USD'), fx)

        if price_raw is not None:
            export['watchlist'][key] = {
                'name': watch['name'],
                'price_eur': round(price_eur, 2) if price_eur else None,
                'price_raw': round(price_raw, 2),
            }

    # ─── Conviction Scores in latest-prices.json speichern ───
    for key, conv in conviction_cache.items():
        if key in export['positions']:
            export['positions'][key]['conviction'] = conv.get('score')
    save_json(PRICES_PATH, export)

    # ─── State Snapshot schreiben ───
    update_state_snapshot(config, export, strategy_statuses, conviction_cache, all_alerts)

    # ─── Overnight Context (nur nach 21:00 Uhr Berlin) ───
    berlin_hour = (datetime.now(timezone.utc) + timedelta(hours=1)).hour
    if berlin_hour >= 21:
        write_overnight_context(export, all_alerts, strategy_statuses)

    # ─── Summary ───
    if all_alerts:
        print(f"ALERTS: {len(all_alerts)}")
        for a in all_alerts:
            print(f"  → {a[:120]}")
    else:
        pos_summary = []
        for key, p in export.get('positions', {}).items():
            pos_summary.append(f"{key} {p['price_eur']:.2f}€ ({p['pnl_pct']:+.1f}%)")
        macro_s = f"WTI ${export['macro'].get('wti', '?')} | VIX {export['macro'].get('vix', '?')}"
        print(f"KEIN_SIGNAL | {macro_s} | {' | '.join(pos_summary)}")


if __name__ == '__main__':
    main()
