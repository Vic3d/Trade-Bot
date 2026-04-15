#!/usr/bin/env python3.13
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
ENTRY_THRESHOLD_THESIS  = 40   # PS_* Thesis-Plays (Deep Dive validiert) — erhöht von 35
ENTRY_THRESHOLD = 52           # Rückwärtskompatibilität
MAX_POSITIONS = 15        # Maximale offene Paper-Positionen
DEFAULT_POSITION_EUR = 2000  # € pro Position wenn keine Config
FEE_PER_TRADE = 1.0      # Trade Republic Gebühr

# ─── DB Helper ───────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def load_config() -> dict:
    try:
        return json.loads(PAPER_CFG.read_text())
    except Exception:
        return {'capital': 25000, 'fee_per_trade': 1.0, 'position_sizing': {}}


def get_free_cash(conn) -> float:
    """Freies Cash aus paper_fund."""
    row = conn.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()
    if row:
        return row['value']
    # Fallback: try legacy 'cash' key
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
    """→ live_data.get_price_eur(). IMMER in EUR — NOK/DKK/GBp werden konvertiert.
    
    Behebt Currency-Bug: EQNR.OL (NOK), NOVO-B.CO (DKK), BA.L (GBp) wurden
    vorher in Lokalwährung gespeichert, aber in EUR verglichen → Fake-Verluste.
    """
    import sys as _sys
    _sys.path.insert(0, '/data/.openclaw/workspace/scripts/core')
    from live_data import get_price_eur
    return get_price_eur(ticker)

def is_price_fresh(ticker: str, max_days: int = 3) -> bool:
    """→ live_data.is_price_fresh()."""
    import sys as _sys
    _sys.path.insert(0, '/data/.openclaw/workspace/scripts/core')
    from live_data import is_price_fresh as _fresh
    return _fresh(ticker, max_days)


# ─── Preisdaten für Watchlist-Ticker in trading.db laden ────────────

def sync_prices_for_tickers(tickers: list):
    """→ live_data.refresh_prices_bulk(). Alle Preise kommen aus einer Quelle."""
    import sys as _sys
    _sys.path.insert(0, '/data/.openclaw/workspace/scripts/core')
    from live_data import refresh_prices_bulk
    results = refresh_prices_bulk(tickers)
    return sum(1 for v in results.values() if v is not None)


def _sync_prices_for_tickers_DEPRECATED(tickers: list):
    """DEPRECATED — nicht mehr verwenden. Nur als Referenz behalten."""
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
    """→ live_data.refresh_vix(). VIX kommt aus einer Quelle."""
    import sys as _sys
    _sys.path.insert(0, '/data/.openclaw/workspace/scripts/core')
    from live_data import refresh_vix as _rv
    vix = _rv()  # schreibt schon in DB
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

    # ── Style automatisch aus Strategie ableiten ──────────────────────
    try:
        import sys as _sys
        _sys.path.insert(0, '/data/.openclaw/workspace/scripts/core')
        from trade_style import classify_strategy, get_style_config, validate_stop_for_style, validate_crv_for_style
        if style == 'swing':  # nur überschreiben wenn default
            style = classify_strategy(strategy)
        style_cfg = get_style_config(style)
    except Exception:
        style_cfg = None

    # ── Guard 0a: Entry-Zeitfenster ──────────────────────────────────────────────
    # Daten: Morgen-Entries (07-11h) haben 0% Win-Rate über 10 Trades.
    # Abend-Entries (17-22h) haben 51% Win-Rate → nur in diesem Fenster.
    # Ausnahme: source='manual' darf immer (Victor handelt manuell), oder
    #           wenn explizit für Backtests aufgerufen.
    try:
        import zoneinfo as _zi
        _now_cet = datetime.now(_zi.ZoneInfo('Europe/Berlin'))
        _hour = _now_cet.hour
        _is_autonomous = source not in ('manual', 'backtest', 'cli', 'victor')
        # Morning Block entfernt (Victor 15.04.2026): kein Zeitfenster-Block mehr
        # Generelles Außerhalb-Fenster: 11-17h hat nur 34% WR → weiche Warnung, kein Block
    except Exception:
        pass  # Zeitcheck nicht kritisch

    # ── Guard 0: Preis-Frische ────────────────────────────────────────
    if not is_price_fresh(ticker, max_days=3):
        return {
            'success': False,
            'trade_id': None,
            'message': f'❌ {ticker}: Preisdaten älter als 3 Tage — kein Trade ohne frische Kurse',
            'blocked_by': 'stale_price',
        }

    # ── Guard 0b: Stop muss unter Entry liegen (Long) ─────────────
    if stop_price >= entry_price:
        return {
            'success': False,
            'trade_id': None,
            'message': f'❌ {ticker}: Stop ({stop_price:.2f}) >= Entry ({entry_price:.2f}) — ungültiger Trade',
            'blocked_by': 'invalid_stop',
        }

    # ── Guard 0c: Minimum CRV 2:1 ──────────────────────────────────
    _reward = abs(target_price - entry_price)
    _risk = abs(entry_price - stop_price)
    _crv = _reward / _risk if _risk > 0 else 0
    if _crv < 2.0:
        return {
            'success': False,
            'trade_id': None,
            'message': f'❌ {ticker}: CRV {_crv:.1f}:1 < 2.0:1 Minimum',
            'blocked_by': 'crv_minimum',
        }

    # ── Guard 0c3: Cost-Hurdle Gate (Phase 19a) ─────────────────────
    # Verhindert Trades deren Edge kleiner ist als die Round-Trip-Kosten.
    # Hintergrund: Bei ~0.75-1% Cost Drag pro Trade in US-Mid-Caps und
    # ~1% in EU-Mid-Caps fressen 100 Trades/Jahr sonst 75-100% des
    # Kapitals. Wir blocken Trades wo Reward-%  < 3x Round-Trip-Kosten.
    try:
        from execution.transaction_costs import get_profile as _tc_profile
        _prof = _tc_profile(ticker)
        # Round-trip cost in basis points (both sides + FX both sides if applicable)
        _rt_bps = 2 * (_prof.spread_bps + _prof.slippage_bps)
        if _prof.currency != 'EUR':
            _rt_bps += 2 * _prof.fx_spread_bps
        _rt_pct = _rt_bps / 100.0  # bps → %
        _reward_pct = (_reward / entry_price) * 100 if entry_price else 0
        _hurdle_pct = _rt_pct * 3.0  # need 3x cost coverage as safety margin
        if _reward_pct < _hurdle_pct:
            return {
                'success': False,
                'trade_id': None,
                'message': (
                    f'❌ {ticker}: Edge zu klein — Reward {_reward_pct:.2f}% '
                    f'< {_hurdle_pct:.2f}% Cost-Hurdle '
                    f'(Round-Trip {_rt_pct:.2f}% × 3 Safety). '
                    f'Market: {_prof.name}. Trading Gebühren würden Edge auffressen.'
                ),
                'blocked_by': 'cost_hurdle',
            }
    except Exception as _tc_e:
        import logging as _tc_log
        _tc_log.getLogger('paper_trade_engine').warning(f'cost-hurdle check skipped: {_tc_e}')

    # ── Guard 0: CEO Directive Check ────────────────────────────────────
    # CEO schreibt täglich sein Marktbild in ceo_directive.json.
    # Bei BEARISH oder HALT wird hier geblockt.
    try:
        ceo_file = WORKSPACE / 'data' / 'ceo_directive.json'
        if ceo_file.exists():
            ceo_d = json.loads(ceo_file.read_text(encoding='utf-8'))
            ceo_bias = ceo_d.get('market_bias', 'NEUTRAL').upper()
            ceo_halt = ceo_d.get('trading_halt', False)
            if ceo_halt:
                return {
                    'success': False,
                    'trade_id': None,
                    'message': f'❌ CEO Trading Halt aktiv: {ceo_d.get("halt_reason", "kein Grund angegeben")}',
                    'blocked_by': 'ceo_halt',
                }
            if ceo_bias == 'BEARISH':
                # Im Bärenmarkt: nur Thesis-Plays mit hoher Conviction erlaubt
                is_thesis = strategy.startswith(('PS_', 'PS', 'DT'))
                if not is_thesis:
                    return {
                        'success': False,
                        'trade_id': None,
                        'message': f'❌ CEO Bias BEARISH — nur Thesis-Plays erlaubt, kein {strategy}',
                        'blocked_by': 'ceo_bearish_bias',
                    }
    except Exception:
        pass  # CEO Direktive ist optional — bei Fehler weiter

    # ── Guard 0c2: Deep Dive Verdict Gate ───────────────────────────────────────
    # Philosophie: Der Deep Dive IST das Gate. Wenn eine Aktie interessant ist,
    # zuerst Deep Dive durchführen. Wenn Verdict = KAUFEN → Trade erlaubt.
    # Kein Verdict oder WARTEN/NICHT KAUFEN → Block für autonome Entries.
    # Victor kann mit source='manual' immer manuell übersteuern.
    _is_autonomous_entry = source not in ('manual', 'victor', 'cli')
    if _is_autonomous_entry:
        try:
            _verdicts_file = WORKSPACE / 'data' / 'deep_dive_verdicts.json'
            _verdict_data = {}
            if _verdicts_file.exists():
                _verdict_data = json.loads(_verdicts_file.read_text(encoding='utf-8'))

            _ticker_verdict = _verdict_data.get(ticker.upper(), {})
            _verdict = _ticker_verdict.get('verdict', '')

            # Source-Validierung: nur echte Deep Dives akzeptieren
            _verdict_source = _ticker_verdict.get('source', '')
            _trusted_sources = {'autonomous_ceo', 'discord_deepdive'}
            if _verdict_source and _verdict_source not in _trusted_sources:
                return {
                    'success': False,
                    'trade_id': None,
                    'message': (
                        f'❌ Deep Dive Guard: Verdict für {ticker} hat unvertrauenswürdige Quelle '
                        f'"{_verdict_source}". Nur autonomous_ceo oder discord_deepdive erlaubt. '
                        f'In Discord: "Deep Dive {ticker}" für echten Deep Dive.'
                    ),
                    'blocked_by': 'untrusted_verdict_source',
                }
            _verdict_date = _ticker_verdict.get('date', '')

            # Deep Dive veraltet wenn älter als 14 Tage
            _dd_fresh = False
            if _verdict_date:
                try:
                    _dd_age = (datetime.now() - datetime.fromisoformat(_verdict_date)).days
                    _dd_fresh = _dd_age <= 14
                except Exception:
                    pass

            if not _verdict or not _dd_fresh:
                # Kein Deep Dive → blocken und Anweisung ausgeben
                _age_hint = f'(letzter: {_verdict_date}, {_dd_age}d alt)' if _verdict_date else '(noch keiner)'
                return {
                    'success': False,
                    'trade_id': None,
                    'message': (
                        f'❌ Deep Dive Pflicht-Gate: Kein aktuelles Deep Dive Verdict für {ticker} {_age_hint}. '
                        f'In Discord eingeben: "Deep Dive {ticker}" '
                        f'→ Wenn Verdict = KAUFEN, wird Trade automatisch freigegeben.'
                    ),
                    'blocked_by': 'no_deep_dive_verdict',
                }

            if _verdict == 'NICHT_KAUFEN':
                return {
                    'success': False,
                    'trade_id': None,
                    'message': (
                        f'❌ Deep Dive Verdict: {ticker} = NICHT KAUFEN (vom {_verdict_date}). '
                        f'Deep Dive hat diesen Trade abgelehnt. '
                        f'Neue Analyse wenn sich Lage ändert: "Deep Dive {ticker}"'
                    ),
                    'blocked_by': 'deep_dive_nicht_kaufen',
                }

            if _verdict == 'WARTEN':
                return {
                    'success': False,
                    'trade_id': None,
                    'message': (
                        f'❌ Deep Dive Verdict: {ticker} = WARTEN (vom {_verdict_date}). '
                        f'Kein Entry bis sich die Situation klärt. '
                        f'Trigger-Bedingung erfüllt? Dann: "Deep Dive {ticker}" erneut.'
                    ),
                    'blocked_by': 'deep_dive_warten',
                }
            # KAUFEN: Trade freigegeben — weiter
        except Exception:
            pass  # Fehler im Gate → defensiv durchlassen (lieber kein Block als Blockade)

    # ── Guard 0d: Deep Dive Pre-Trade Gate ──────────────────────────────
    # Implementiert die Pflichtregeln aus deepdive-protokoll.md.
    # Verhindert "Falling Knife", "kein frischer Katalysator", "Aktie läuft
    # gegen eigenen Sektor"-Käufe — die häufigsten Bot-Fehler.
    try:
        conn_gate = get_db()
        rows_gate = conn_gate.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 126",
            (ticker,)
        ).fetchall()
        conn_gate.close()
        closes_gate = [r['close'] for r in rows_gate if r['close']]

        if len(closes_gate) >= 50:
            current_gate = entry_price or closes_gate[0]
            ma50_gate    = sum(closes_gate[:50]) / 50

            # Block 1: Aktie unter MA50 UND 3M-Downtrend > 10%
            if current_gate < ma50_gate and len(closes_gate) >= 63:
                trend_3m = (closes_gate[0] - closes_gate[62]) / closes_gate[62]
                if trend_3m < -0.10:
                    return {
                        'success': False,
                        'trade_id': None,
                        'message': (
                            f'❌ Deep Dive Gate: Falling Knife — {ticker} unter MA50 '
                            f'({current_gate:.2f} < {ma50_gate:.2f}) '
                            f'UND 3M-Trend {trend_3m*100:.1f}%. '
                            f'Führe zuerst "Deep Dive {ticker}" durch.'
                        ),
                        'blocked_by': 'deepdive_gate_downtrend',
                    }

            # Block 2: Aktie >40% unter 52W-Hoch ohne dokumentierten Erholungs-Katalysator
            high_52w_gate = max(closes_gate[:min(252, len(closes_gate))])
            dist_52w = (current_gate - high_52w_gate) / high_52w_gate
            if dist_52w < -0.40:
                # Prüfe ob Strategie einen frischen Katalysator hat (≤30 Tage)
                has_catalyst = False
                try:
                    _strats = json.loads(
                        (WORKSPACE / 'data' / 'strategies.json').read_text(encoding='utf-8')
                    )
                    if strategy in _strats:
                        import re as _re
                        last_upd = _strats[strategy].get('genesis', {}).get('created', '') or \
                                   _strats[strategy].get('created_at', '')
                        if last_upd:
                            from datetime import timedelta
                            upd_date = datetime.fromisoformat(str(last_upd)[:10])
                            has_catalyst = (datetime.now() - upd_date).days <= 30
                except Exception:
                    has_catalyst = True  # Kein Block wenn Daten fehlen
                if not has_catalyst:
                    return {
                        'success': False,
                        'trade_id': None,
                        'message': (
                            f'❌ Deep Dive Gate: {ticker} ist {abs(dist_52w)*100:.0f}% '
                            f'unter 52W-Hoch ohne frischen Katalysator (≤30 Tage). '
                            f'Strategie {strategy}: Thesis veraltet? '
                            f'Führe "Deep Dive {ticker}" durch und aktualisiere die Thesis.'
                        ),
                        'blocked_by': 'deepdive_gate_no_catalyst',
                    }
    except Exception:
        pass  # Gate ist defensiv — bei Fehler lieber einlassen als blocken

    # ── Guard 0e: Earnings Blackout (3 Tage vor Earnings kein Entry) ─────
    # Warum: Earnings = binäres Event, Thesis kann perfekt sein und trotzdem
    # -20% Gap-Down nach schlechten Zahlen. Besser: nach Earnings einsteigen.
    # Ausnahmen: manual/paper_lab source (Victor will bewusst pre-earnings traden)
    if source not in ('manual', 'paper_lab', 'victor', 'cli'):
        try:
            _events_file = WORKSPACE / 'data' / 'upcoming_events.json'
            if _events_file.exists():
                _events = json.loads(_events_file.read_text(encoding='utf-8'))
                _all_events = _events.get('events', [])
                _ticker_clean = ticker.upper().replace('.DE', '').replace('.OL', '').replace('.PA', '').replace('.L', '').replace('.AS', '').replace('.CO', '')

                from datetime import timedelta as _td
                _today = datetime.now(timezone.utc).date()

                for _ev in _all_events:
                    if _ev.get('type') != 'earnings':
                        continue
                    _ev_ticker = (_ev.get('ticker', '') or '').upper()
                    if _ev_ticker != _ticker_clean and _ev_ticker not in ticker.upper():
                        continue
                    # Earnings gefunden — prüfe ob innerhalb 3 Tagen
                    try:
                        _ev_date = datetime.fromisoformat(_ev.get('date', '2000-01-01')).date()
                        _days_until = (_ev_date - _today).days
                        if 0 <= _days_until <= 3:
                            return {
                                'success': False,
                                'trade_id': None,
                                'message': (
                                    f'❌ Earnings Blackout: {ticker} berichtet am {_ev.get("date")} '
                                    f'({_days_until} Tage). Kein Entry 3 Tage vor Earnings — '
                                    f'binäres Risiko. Nach Earnings neu bewerten.'
                                ),
                                'blocked_by': 'earnings_blackout',
                            }
                    except Exception:
                        pass
        except Exception:
            pass  # Earnings-Check nicht kritisch — bei Fehler weiter

    # ── Guard 1: Thesis + Conviction Check ──────────────────────────────
    # Phase 2: VIX is no longer a hard block — only a conviction modifier.
    # Hard blocks are: thesis INVALIDATED or CRV < 2.0
    vix = refresh_vix_in_db()

    try:
        from conviction_scorer import check_entry_allowed, calculate_conviction, get_position_size, ENTRY_THRESHOLD
        allowed, reason = check_entry_allowed(strategy)
        if not allowed:
            return {
                'success': False,
                'trade_id': None,
                'message': f'❌ Entry blocked: {reason}',
                'blocked_by': 'thesis_invalidated',
            }
    except Exception as e:
        reason = f'Entry check unavailable: {e}'

    # ── Guard 2: Conviction Score ────────────────────────────────────
    try:
        conviction = calculate_conviction(ticker, strategy, entry_price, stop_price, target_price)
        conv_score = conviction['score']

        # Hard block from conviction scorer (thesis invalidated or CRV too low)
        if not conviction.get('entry_allowed', True):
            return {
                'success': False,
                'trade_id': None,
                'message': f'❌ Conviction block: {conviction.get("block_reason", "score too low")}',
                'blocked_by': 'conviction',
                'conviction_score': conv_score,
            }

        if conv_score < ENTRY_THRESHOLD:
            return {
                'success': False,
                'trade_id': None,
                'message': f'❌ Conviction zu niedrig: {conv_score:.0f} < {ENTRY_THRESHOLD} (ENTRY_THRESHOLD)',
                'blocked_by': 'conviction',
                'conviction_score': conv_score,
            }
    except Exception as e:
        return {
            'success': False,
            'trade_id': None,
            'message': f'❌ Conviction Score nicht berechenbar: {e}',
            'blocked_by': 'conviction_error',
        }
    
    conn = get_db()
    
    # ── Guard 2b: Wöchentliches Trade-Limit ─────────────────────────
    # Regel: max 2-3 neue Positionen pro Woche (aus paper-strategien.md)
    # Mehr Trades = schlechtere Qualität, Overtrading, emotionale Entscheidungen.
    MAX_TRADES_PER_WEEK = 3
    try:
        from datetime import timedelta
        # ISO-Woche: Montag 00:00 bis Sonntag 23:59
        today = datetime.now(timezone.utc)
        days_since_monday = today.weekday()  # 0=Mo, 6=So
        monday = today - timedelta(days=days_since_monday)
        monday_str = monday.strftime('%Y-%m-%d')
        weekly_count = conn.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE entry_date >= ? AND status != 'CANCELLED'",
            (monday_str,)
        ).fetchone()[0]
        if weekly_count >= MAX_TRADES_PER_WEEK:
            conn.close()
            return {
                'success': False,
                'trade_id': None,
                'message': (
                    f'❌ Wöchentliches Trade-Limit erreicht: {weekly_count}/{MAX_TRADES_PER_WEEK} '
                    f'Trades diese Woche (seit {monday_str}). '
                    f'Mehr Trades = schlechtere Qualität. Warte auf nächste Woche oder erhöhe Qualität der Setups.'
                ),
                'blocked_by': 'weekly_trade_limit',
            }
    except Exception:
        pass  # Limit nicht kritisch — bei Fehler weiter

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

    # ── Guard 5b: Style-spezifische Checks ──────────────────────────
    if style_cfg:
        # VIX-Limit für Day Trades enger
        if vix and vix > style_cfg.max_vix:
            conn.close()
            return {
                'success': False,
                'trade_id': None,
                'message': f'❌ {style.upper()}: VIX {vix:.1f} > {style_cfg.max_vix} — kein {style_cfg.name}',
                'blocked_by': f'vix_{style}',
            }
        # Stop-Abstand validieren
        try:
            from trade_style import validate_stop_for_style, validate_crv_for_style
            stop_ok, stop_reason = validate_stop_for_style(entry_price, stop_price, style)
            if not stop_ok:
                conn.close()
                return {'success': False, 'trade_id': None, 'message': f'❌ {stop_reason}', 'blocked_by': 'stop_style'}
            crv_ok, crv_reason = validate_crv_for_style(entry_price, stop_price, target_price, style)
            if not crv_ok:
                conn.close()
                return {'success': False, 'trade_id': None, 'message': f'❌ {crv_reason}', 'blocked_by': 'crv_style'}
        except Exception:
            pass

    # ── Guard 6: Thesis-Exposure (max 30% Kapital pro These) ────────
    try:
        total_capital = 25000.0
        thesis_rows = conn.execute('''
            SELECT SUM(entry_price * shares) FROM paper_portfolio
            WHERE status="OPEN" AND strategy=?
        ''', (strategy,)).fetchone()
        thesis_exposure = thesis_rows[0] or 0
        if thesis_exposure / total_capital > 0.30:
            conn.close()
            return {
                'success': False,
                'trade_id': None,
                'message': f'❌ Thesis-Exposure {strategy} zu hoch: {thesis_exposure/total_capital*100:.0f}% > 30%',
                'blocked_by': 'thesis_exposure',
            }
    except Exception:
        pass

    # ═══════════════════════════════════════════════════════════════════
    # ── Guard 5p9: PHASE 9 — Portfolio Risk Management 2.0 ───────────
    # ═══════════════════════════════════════════════════════════════════
    # 5 Profi-Level Checks in einem Aufruf:
    #   - Drawdown Circuit Breaker (-5% in 7d → Pause)
    #   - Correlation / Sector Cluster (max 2 korrelierte Positionen)
    #   - Kelly Criterion Sizing (dynamisch basierend auf Strategy-WR)
    #   - VIX Volatility Scaling (VIX>25 → Size halbieren)
    #   - Sector Exposure Limit (max 30% pro Sektor)
    phase9_cap = 1500.0  # Fallback falls Risk-Modul nicht lädt
    try:
        import sys as _p9sys
        if '/opt/trademind/scripts' not in _p9sys.path:
            _p9sys.path.insert(0, '/opt/trademind/scripts')
        from portfolio_risk import run_all_risk_checks as _p9_run
        _p9 = _p9_run(ticker=ticker, strategy_id=strategy, base_size=1500.0)
        if _p9.get('blocked'):
            conn.close()
            return {
                'success': False,
                'trade_id': None,
                'message': f"❌ Phase 9 Risk-Block ({_p9.get('blocked_by')}): {_p9.get('reason')}",
                'blocked_by': f"phase9_{_p9.get('blocked_by')}",
            }
        phase9_cap = float(_p9.get('final_size') or 1500.0)
    except Exception as _p9e:
        # Graceful degradation: wenn Risk-Modul fehlt, nicht blockieren
        import logging as _p9log
        _p9log.getLogger('paper_trade_engine').warning(f'Phase 9 risk check skipped: {_p9e}')

    # ── Guard 6: Freies Cash + Position Sizing ───────────────────────
    free_cash = get_free_cash(conn)
    cfg = load_config()
    portfolio_value = cfg.get('capital', 25000)

    # Phase 2: Use get_position_size() from conviction_scorer (score-based sizing)
    try:
        from conviction_scorer import get_position_size as _gps
        shares_from_risk = _gps(conv_score, portfolio_value, entry_price, stop_price)
    except Exception:
        # Fallback: 2% risk method
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share > 0:
            shares_from_risk = int(portfolio_value * 0.02 / risk_per_share)
        else:
            shares_from_risk = 0

    # ── Phase 19b: Vol-Target Sizing (feature-flagged) ──────────────────
    # Override conviction sizing if autonomy_config.json sets
    #   "sizing_mode": "vol_target"
    try:
        import json as _json
        _cfg_path = DB_PATH.parent / 'autonomy_config.json'
        if _cfg_path.exists():
            _auto = _json.loads(_cfg_path.read_text(encoding='utf-8'))
        else:
            _auto = {}
        if _auto.get('sizing_mode') == 'vol_target':
            from execution.position_sizing import size_position as _vt_size
            _sz = _vt_size(
                ticker=ticker,
                entry_price=entry_price,
                stop_price=stop_price,
                portfolio_value_eur=portfolio_value,
                conviction_score=int(conv_score) if conv_score else None,
                fx_rate=1.0,
            )
            if not _sz.get('skip') and _sz.get('shares', 0) > 0:
                shares_from_risk = int(_sz['shares'])
                print(
                    f"[sizer] vol_target: {_sz['shares']} shares "
                    f"risk={_sz['risk_eur']}€ ({_sz['risk_pct_of_portfolio']}%) "
                    f"reason={_sz['reason']}"
                )
    except Exception as _sz_e:
        import logging as _sz_log
        _sz_log.getLogger('paper_trade_engine').warning(f'vol_target sizing skipped: {_sz_e}')

    if shares_from_risk <= 0:
        conn.close()
        return {
            'success': False,
            'trade_id': None,
            'message': f'❌ Position sizing returned 0 shares (conviction={conv_score:.0f}, entry={entry_price:.2f}, stop={stop_price:.2f})',
            'blocked_by': 'sizing_zero',
        }

    # Phase 9: Dynamic Cap aus Kelly + VIX + Sector Check (oder 1500€ Fallback)
    MAX_POSITION_EUR = phase9_cap
    position_eur = shares_from_risk * entry_price
    if position_eur > MAX_POSITION_EUR:
        shares_from_risk = int(MAX_POSITION_EUR / entry_price)
        position_eur = shares_from_risk * entry_price

    # Apply cash constraint
    if position_eur > free_cash - 100:
        # Scale down to available cash
        shares_from_risk = int((free_cash - 100) / entry_price)
        position_eur = shares_from_risk * entry_price

    if shares_from_risk <= 0 or free_cash < position_eur:
        conn.close()
        return {
            'success': False,
            'trade_id': None,
            'message': f'❌ Nicht genug Cash: {free_cash:.0f}€ verfügbar, {position_eur:.0f}€ benötigt',
            'blocked_by': 'cash',
        }

    # ── Guard 6b: Position <15% vom Fund (Trade-Vor-Checkliste Regel 8) ───────
    # Verhindert Überkonzentration in einer einzelnen Position.
    # Hard Cap 1500€ löst das meist, aber als explizite Regel auch hier prüfen.
    try:
        total_capital_est = cfg.get('capital', 25000)
        position_pct = position_eur / total_capital_est
        if position_pct > 0.15:
            # Trim auf 15% statt blocken (freundlichere Behandlung)
            max_allowed_eur = total_capital_est * 0.15
            shares_from_risk = int(max_allowed_eur / entry_price)
            position_eur = shares_from_risk * entry_price
    except Exception:
        pass

    # ── Guard 6c: Cash nach Trade muss >10% bleiben (Trade-Vor-Checkliste) ──
    # Regel 7 der Checkliste: "Cash nach Trade noch >10% vom Fund?"
    total_capital_est = cfg.get('capital', 25000)  # für unten
    # Verhindert illiquide Situationen wo wir nicht mehr auf Chancen reagieren können.
    MIN_CASH_RESERVE_PCT = 0.10
    try:
        remaining_cash_after = free_cash - position_eur
        if remaining_cash_after < total_capital_est * MIN_CASH_RESERVE_PCT:
            conn.close()
            return {
                'success': False,
                'trade_id': None,
                'message': (
                    f'❌ Cash-Reserve-Regel verletzt: nach diesem Trade nur noch '
                    f'{remaining_cash_after:.0f}€ ({remaining_cash_after/total_capital_est*100:.1f}%) übrig. '
                    f'Mindest-Reserve: 10% = {total_capital_est*MIN_CASH_RESERVE_PCT:.0f}€. '
                    f'Position verkleinern oder anderen Trade schließen.'
                ),
                'blocked_by': 'cash_reserve',
            }
    except Exception:
        pass  # Reserve-Check nicht kritisch

    shares = float(shares_from_risk)
    fees = FEE_PER_TRADE
    total_cost = shares * entry_price + fees
    
    # ── Entry ausführen ──────────────────────────────────────────────
    regime = conviction.get('regime', 'UNKNOWN')
    vix_val = conviction.get('vix', 0)
    now = datetime.now(timezone.utc).isoformat()
    
    # ── Entry Gate Check (PFLICHT) ────────────────────────────────────
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.dirname(__file__)))
        from entry_gate import EntryGate
        _gate = EntryGate(str(DB_PATH))
        _headline = conviction.get('headline', '')
        _source = conviction.get('source', '')
        _gate_result = _gate.check(ticker, strategy, _headline, _source, regime, vix_val)
        if not _gate_result['allowed']:
            conn.close()
            return {'success': False, 'trade_id': None,
                    'reason': f"Entry Gate blocked: {_gate_result['reason']}"}
    except Exception as _e:
        pass  # Gate-Fehler nicht blockierend
    # ─────────────────────────────────────────────────────────────────
    
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
        UPDATE paper_fund SET value = value - ? WHERE key = 'current_cash'
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

    # ── Feature-Vollständigkeit prüfen ──
    REQUIRED_FEATURES = ['rsi_at_entry', 'volume_ratio', 'vix_at_entry', 'ma50_distance', 'spy_5d_return']
    _missing = [f for f in REQUIRED_FEATURES if not _features.get(f)]
    if _missing:
        print(f"  ⚠️  Fehlende Features: {_missing} — ML-Training-Qualität eingeschränkt")

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
    # Advisory Layer — Warum dieser Trade?
    try:
        from conviction_scorer import calculate_conviction
        _adv = calculate_conviction(ticker, strategy, entry_price, stop_price, target_price)
        _factors = _adv.get('factors', {})
        _strongest = _adv.get('strongest', [])
        _weakest  = _adv.get('weakest', [])
        _adv_str  = ""
        if _strongest:
            _adv_str += "\n💡 Stärken: " + ', '.join(f"{f['factor']} ({f['score']})" for f in _strongest)
        if _weakest and _weakest[0]['score'] < 40:
            _adv_str += f"\n⚠️ Risiko: {_weakest[0]['factor']} ({_weakest[0]['score']}) schwach"
    except Exception:
        _adv_str = ""

    msg = (
        f"📊 **PAPER TRADE ERÖFFNET** — {ticker}\n"
        f"Strategie: {strategy} | Entry: {entry_price:.2f}€\n"
        f"Stop: {stop_price:.2f}€ | Ziel: {target_price:.2f}€ | CRV: {crv}:1\n"
        f"Position: {position_eur:.0f}€ ({shares:.2f} Shares) | Conviction: {conv_score:.0f}/100{_prob_str}{_dna_str}\n"
        f"Regime: {regime} | VIX: {f'{vix_val:.1f}' if vix_val else 'n/a'}{_warn_str}"
        f"{_adv_str}\n"
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


# ─── Trade Close mit PnL-Berechnung ─────────────────────────────────

def close_trade(trade_id: int, exit_price: float, exit_reason: str = 'manual') -> dict:
    """
    Schliesst einen offenen Paper Trade und berechnet PnL.

    Berechnet:
      pnl_eur  = (exit_price - entry_price) * shares - 2 * FEE_PER_TRADE
      pnl_pct  = pnl_eur / (entry_price * shares)
      status   = WIN (pnl_eur > 10) | LOSS (pnl_eur < -10) | CLOSED (break-even)

    Returns dict mit success, pnl_eur, pnl_pct, status.
    """
    conn = get_db()
    try:
        trade = conn.execute(
            "SELECT * FROM paper_portfolio WHERE id=? AND status='OPEN'",
            (trade_id,)
        ).fetchone()
        if not trade:
            return {'success': False, 'message': f'Trade {trade_id} nicht gefunden oder bereits geschlossen'}

        entry_price = trade['entry_price']
        shares      = trade['shares']
        strategy    = trade['strategy'] or 'UNKNOWN'
        ticker      = trade['ticker']

        if not entry_price or not shares or shares <= 0:
            return {'success': False, 'message': 'Ungueltige Trade-Daten (entry_price oder shares fehlt)'}

        entry_cost = entry_price * shares
        exit_value = exit_price * shares
        fees = FEE_PER_TRADE * 2  # entry + exit
        pnl_eur = exit_value - entry_cost - fees
        pnl_pct = (pnl_eur / entry_cost * 100) if entry_cost > 0 else 0.0

        if pnl_eur > 10:
            new_status = 'WIN'
        elif pnl_eur < -10:
            new_status = 'LOSS'
        else:
            new_status = 'CLOSED'

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE paper_portfolio
            SET status=?, exit_price=?, close_date=?, pnl_eur=?, pnl_pct=?, exit_type=?
            WHERE id=?
            """,
            (new_status, exit_price, now, round(pnl_eur, 2), round(pnl_pct, 2), exit_reason, trade_id)
        )
        conn.commit()

        # Cash zurueck in paper_fund
        try:
            conn.execute(
                "UPDATE paper_fund SET value = value + ? WHERE key='current_cash'",
                (exit_value - FEE_PER_TRADE,)
            )
            conn.commit()
        except Exception:
            pass  # paper_fund optional

        icon = 'WIN' if new_status == 'WIN' else ('LOSS' if new_status == 'LOSS' else 'CLOSED')
        msg = (
            f"[{icon}] {ticker} | {strategy} | "
            f"Entry {entry_price:.2f} -> Exit {exit_price:.2f} | "
            f"PnL: {pnl_eur:+.2f} EUR ({pnl_pct:+.1f}%) | Grund: {exit_reason}"
        )
        queue_alert(msg)

        return {
            'success':    True,
            'trade_id':   trade_id,
            'ticker':     ticker,
            'strategy':   strategy,
            'pnl_eur':    round(pnl_eur, 2),
            'pnl_pct':    round(pnl_pct, 2),
            'status':     new_status,
            'exit_price': exit_price,
            'message':    msg,
        }
    except Exception as e:
        return {'success': False, 'message': f'close_trade Fehler: {e}'}
    finally:
        conn.close()


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
    
    elif cmd == 'close' and len(sys.argv) >= 4:
        trade_id   = int(sys.argv[2])
        exit_price = float(sys.argv[3])
        reason     = sys.argv[4] if len(sys.argv) > 4 else 'manual'
        result = close_trade(trade_id, exit_price, reason)
        if result['success']:
            print(f"[{result['status']}] Trade #{trade_id} geschlossen: {result['pnl_eur']:+.2f} EUR ({result['pnl_pct']:+.1f}%)")
        else:
            print(f"Fehler: {result['message']}")

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
