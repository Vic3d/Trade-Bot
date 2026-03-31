#!/usr/bin/env python3
"""
TradeMind CEO — Das zentrale Gehirn des Systems
================================================
Liest alle Datenquellen, berechnet den System-Zustand,
schreibt den täglichen Marschbefehl (ceo_directive.json)
und generiert einen Bericht für Victor.

Verwendung:
  python3 scripts/ceo.py          # Direktive schreiben + Report ausgeben
  python3 scripts/ceo.py --health # Nur System-Health-Check
  python3 scripts/ceo.py --report # Nur Report, keine Direktive

Autor: Albert 🎩 | 31.03.2026
"""

import sqlite3
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

WS = Path('/data/.openclaw/workspace')


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

def safe_read_json(path: Path, default=None):
    """JSON-Datei lesen — gibt default zurück wenn Datei fehlt oder kaputt ist."""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default if default is not None else {}


def safe_read_text(path: Path, default: str = '') -> str:
    """Textdatei lesen — gibt default zurück wenn Datei fehlt."""
    try:
        if path.exists():
            return path.read_text()
    except Exception:
        pass
    return default


def get_db():
    """SQLite-Verbindung öffnen."""
    db_path = WS / 'data/trading.db'
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


# ─── CEO Direktive laden ─────────────────────────────────────────────────────

def load_ceo_directive() -> dict | None:
    """
    Lädt die aktuelle CEO-Direktive.
    Returns None wenn nicht vorhanden oder älter als 24h.
    """
    path = WS / 'data/ceo_directive.json'
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text())
        ts = datetime.fromisoformat(d['timestamp'])
        if (datetime.now() - ts).total_seconds() < 86400:
            return d
    except Exception:
        pass
    return None


# ─── Datenquellen laden ───────────────────────────────────────────────────────

def load_all_sources() -> dict:
    """Alle externen Datenquellen einlesen."""
    return {
        'strategies': safe_read_json(WS / 'data/strategies.json'),
        'regime': safe_read_json(WS / 'memory/market-regime.json'),
        'dna': safe_read_json(WS / 'data/dna.json'),
        'benchmark': safe_read_json(WS / 'data/benchmark.json'),
        'paper_config': safe_read_json(WS / 'data/paper_config.json'),
        'signals': safe_read_json(WS / 'data/signals.json', default=[]),
        'accuracy': safe_read_text(WS / 'memory/albert-accuracy.md'),
        'strategien': safe_read_text(WS / 'memory/strategien.md'),
        'state_snapshot': safe_read_text(WS / 'memory/state-snapshot.md'),
        'strategy_changelog': safe_read_text(WS / 'memory/strategy-changelog.md'),
    }


# ─── Historische Performance aus DB ─────────────────────────────────────────

def load_historical_data(conn) -> dict:
    """
    Berechnet alle relevanten Metriken aus der trading.db.
    Robust: kein Crash bei fehlenden Spalten oder leerer DB.
    """
    result = {
        'total_closed_trades': 0,
        'overall_win_rate': 0.0,
        'avg_pnl_per_trade': 0.0,
        'best_strategy': 'N/A',
        'worst_strategy': 'N/A',
        'open_positions': 0,
        'portfolio_drawdown': 0.0,
        'paper_benchmark_gap': 0.0,
        'recent_win_rate_7d': 0.5,
        'recent_win_rate_30d': 0.5,
        'strategy_performance': {},
        'consecutive_loss_days': 0,
        'total_realized_pnl': 0.0,
        'starting_capital': 25000.0,
        'current_cash': 0.0,
    }

    if conn is None:
        return result

    try:
        # Gesamtperformance (geschlossene Trades)
        row = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END), AVG(pnl_eur) "
            "FROM paper_portfolio WHERE status != 'OPEN' AND pnl_eur IS NOT NULL"
        ).fetchone()
        if row and row[0]:
            total = int(row[0])
            wins = int(row[1]) if row[1] else 0
            result['total_closed_trades'] = total
            result['overall_win_rate'] = wins / total if total > 0 else 0.0
            result['avg_pnl_per_trade'] = float(row[2]) if row[2] else 0.0
    except Exception:
        pass

    try:
        # Strategie-Performance
        rows = conn.execute(
            "SELECT strategy, COUNT(*), "
            "SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END), AVG(pnl_eur) "
            "FROM paper_portfolio WHERE status != 'OPEN' AND strategy IS NOT NULL "
            "GROUP BY strategy"
        ).fetchall()
        strat_perf = {}
        for r in rows:
            strat = r[0]
            n = int(r[1])
            wins = int(r[2]) if r[2] else 0
            avg_pnl = float(r[3]) if r[3] else 0.0
            wr = wins / n if n > 0 else 0.0
            strat_perf[strat] = {'trades': n, 'wins': wins, 'win_rate': wr, 'avg_pnl': avg_pnl}

        result['strategy_performance'] = strat_perf

        # Beste und schlechteste Strategie (min 2 Trades)
        eligible = {k: v for k, v in strat_perf.items() if v['trades'] >= 2}
        if eligible:
            best = max(eligible.items(), key=lambda x: x[1]['win_rate'])
            worst = min(eligible.items(), key=lambda x: x[1]['win_rate'])
            result['best_strategy'] = best[0]
            result['worst_strategy'] = worst[0]
    except Exception:
        pass

    try:
        # Offene Positionen
        count = conn.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE status = 'OPEN'"
        ).fetchone()
        result['open_positions'] = int(count[0]) if count else 0
    except Exception:
        pass

    try:
        # Win-Rate letzte 7 und 30 Tage
        cutoff_7d = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        cutoff_30d = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

        for days, cutoff, key in [(7, cutoff_7d, 'recent_win_rate_7d'),
                                    (30, cutoff_30d, 'recent_win_rate_30d')]:
            row = conn.execute(
                f"SELECT COUNT(*), SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) "
                f"FROM paper_portfolio WHERE status != 'OPEN' AND close_date >= '{cutoff}'"
            ).fetchone()
            if row and row[0] and int(row[0]) > 0:
                result[key] = int(row[1] or 0) / int(row[0])
    except Exception:
        pass

    try:
        # Paper-Fund Daten
        fund_rows = conn.execute("SELECT key, value FROM paper_fund").fetchall()
        fund = {r[0]: r[1] for r in fund_rows}
        starting = float(fund.get('starting_capital', 25000))
        cash = float(fund.get('current_cash', 0))
        realized_pnl = float(fund.get('total_realized_pnl', 0))
        result['starting_capital'] = starting
        result['current_cash'] = cash
        result['total_realized_pnl'] = realized_pnl

        # Investiertes Kapital in offenen Positionen
        invested_row = conn.execute(
            "SELECT SUM(entry_price * shares) FROM paper_portfolio WHERE status = 'OPEN'"
        ).fetchone()
        invested = float(invested_row[0]) if invested_row and invested_row[0] else 0.0

        # Portfolio-Gesamtwert (Cash + Invested zu Entry-Preisen als Proxy)
        # Korrekte Annäherung: Cash + Invested = gesamtes eingesetztes Kapital
        total_value = cash + invested

        # Drawdown = wie weit sind wir vom Höchststand entfernt?
        # Aus paper_performance holen falls verfügbar
        try:
            pp_row = conn.execute(
                "SELECT max_drawdown, total_value FROM paper_performance ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if pp_row:
                max_dd = pp_row[0]
                if max_dd is not None:
                    result['portfolio_drawdown'] = abs(float(max_dd))
                else:
                    # Fallback: Aktueller Wert vs. Starting Capital
                    pnl_ratio = (total_value - starting) / starting if starting > 0 else 0
                    result['portfolio_drawdown'] = max(0.0, -pnl_ratio)
            else:
                pnl_ratio = (total_value - starting) / starting if starting > 0 else 0
                result['portfolio_drawdown'] = max(0.0, -pnl_ratio)
        except Exception:
            # Letzter Fallback: Nur realisierter P&L
            pnl_ratio = realized_pnl / starting if starting > 0 else 0
            result['portfolio_drawdown'] = max(0.0, -pnl_ratio)

    except Exception:
        pass

    try:
        # Aufeinanderfolgende Verlust-Tage berechnen
        rows = conn.execute(
            "SELECT DATE(close_date) as day, "
            "SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) as wins, "
            "COUNT(*) as total "
            "FROM paper_portfolio WHERE status != 'OPEN' AND close_date IS NOT NULL "
            "GROUP BY day ORDER BY day DESC LIMIT 14"
        ).fetchall()
        consecutive_losses = 0
        for r in rows:
            day_wins = int(r[1] or 0)
            day_total = int(r[2] or 0)
            if day_total > 0 and day_wins == 0:
                consecutive_losses += 1
            else:
                break
        result['consecutive_loss_days'] = consecutive_losses
    except Exception:
        pass

    try:
        # Benchmark-Gap (Albert vs. SPY)
        bench = safe_read_json(WS / 'data/benchmark.json')
        if bench and 'benchmarks' in bench:
            spy_perf = bench['benchmarks'].get('SPY', {}).get('performance_pct', 0)
            paper_perf = bench.get('paper_fund', {}).get('performance_pct', 0)
            result['paper_benchmark_gap'] = paper_perf - spy_perf
    except Exception:
        pass

    return result


# ─── Trading-Mode Entscheidung ────────────────────────────────────────────────

def determine_trading_mode(vix: float, geo_score: float, win_rate_7d: float,
                            drawdown: float, consecutive_loss_days: int) -> tuple[str, str]:
    """
    Bestimmt den Trading-Modus basierend auf Marktbedingungen.

    Returns: (mode, reason)
    mode: AGGRESSIVE | NORMAL | DEFENSIVE | SHUTDOWN
    """
    reasons = []

    # SHUTDOWN: VIX > 40 ODER Drawdown > 20% ODER 3+ Verlust-Tage in Folge
    if vix > 40:
        reasons.append(f'VIX {vix:.1f} > 40')
    if drawdown > 0.20:
        reasons.append(f'Drawdown {drawdown:.1%} > 20%')
    if consecutive_loss_days >= 3:
        reasons.append(f'{consecutive_loss_days} Verlust-Tage in Folge')
    if reasons:
        return 'SHUTDOWN', ' + '.join(reasons)

    # DEFENSIVE: VIX > 28 ODER Geopolitik HIGH ODER Win-Rate < 25% letzte 7d
    def_reasons = []
    if vix > 28:
        def_reasons.append(f'VIX {vix:.1f} > 28')
    if geo_score > 50:
        def_reasons.append(f'Geo-Score {geo_score:.0f} > 50')
    if win_rate_7d < 0.25:
        def_reasons.append(f'WR 7d {win_rate_7d:.0%} < 25%')
    if def_reasons:
        return 'DEFENSIVE', ' + '.join(def_reasons)

    # AGGRESSIVE: VIX < 20 UND Win-Rate > 50% letzte 7d
    if vix < 20 and win_rate_7d > 0.50:
        return 'AGGRESSIVE', 'Niedrige Volatilität, starke Performance'

    # NORMAL: alles andere
    return 'NORMAL', 'Standardbetrieb'


# ─── Trading-Rules je Modus ───────────────────────────────────────────────────

def build_trading_rules(mode: str, vix: float, strat_perf: dict, strategies: dict) -> dict:
    """Baut die konkreten Handelsregeln basierend auf Modus und Performance."""

    # Basis-Regeln nach Modus
    mode_configs = {
        'SHUTDOWN': {
            'max_new_positions_today': 0,
            'max_position_size_eur': 0,
            'stop_tightening_factor': 1.5,
            'vix_conviction_adjustment': -3,
        },
        'DEFENSIVE': {
            'max_new_positions_today': 2,
            'max_position_size_eur': 1500,
            'stop_tightening_factor': 1.3,
            'vix_conviction_adjustment': -2,
        },
        'NORMAL': {
            'max_new_positions_today': 4,
            'max_position_size_eur': 2000,
            'stop_tightening_factor': 1.0,
            'vix_conviction_adjustment': 0,
        },
        'AGGRESSIVE': {
            'max_new_positions_today': 6,
            'max_position_size_eur': 2500,
            'stop_tightening_factor': 0.9,
            'vix_conviction_adjustment': +1,
        },
    }

    rules = mode_configs.get(mode, mode_configs['NORMAL']).copy()

    # Strategien nach Performance klassifizieren
    # Locked/gesperrte Strategien
    blocked = []
    allowed = []

    # Sektoren die bei DEFENSIVE/SHUTDOWN geblockt werden
    risky_sectors = {'technology', 'day_trade'}
    safe_sectors = {'energy', 'metals', 'fertilizer', 'materials'}

    for strat_id, strat_data in strategies.items():
        if strat_id.startswith('_') or strat_id == 'emerging_themes':
            continue

        # Explizit gesperrt?
        if strat_data.get('locked', False):
            blocked.append(strat_id)
            continue

        # Typ = day_trade? Im Defensive/SHUTDOWN immer blockieren
        strat_type = strat_data.get('type', '')
        if strat_type == 'day_trade' and mode in ('DEFENSIVE', 'SHUTDOWN'):
            blocked.append(strat_id)
            continue

        # Sektor prüfen
        sector = strat_data.get('sector', '')
        health = strat_data.get('health', 'yellow')

        if mode == 'SHUTDOWN':
            blocked.append(strat_id)
        elif mode == 'DEFENSIVE':
            if sector in risky_sectors or health == 'red':
                blocked.append(strat_id)
            else:
                allowed.append(strat_id)
        else:
            if health != 'red':
                allowed.append(strat_id)
            else:
                blocked.append(strat_id)

    # Performance-basiertes Blockieren (0 Wins nach 3+ Trades)
    for strat_id, perf in strat_perf.items():
        if perf['trades'] >= 3 and perf['win_rate'] == 0.0:
            if strat_id not in blocked:
                blocked.append(strat_id)
            if strat_id in allowed:
                allowed.remove(strat_id)

    rules['allowed_strategies'] = sorted(set(allowed))
    rules['blocked_strategies'] = sorted(set(blocked))

    return rules


# ─── System-Health berechnen ──────────────────────────────────────────────────

def calculate_system_health(hist: dict, sources: dict) -> dict:
    """
    Berechnet den System-Health-Score (0–100).
    100 = alles perfekt, 0 = System komplett kaputt.
    """
    score = 100
    errors = []
    warnings = []

    # Trade Journal Qualität
    journal_entries = 0
    db = get_db()
    if db:
        try:
            row = db.execute("SELECT COUNT(*) FROM trade_journal").fetchone()
            journal_entries = int(row[0]) if row else 0
            db.close()
        except Exception:
            pass

    if journal_entries < 5:
        score -= 15
        warnings.append(f'P1.3 Trade Journal: nur {journal_entries} Einträge — mehr Daten nötig')
    elif journal_entries < 20:
        score -= 5
        warnings.append(f'Trade Journal: {journal_entries} Einträge (Ziel: 30+ für statistische Signifikanz)')

    # Datenbasis zu klein
    if hist['total_closed_trades'] < 20:
        score -= 10
        warnings.append(f'Nur {hist["total_closed_trades"]} geschlossene Trades — zu wenig für valide Aussagen')

    # Win-Rate sehr niedrig
    if hist['overall_win_rate'] < 0.30:
        score -= 20
        warnings.append(f'Win-Rate {hist["overall_win_rate"]:.0%} — unter 30% (Ziel: >45%)')
    elif hist['overall_win_rate'] < 0.40:
        score -= 10
        warnings.append(f'Win-Rate {hist["overall_win_rate"]:.0%} — verbesserungswürdig')

    # Drawdown
    if hist['portfolio_drawdown'] > 0.15:
        score -= 25
        errors.append(f'Drawdown {hist["portfolio_drawdown"]:.1%} — kritisch! Limit 20%')
    elif hist['portfolio_drawdown'] > 0.10:
        score -= 15
        warnings.append(f'Drawdown {hist["portfolio_drawdown"]:.1%} — erhöht')

    # Aufeinanderfolgende Verlust-Tage
    if hist['consecutive_loss_days'] >= 3:
        score -= 20
        errors.append(f'{hist["consecutive_loss_days"]} aufeinanderfolgende Verlust-Tage — SHUTDOWN-Trigger!')
    elif hist['consecutive_loss_days'] == 2:
        score -= 10
        warnings.append(f'{hist["consecutive_loss_days"]} Verlust-Tage in Folge — beobachten')

    # Datenquellen verfügbar?
    if not sources.get('regime'):
        score -= 5
        warnings.append('market-regime.json nicht verfügbar')

    if not sources.get('strategies'):
        score -= 10
        errors.append('strategies.json nicht verfügbar!')

    # P1.x Features Status
    p1_features = []
    lernplan = sources.get('accuracy', '') + sources.get('state_snapshot', '')
    if 'P1.1' in lernplan or 'dedup' in lernplan.lower():
        p1_features.append('P1.1')
    if 'P1.2' in lernplan or 'VIX' in lernplan:
        p1_features.append('P1.2')
    if 'P1.3' in lernplan or 'trade_journal' in lernplan.lower():
        p1_features.append('P1.3')
    if 'P1.4' in lernplan or 'magnitude' in lernplan.lower():
        p1_features.append('P1.4')

    score = max(0, min(100, score))

    return {
        'score': score,
        'errors': errors,
        'warnings': warnings,
        'journal_entries': journal_entries,
        'p1_features_active': len(p1_features) >= 3,
        'p1_features_list': p1_features,
    }


# ─── Geopolitik-Score ────────────────────────────────────────────────────────

def estimate_geo_score(regime: dict, strategies: dict) -> float:
    """
    Schätzt Geopolitik-Risiko-Score (0–100).
    Basiert auf aktiven Strategien + Regime.
    """
    score = 0

    # Regime-basiert
    regime_type = regime.get('regime', 'NORMAL')
    if 'DOWN' in regime_type or 'CRASH' in regime_type:
        score += 30
    elif 'RANGE' in regime_type:
        score += 15

    # Aktive geo-politische Strategien
    geo_strategies = ['S1', 'S9', 'PS1', 'PS2']
    for s in geo_strategies:
        if s in strategies and strategies[s].get('status') == 'active':
            score += 10

    # Iran-Konflikt aktiv?
    s1 = strategies.get('S1', {})
    if s1.get('health') in ('green_hot', 'green'):
        score += 20

    return min(100, score)


# ─── Top Opportunities identifizieren ────────────────────────────────────────

def find_top_opportunities(mode: str, strategies: dict, strat_perf: dict) -> list:
    """Findet die 3 besten Opportunitäten basierend auf Modus und Performance."""
    if mode in ('SHUTDOWN',):
        return []

    opps = []

    for strat_id, strat in strategies.items():
        if strat_id.startswith('_') or strat_id == 'emerging_themes':
            continue
        if strat.get('locked', False):
            continue
        if strat.get('status') not in ('active', 'watchlist', 'watching'):
            continue

        health = strat.get('health', 'red')
        if health not in ('green', 'green_hot', 'yellow'):
            continue

        perf = strat_perf.get(strat_id, {})
        wr = perf.get('win_rate', 0)
        n = perf.get('trades', 0)

        # Score: Health + Win-Rate + Conviction
        opp_score = 0
        if health == 'green_hot':
            opp_score += 40
        elif health == 'green':
            opp_score += 30
        elif health == 'yellow':
            opp_score += 10

        if n >= 2:
            opp_score += int(wr * 30)

        # DEFENSIVE: nur sichere Sektoren
        if mode == 'DEFENSIVE' and strat.get('sector') in ('technology',):
            continue

        name = strat.get('name', strat_id)
        tickers = strat.get('tickers', [])
        opps.append({
            'strategy': strat_id,
            'name': name,
            'tickers': tickers[:3],
            'health': health,
            'score': opp_score,
            'win_rate': wr,
            'trades': n,
        })

    opps.sort(key=lambda x: x['score'], reverse=True)
    return opps[:3]


# ─── CEO-Direktive zusammenbauen ─────────────────────────────────────────────

def build_directive(sources: dict, hist: dict, health: dict) -> dict:
    """Baut die vollständige CEO-Direktive."""

    regime = sources.get('regime', {})
    strategies = sources.get('strategies', {})

    # VIX aus Regime lesen
    vix = regime.get('indicators', {}).get('vix', 25.0)
    regime_type = regime.get('regime', 'TREND_DOWN')

    # Geopolitik-Score
    geo_score = estimate_geo_score(regime, strategies)

    # Trading-Mode bestimmen
    mode, mode_reason = determine_trading_mode(
        vix=vix,
        geo_score=geo_score,
        win_rate_7d=hist['recent_win_rate_7d'],
        drawdown=hist['portfolio_drawdown'],
        consecutive_loss_days=hist['consecutive_loss_days'],
    )

    # Trading-Rules
    rules = build_trading_rules(mode, vix, hist['strategy_performance'], strategies)

    # Top-Opportunitäten
    top_opps = find_top_opportunities(mode, strategies, hist['strategy_performance'])

    # CEO-Notizen generieren
    ceo_notes = _generate_ceo_notes(mode, vix, hist, regime_type)

    # Direktive zusammenbauen
    directive = {
        'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'mode': mode,
        'mode_reason': mode_reason,
        'vix': round(vix, 1),
        'regime': regime_type,
        'geo_alert_level': 'HIGH' if geo_score > 60 else 'MEDIUM' if geo_score > 30 else 'LOW',
        'geo_score': round(geo_score, 0),

        # REAL TRADING — bleibt konservativ (CEO-Regeln gelten)
        'trading_rules': rules,

        # PAPER LAB — volle Freiheit, Experimental Mode
        'paper_lab': {
            'mode': 'EXPERIMENTAL',
            'description': 'Paper Lab testet alles — auch schwache Setups und hohes Risiko',
            'max_new_positions_per_run': 15,
            'min_conviction_score': 1,        # Auch Score 1-2 wird getestet (statt 4+)
            'ignore_vix_limit': True,          # Tradet auch bei VIX 40+
            'ignore_regime': True,             # Tradet auch in CRASH
            'blocked_strategies': [],          # Nichts geblockt
            'max_position_size_eur': 3000,     # Höhere Einzelpositionsgröße
            'stop_factor': 1.0,                # Normaler Stop (nicht enger)
            'risk_mode': 'HIGH',               # Explizit: hohes Risiko erlaubt
            'experimental_strategies': True,   # Auch Strategien mit health='testing'
        },

        'system_health': {
            'score': health['score'],
            'errors': health['errors'],
            'warnings': health['warnings'],
        },

        'learning_status': {
            'overall_win_rate': round(hist['overall_win_rate'], 3),
            'win_rate_7d': round(hist['recent_win_rate_7d'], 3),
            'win_rate_30d': round(hist['recent_win_rate_30d'], 3),
            'best_strategy': hist['best_strategy'],
            'worst_strategy': hist['worst_strategy'],
            'total_closed_trades': hist['total_closed_trades'],
            'open_positions': hist['open_positions'],
            'portfolio_drawdown': round(hist['portfolio_drawdown'], 3),
            'p1_features_active': health['p1_features_active'],
            'data_quality_score': _calc_data_quality(hist, health),
        },

        'top_opportunities': top_opps,

        'ceo_notes': ceo_notes,
    }

    return directive


def _generate_ceo_notes(mode: str, vix: float, hist: dict, regime: str) -> str:
    """Generiert situative CEO-Notizen."""
    notes = []

    if mode == 'SHUTDOWN':
        notes.append('System im SHUTDOWN-Modus. Keine neuen Positionen öffnen.')
    elif mode == 'DEFENSIVE':
        notes.append(f'VIX {vix:.1f} — erhöhte Volatilität. Stops erweitern.')
        if vix > 28:
            notes.append('Tech-Positionen (NVDA, PLTR, MSFT) nur halten, nicht ausbauen.')
    elif mode == 'AGGRESSIVE':
        notes.append('Niedrige Volatilität + starke Performance — Chance nutzen.')

    if hist['consecutive_loss_days'] >= 2:
        notes.append(f'⚠️ {hist["consecutive_loss_days"]} Verlust-Tage in Folge — Position Sizing reduzieren.')

    if hist['total_closed_trades'] < 30:
        notes.append(f'Datenbasis noch klein ({hist["total_closed_trades"]} Trades) — keine statistischen Garantien.')

    if 'TREND_DOWN' in regime or 'CRASH' in regime:
        notes.append('Abwärtstrend aktiv — S&P unter MA200 = kein Growth-Long.')

    return ' | '.join(notes) if notes else 'Standardbetrieb.'


def _calc_data_quality(hist: dict, health: dict) -> int:
    """Berechnet einen Data-Quality-Score (0–100)."""
    score = 100
    if hist['total_closed_trades'] < 10: score -= 30
    elif hist['total_closed_trades'] < 30: score -= 15
    if health['journal_entries'] < 5: score -= 20
    elif health['journal_entries'] < 20: score -= 10
    if not health['p1_features_active']: score -= 15
    return max(0, min(100, score))


# ─── Discord-Report generieren ────────────────────────────────────────────────

def generate_report(directive: dict, hist: dict) -> str:
    """Generiert den Discord-Tagesbriefing-Text für Victor."""

    mode = directive['mode']
    vix = directive['vix']
    regime = directive['regime']
    health_score = directive['system_health']['score']

    # Mode-Label mit Emoji
    mode_labels = {
        'AGGRESSIVE': '🚀 AGGRESSIV',
        'NORMAL': '🟢 NORMAL',
        'DEFENSIVE': '🛡️ DEFENSIV',
        'SHUTDOWN': '🔴 SHUTDOWN',
    }
    mode_label = mode_labels.get(mode, mode)

    # Performance-Zahlen
    wr_overall = directive['learning_status']['overall_win_rate']
    wr_7d = directive['learning_status']['win_rate_7d']
    drawdown = directive['learning_status']['portfolio_drawdown']
    best_strat = directive['learning_status']['best_strategy']
    worst_strat = directive['learning_status']['worst_strategy']
    total_trades = directive['learning_status']['total_closed_trades']
    open_pos = directive['learning_status']['open_positions']

    best_perf = hist['strategy_performance'].get(best_strat, {})
    worst_perf = hist['strategy_performance'].get(worst_strat, {})
    best_wr = best_perf.get('win_rate', 0)
    worst_wr = worst_perf.get('win_rate', 0)

    # Benchmark-Gap
    bench_gap = hist.get('paper_benchmark_gap', 0)
    bench_str = f'{bench_gap:+.1f}% vs SPY' if bench_gap != 0 else 'vs SPY N/A'

    # Direktive-Details
    rules = directive['trading_rules']
    max_pos = rules.get('max_new_positions_today', 0)
    max_size = rules.get('max_position_size_eur', 0)
    stop_factor = rules.get('stop_tightening_factor', 1.0)
    allowed = rules.get('allowed_strategies', [])
    blocked = rules.get('blocked_strategies', [])

    # Allowed/Blocked kurzfassen
    allowed_str = ', '.join(allowed[:5]) if allowed else 'Keine'
    blocked_str = ', '.join(blocked[:5]) if blocked else 'Keine'
    if len(blocked) > 5:
        blocked_str += f' +{len(blocked)-5} weitere'

    # Warnungen
    warnings = directive['system_health']['warnings']
    errors = directive['system_health']['errors']

    # P1-Features
    p1_active = directive['learning_status']['p1_features_active']
    p1_str = '✅' if p1_active else '⏸️'

    # Top Opportunities
    opps = directive.get('top_opportunities', [])
    opp_lines = []
    for opp in opps:
        tickers_str = ', '.join(opp['tickers']) if opp['tickers'] else 'N/A'
        opp_lines.append(f"  • {opp['name']} ({opp['strategy']}) — {tickers_str} | WR: {opp['win_rate']:.0%}")

    # CEO-Notizen
    ceo_notes = directive.get('ceo_notes', '')

    report_lines = [
        '🎩 **TradeMind CEO — Tagesbriefing**',
        '',
        f'📊 **System-Status:** {mode_label} (VIX {vix:.1f} | Regime: {regime})',
        f'📈 **Performance:** Win-Rate {wr_overall:.0%} (7d: {wr_7d:.0%}) | {bench_str}',
        f'🏆 **Beste Strategie:** {best_strat} ({best_wr:.0%} WR) | ⚠️ Schwächste: {worst_strat} ({worst_wr:.0%} WR)',
        f'📦 **Positionen:** {open_pos} offen | {total_trades} Trades geschlossen | Drawdown: {drawdown:.1%}',
        '',
        '**Heutige Direktive:**',
        f'- Max {max_pos} neue Positionen (Größe: €{max_size:,.0f})',
        f'- Stop-Faktor ×{stop_factor:.1f}' + (' (breiter bei VIX > 28)' if vix > 28 else ''),
        f'- Erlaubt: {allowed_str[:60]}',
        f'- Geblockt: {blocked_str[:80]}',
    ]

    if opp_lines:
        report_lines.append('')
        report_lines.append('**Top Opportunities:**')
        report_lines.extend(opp_lines)

    report_lines.append('')
    report_lines.append(f'**System-Gesundheit:** {health_score}/100')

    if errors:
        for e in errors:
            report_lines.append(f'🚨 {e}')

    if warnings:
        for w in warnings[:3]:
            report_lines.append(f'⚠️ {w}')

    report_lines.extend([
        '',
        f'**Lernfortschritt:** P1.1–P1.4 {p1_str} | Trades gesamt: {total_trades} | Nächste Review: +{max(0, 30-total_trades)} Trades',
    ])

    if ceo_notes and ceo_notes != 'Standardbetrieb.':
        report_lines.extend([
            '',
            f'📝 **CEO-Notiz:** {ceo_notes}',
        ])

    return '\n'.join(report_lines)


# ─── Health-Only Report ────────────────────────────────────────────────────────

def generate_health_report(health: dict, hist: dict) -> str:
    """Kurzreport für --health Flag."""
    lines = [
        '🏥 **TradeMind System-Health**',
        f'Score: {health["score"]}/100',
        f'Trade Journal: {health["journal_entries"]} Einträge',
        f'Closed Trades: {hist["total_closed_trades"]}',
        f'Win-Rate: {hist["overall_win_rate"]:.0%}',
        f'Drawdown: {hist["portfolio_drawdown"]:.1%}',
        f'P1-Features: {", ".join(health["p1_features_list"]) or "Keine"}',
    ]
    for e in health['errors']:
        lines.append(f'🚨 ERROR: {e}')
    for w in health['warnings']:
        lines.append(f'⚠️ WARN: {w}')
    return '\n'.join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='TradeMind CEO')
    parser.add_argument('--health', action='store_true', help='Nur System-Health-Check')
    parser.add_argument('--report', action='store_true', help='Nur Report, keine Direktive schreiben')
    args = parser.parse_args()

    # ── Schritt 1: Alle Quellen laden ────────────────────────────────────────
    sources = load_all_sources()

    # ── Schritt 2: DB-Daten laden ─────────────────────────────────────────────
    conn = get_db()
    hist = load_historical_data(conn)
    if conn:
        try:
            conn.close()
        except Exception:
            pass

    # ── Schritt 3: System-Health berechnen ────────────────────────────────────
    health = calculate_system_health(hist, sources)

    # ── Health-Only Modus ─────────────────────────────────────────────────────
    if args.health:
        print(generate_health_report(health, hist))
        return

    # ── Schritt 4: Direktive bauen ────────────────────────────────────────────
    directive = build_directive(sources, hist, health)

    # ── Schritt 5: Report generieren ──────────────────────────────────────────
    report = generate_report(directive, hist)

    # ── Schritt 6: Direktive schreiben (wenn nicht --report) ──────────────────
    if not args.report:
        directive_path = WS / 'data/ceo_directive.json'
        try:
            with open(directive_path, 'w') as f:
                json.dump(directive, f, indent=2, ensure_ascii=False)
            print(f'✅ CEO-Direktive geschrieben: {directive_path}')
        except Exception as e:
            print(f'❌ Fehler beim Schreiben der Direktive: {e}', file=sys.stderr)

    # ── Schritt 7: Report ausgeben ────────────────────────────────────────────
    print()
    print(report)

    return report


if __name__ == '__main__':
    main()
