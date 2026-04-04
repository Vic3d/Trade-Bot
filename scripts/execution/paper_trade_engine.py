#!/usr/bin/env python3
"""
Paper Trade Engine v1 — Autonome Paper Trade Ausführung
========================================================
Verbindet: Signal → VIX Guard → Conviction Check → Entry → Logging

Wird aufgerufen:
  - Aus trading_monitor.py wenn ein Watchlist-Setup getriggert wird
  - Via Cron (täglich 09:00) für Gap-Up Setups
  - Via CLI: python3 paper_trade_engine.py propose TICKER STRATEGY ENTRY STOP TARGET

Regeln:
  1. VIX Hard Block (via conviction_scorer.check_entry_allowed)
  2. Conviction Score ≥ ENTRY_THRESHOLD (Standard: 52)
  3. Max Positionen nicht überschritten
  4. Kein Duplikat gleicher Ticker
  5. Earnings Blackout (3 Tage vor Earnings kein Entry)

Albert 🎩 | v1.0 | 29.03.2026
"""

import sqlite3, json, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'intelligence'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'execution'))

DB_PATH = Path('/data/.openclaw/workspace/data/trading.db')
WORKSPACE = Path('/data/.openclaw/workspace')
PAPER_CFG = WORKSPACE / 'data' / 'paper_config.json'
ALERT_QUEUE = WORKSPACE / 'memory' / 'alert-queue.json'

ENTRY_THRESHOLD_DEFAULT = 52   # Generische Strategien
ENTRY_THRESHOLD_THESIS  = 35   # PS_* Thesis-Plays (Deep Dive validiert)
ENTRY_THRESHOLD = 52           # Rückwärtskompatibilität
MAX_POSITIONS = 15        # Maximale offene Paper-Positionen
DEFAULT_POSITION_EUR = 2000  # € pro Position wenn keine Config
FEE_PER_TRADE = 1.0      # Trade Republic Gebühr

# ─── DB Helper ───────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def load_config() -> dict:
    try:
        return json.loads(PAPER_CFG.read_text())
    except Exception:
        return {'capital': 25000, 'fee_per_trade': 1.0, 'position_sizing': {}}


def get_free_cash(conn) -> float:
    """Freies Cash aus paper_fund."""
    row = conn.execute("SELECT value FROM paper_fund WHERE key='cash'").fetchone()
    return row['value'] if row else 10000.0


def get_open_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'").fetchone()[0]


def has_open_position(conn, ticker: str) -> bool:
    row = conn.execute(
        "SELECT id FROM paper_portfolio WHERE ticker=? AND status='OPEN'", (ticker.upper(),)
    ).fetchone()
    return row is not None


def get_sector(ticker: str) -> str:
    """Liest Sektor aus ticker_meta oder trading_config."""
    try:
        cfg = json.loads((WORKSPACE / 'trading_config.json').read_text())
        return cfg.get('sector_map', {}).get(ticker.upper(), 'UNKNOWN')
    except Exception:
        return 'UNKNOWN'


def get_sector_count(conn, sector: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM paper_portfolio WHERE sector=? AND status='OPEN'", (sector,)
    ).fetchone()[0]


def yahoo_price(ticker: str) -> float | None:
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
        return data['chart']['result'][0]['meta'].get('regularMarketPrice')
    except Exception:
        return None


# ─── Preisdaten für Watchlist-Ticker in trading.db laden ────────────

def sync_prices_for_tickers(tickers: list):
    """
    Holt aktuelle Kurse + Volumen für alle übergebenen Ticker von Yahoo
    und schreibt sie in trading.db:prices.
    Stellt sicher dass Conviction Scorer echte Daten hat.
    """
    import time as _time
    conn = get_db()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    inserted = 0

    for ticker in tickers:
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.load(r)
            result = data['chart']['result'][0]
            timestamps = result.get('timestamp', [])
            quote = result['indicators']['quote'][0]
            closes  = quote.get('close', [])
            volumes = quote.get('volume', [])
            opens   = quote.get('open', [])
            highs   = quote.get('high', [])
            lows    = quote.get('low', [])

            for i, ts in enumerate(timestamps):
                date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
                c = closes[i] if i < len(closes) else None
                v = volumes[i] if i < len(volumes) else None
                o = opens[i]   if i < len(opens)   else None
                h = highs[i]   if i < len(highs)   else None
                l = lows[i]    if i < len(lows)    else None
                if c is None:
                    continue
                conn.execute("""
                    INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (ticker, date_str, o, h, l, c, v))
                inserted += 1

            conn.commit()
            _time.sleep(0.3)
        except Exception as e:
            pass  # Ticker nicht verfügbar — weiter

    conn.close()
    return inserted


def sync_watchlist_prices():
    """Synct Preise für alle Watchlist-Ticker aus trading_config.json."""
    try:
        cfg = json.loads((WORKSPACE / 'trading_config.json').read_text())
        tickers = [w.get('yahoo') or w.get('ticker') for w in cfg.get('watchlist', []) if w.get('ticker')]
        tickers = list(set(t for t in tickers if t))
        inserted = sync_prices_for_tickers(tickers)
        return inserted
    except Exception as e:
        return 0


# ─── VIX & Regime aktualisieren ──────────────────────────────────────

def refresh_vix_in_db():
    """Holt aktuellen VIX von Yahoo und schreibt in macro_daily."""
    vix = yahoo_price('^VIX')
    if vix is None:
        return None
    
    conn = get_db()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    conn.execute("""
        INSERT OR REPLACE INTO macro_daily (date, indicator, value)
        VALUES (?, 'VIX', ?)
    """, (today, round(vix, 2)))
    conn.commit()
    
    # Auch regime_history aktualisieren (einfach, nur VIX-basiert)
    from conviction_scorer import _get_current_regime
    # Importiere classify_regime aus regime_detector
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / 'intelligence'))
        from regime_detector import classify_regime, detect_current_regime
        detect_current_regime()  # schreibt auch regime_history
    except Exception as e:
        # Fallback: einfaches VIX-Mapping
        if vix >= 35:
            regime = 'CRISIS'
        elif vix >= 30:
            regime = 'BEAR'
        elif vix >= 25:
            regime = 'CORRECTION'
        elif vix >= 20:
            regime = 'NEUTRAL'
        elif vix >= 15:
            regime = 'BULL_VOLATILE'
        else:
            regime = 'BULL_CALM'
        
        conn.execute("""
            INSERT OR REPLACE INTO regime_history (date, regime, vix)
            VALUES (?, ?, ?)
        """, (today, regime, round(vix, 2)))
        conn.commit()
    
    conn.close()
    return vix


# ─── Alert-Queue ─────────────────────────────────────────────────────

def queue_alert(message: str):
    """Schreibt Alert in alert-queue.json für Discord-Delivery."""
    queue = []
    if ALERT_QUEUE.exists():
        try:
            queue = json.loads(ALERT_QUEUE.read_text())
        except Exception:
            queue = []
    
    queue.append({
        'message': message,
        'target': '452053147620343808',
        'ts': datetime.now(timezone.utc).isoformat(),
    })
    ALERT_QUEUE.write_text(json.dumps(queue, indent=2))


# ─── Core: Trade Entry ───────────────────────────────────────────────

def execute_paper_entry(
    ticker: str,
    strategy: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    thesis: str = '',
    style: str = 'swing',
    source: str = 'auto',
) -> dict:
    """
    Führt einen Paper Trade aus (nach allen Guards).
    
    Returns: {'success': bool, 'trade_id': int|None, 'message': str, 'blocked_by': str|None}
    """
    ticker = ticker.upper()
    
    # ── Guard 1: VIX Hard Block ──────────────────────────────────────
    # VIX aktualisieren bevor wir entscheiden
    vix = refresh_vix_in_db()
    
    try:
        from conviction_scorer import check_entry_allowed, calculate_conviction
        allowed, reason = check_entry_allowed(strategy)
        if not allowed:
            return {
                'success': False,
                'trade_id': None,
                'message': f'❌ VIX Block: {reason}',
                'blocked_by': 'vix_regime',
            }
    except Exception as e:
        reason = f'Regime check unavailable: {e}'
    
    # ── Guard 2: Conviction Score ────────────────────────────────────
    # PS_* = Thesis-Strategien (manuell Deep-Dive validiert) → niedrigere Schwelle
    is_thesis = strategy.upper().startswith('PS_')
    threshold = ENTRY_THRESHOLD_THESIS if is_thesis else ENTRY_THRESHOLD_DEFAULT

    try:
        conviction = calculate_conviction(ticker, strategy, entry_price, stop_price, target_price)
        conv_score = conviction['score']

        if conv_score < threshold:
            return {
                'success': False,
                'trade_id': None,
                'message': f'❌ Conviction zu niedrig: {conv_score:.0f} < {threshold} ({"Thesis" if is_thesis else "Standard"}-Threshold)',
                'blocked_by': 'conviction',
                'conviction_score': conv_score,
            }
    except Exception as e:
        conviction = {'score': 0, 'regime': 'UNKNOWN', 'vix': None}
        conv_score = 0
    
    conn = get_db()
    
    # ── Guard 3: Max Positionen ──────────────────────────────────────
    open_count = get_open_count(conn)
    if open_count >= MAX_POSITIONS:
        conn.close()
        return {
            'success': False,
            'trade_id': None,
            'message': f'❌ Max Positionen erreicht ({open_count}/{MAX_POSITIONS})',
            'blocked_by': 'max_positions',
        }
    
    # ── Guard 4: Kein Duplikat ───────────────────────────────────────
    if has_open_position(conn, ticker):
        conn.close()
        return {
            'success': False,
            'trade_id': None,
            'message': f'❌ {ticker} bereits offen',
            'blocked_by': 'duplicate',
        }
    
    # ── Guard 5: Sektor-Limit ────────────────────────────────────────
    sector = get_sector(ticker)
    sector_count = get_sector_count(conn, sector)
    max_sector = 4  # aus paper_config
    if sector_count >= max_sector:
        conn.close()
        return {
            'success': False,
            'trade_id': None,
            'message': f'❌ Sektor {sector} voll ({sector_count}/{max_sector} Positionen)',
            'blocked_by': 'sector_limit',
        }
    
    # ── Guard 6: Freies Cash ─────────────────────────────────────────
    free_cash = get_free_cash(conn)
    cfg = load_config()
    
    # Position Sizing: 2% Risiko-Methode
    risk_per_share = abs(entry_price - stop_price)
    portfolio_value = cfg.get('capital', 25000)
    if risk_per_share > 0 and entry_price > 0:
        max_risk_eur = portfolio_value * 0.02
        position_eur = min(
            round(max_risk_eur / (risk_per_share / entry_price), 2),
            cfg.get('position_sizing', {}).get('score_6_to_9', DEFAULT_POSITION_EUR),
            free_cash - 100  # mind. 100€ Cash-Reserve
        )
    else:
        position_eur = DEFAULT_POSITION_EUR
    
    if position_eur <= 0 or free_cash < position_eur:
        conn.close()
        return {
            'success': False,
            'trade_id': None,
            'message': f'❌ Nicht genug Cash: {free_cash:.0f}€ verfügbar, {position_eur:.0f}€ benötigt',
            'blocked_by': 'cash',
        }
    
    shares = round(position_eur / entry_price, 4)
    fees = FEE_PER_TRADE
    total_cost = shares * entry_price + fees
    
    # ── Entry ausführen ──────────────────────────────────────────────
    regime = conviction.get('regime', 'UNKNOWN')
    vix_val = conviction.get('vix', 0)
    now = datetime.now(timezone.utc).isoformat()
    
    conn.execute("""
        INSERT INTO paper_portfolio 
        (ticker, strategy, entry_price, entry_date, shares, stop_price, target_price,
         status, fees, notes, style, conviction, regime_at_entry, sector)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?)
    """, (
        ticker, strategy, entry_price, now, shares,
        stop_price, target_price, fees,
        f'[AUTO-ENTRY {source}] {thesis}', style,
        int(conv_score), regime, sector
    ))
    
    # Cash reduzieren
    conn.execute("""
        UPDATE paper_fund SET value = value - ? WHERE key = 'cash'
    """, (total_cost,))
    
    trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    # ── Phase 1: Feature Tracking ──
    _features = {}
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from feature_collector import collect_and_save, collect_features
        _features = collect_features(ticker)
        collect_and_save(trade_id, ticker)
    except Exception as _fe:
        print(f"  ⚠️  Feature Collector Fehler (nicht kritisch): {_fe}")

    # ── Phase 4: Online Model Prediction ──
    _win_prob = None
    try:
        from online_model import predict as _predict
        _pred = _predict(_features)
        _win_prob = _pred.get('win_probability')
        _interp = _pred.get('interpretation', '')
        _conf = _pred.get('confidence', '')
        if _win_prob is not None:
            print(f"  🧠 Modell-Prognose: {_win_prob:.0%} Win ({_conf}) — {_interp}")
    except Exception as _oe:
        print(f"  ⚠️  Online Model Fehler (nicht kritisch): {_oe}")

    # ── Phase 7: DNA Gate Check ──
    _dna_score = None
    _dna_violations = []
    try:
        from strategy_dna import check_dna_gate as _dna_check
        _dna = _dna_check(strategy, _features)
        _dna_score = _dna.get('score')
        _dna_status = _dna.get('status', 'UNKNOWN')
        _dna_violations = _dna.get('violations', [])
        if _dna_score is not None:
            _icon = {'GREEN': '🟢', 'YELLOW': '🟡', 'RED': '🔴'}.get(_dna_status, '⚫')
            print(f"  🧬 DNA Gate: {_icon} {_dna_score}/100 ({_dna_status})")
            for v in _dna_violations:
                print(f"     ⚠️  {v}")
    except Exception as _de:
        print(f"  ⚠️  DNA Gate Fehler (nicht kritisch): {_de}")

    # CRV berechnen
    reward = abs(target_price - entry_price)
    risk = abs(entry_price - stop_price)
    crv = round(reward / risk, 1) if risk > 0 else 0
    
    # Alert senden
    _prob_str = f" | 🧠 {_win_prob:.0%}" if _win_prob is not None else ""
    _dna_str = f" | 🧬 DNA {_dna_score}/100" if _dna_score is not None else ""
    _warn_str = ""
    if _dna_violations:
        _warn_str = "\n⚠️  " + " | ".join(_dna_violations[:2])
    msg = (
        f"📊 **PAPER TRADE ERÖFFNET** — {ticker}\n"
        f"Strategie: {strategy} | Entry: {entry_price:.2f}€\n"
        f"Stop: {stop_price:.2f}€ | Ziel: {target_price:.2f}€ | CRV: {crv}:1\n"
        f"Position: {position_eur:.0f}€ ({shares:.2f} Shares) | Conviction: {conv_score:.0f}/100{_prob_str}{_dna_str}\n"
        f"Regime: {regime} | VIX: {f'{vix_val:.1f}' if vix_val else 'n/a'}{_warn_str}\n"
        f"📝 {thesis[:120] if thesis else '(kein Thesis)'}"
    )
    queue_alert(msg)
    
    return {
        'success': True,
        'trade_id': trade_id,
        'message': msg,
        'blocked_by': None,
        'position_eur': position_eur,
        'shares': shares,
        'conviction_score': conv_score,
        'regime': regime,
        'crv': crv,
    }


# ─── Batch: Alle Watchlist-Setups aus trading_config prüfen ──────────

def scan_and_execute_watchlist():
    """
    Liest Watchlist aus trading_config.json, prüft Entry-Bedingungen,
    führt bei Erfüllung automatisch Paper Trades aus.
    
    Returns: list[dict] mit Ergebnissen
    """
    try:
        cfg = json.loads((WORKSPACE / 'trading_config.json').read_text())
    except Exception as e:
        return [{'error': f'Config not found: {e}'}]
    
    watchlist = cfg.get('watchlist', [])
    if not watchlist:
        return [{'info': 'Watchlist leer'}]

    # Preisdaten aktualisieren bevor Conviction berechnet wird
    sync_watchlist_prices()

    results = []
    
    for item in watchlist:
        ticker = item.get('ticker', '')
        strategy = item.get('strategy', 'S1')
        # Unterstütze verschiedene Key-Konventionen aus trading_config.json
        entry_low  = (item.get('entry_low_eur') or item.get('entry_low')
                      or item.get('entryMin') or 0)
        entry_high = (item.get('entry_high_eur') or item.get('entry_high')
                      or item.get('entryMax') or 0)
        stop    = (item.get('stop_eur') or item.get('stop') or 0)
        targets = item.get('targets', [])
        target  = (item.get('target1_eur') or item.get('target1')
                   or (targets[0] if targets else 0))
        thesis  = item.get('thesis', '')

        if not ticker or not entry_low or not stop or not target:
            continue
        
        # Aktuellen Preis holen
        current_price = yahoo_price(ticker)
        if current_price is None:
            results.append({'ticker': ticker, 'skipped': 'Kein Preis'})
            continue
        
        # Entry-Bedingung prüfen
        entry_mid = (entry_low + entry_high) / 2 if entry_high else entry_low
        
        if entry_low <= current_price <= (entry_high or entry_low * 1.03):
            # Entry-Zone getroffen → ausführen
            result = execute_paper_entry(
                ticker=ticker,
                strategy=strategy,
                entry_price=current_price,
                stop_price=stop,
                target_price=target,
                thesis=thesis,
                source='watchlist_scan',
            )
            results.append({'ticker': ticker, 'price': current_price, **result})
        else:
            results.append({
                'ticker': ticker,
                'price': current_price,
                'entry_zone': f'{entry_low}–{entry_high or entry_low}',
                'status': 'not_in_zone',
            })
    
    return results


# ─── CLI ─────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  paper_trade_engine.py propose TICKER STRATEGY ENTRY STOP TARGET [THESIS]")
        print("  paper_trade_engine.py scan        # Watchlist scannen + ausführen")
        print("  paper_trade_engine.py vix_check   # VIX Guard Status anzeigen")
        print("  paper_trade_engine.py refresh_vix # VIX in DB aktualisieren")
        return
    
    cmd = sys.argv[1].lower()
    
    if cmd == 'refresh_vix':
        vix = refresh_vix_in_db()
        print(f"✅ VIX aktualisiert: {vix:.2f}" if vix else "❌ VIX-Update fehlgeschlagen")
    
    elif cmd == 'vix_check':
        vix = refresh_vix_in_db()
        from conviction_scorer import check_entry_allowed
        allowed, reason = check_entry_allowed()
        conn = get_db()
        from conviction_scorer import _get_current_regime, _get_current_vix
        regime = _get_current_regime(conn)
        vix_db = _get_current_vix(conn)
        conn.close()
        print(f"═══ VIX Guard Status ═══")
        print(f"  VIX (live): {vix:.2f}" if vix else "  VIX: n/a")
        print(f"  VIX (DB):   {vix_db:.2f}" if vix_db else "  VIX (DB): n/a")
        print(f"  Regime:     {regime}")
        print(f"  Entry:      {'✅ ERLAUBT' if allowed else '🔴 GEBLOCKT'}")
        print(f"  Reason:     {reason}")
    
    elif cmd == 'scan':
        print("📡 Watchlist-Scan läuft...")
        results = scan_and_execute_watchlist()
        for r in results:
            ticker = r.get('ticker', '?')
            if r.get('success'):
                print(f"  ✅ {ticker}: Trade eröffnet (ID {r.get('trade_id')}, Conviction {r.get('conviction_score'):.0f})")
            elif 'blocked_by' in r:
                print(f"  ❌ {ticker}: {r.get('message', 'Blocked')}")
            elif r.get('status') == 'not_in_zone':
                print(f"  📍 {ticker}: {r.get('price'):.2f} — außerhalb Zone {r.get('entry_zone')}")
            else:
                print(f"  ⚪ {ticker}: {r}")
    
    elif cmd == 'propose' and len(sys.argv) >= 7:
        ticker   = sys.argv[2]
        strategy = sys.argv[3]
        entry    = float(sys.argv[4])
        stop     = float(sys.argv[5])
        target   = float(sys.argv[6])
        thesis   = sys.argv[7] if len(sys.argv) > 7 else ''
        
        result = execute_paper_entry(ticker, strategy, entry, stop, target, thesis, source='cli')
        if result['success']:
            print(f"✅ Trade #{result['trade_id']} eröffnet")
            print(result['message'])
        else:
            print(f"❌ Trade abgelehnt: {result['message']}")
    
    else:
        print(f"Unbekannter Befehl: {cmd}")


if __name__ == '__main__':
    main()
