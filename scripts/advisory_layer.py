#!/usr/bin/env python3.14
"""
advisory_layer.py — KI erklärt jeden Trade in natürlicher Sprache
==================================================================
Wird nach jedem Trade-Entry aufgerufen.
Generiert eine kurze, verständliche Erklärung WARUM dieser Trade gemacht wurde.

Kein LLM-API-Call nötig — regelbasierte natürliche Sprache aus Conviction-Faktoren.
(LLM-Version optional per --llm Flag wenn Claude Code Auth verfügbar)
"""
import sqlite3
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

WS  = Path('/data/.openclaw/workspace')
DB  = WS / 'data/trading.db'
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts/core'))


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


# ─── Regelbasierte Erklärung ─────────────────────────────────────────────────

def build_explanation(ticker: str, strategy: str, conviction: dict) -> str:
    """
    Baut eine natürlichsprachliche Trade-Erklärung aus Conviction-Faktoren.
    Kein API-Call nötig — deterministisch und schnell.
    """
    score      = conviction.get('score', 0)
    factors    = conviction.get('factors', {})
    regime     = conviction.get('regime', 'UNKNOWN')
    vix        = conviction.get('vix', 0)
    style      = conviction.get('style', 'swing')

    # Thesis-Name leserlich machen
    THESIS_NAMES = {
        'PS1': 'Öl & Iran-These',
        'PS2': 'Tanker-Rates',
        'PS3': 'US Defense',
        'PS4': 'Edelmetalle',
        'PS5': 'Agrar & Dünger',
        'PS11': 'EU Rüstung',
        'PS14': 'Shipping',
        'PS_Copper': 'Kupfer-Transition',
        'PS_China': 'China Recovery',
        'PS_AIInfra': 'AI Infrastruktur',
        'PS_NVO': 'GLP-1 / Novo Nordisk',
        'PS_STLD': 'US Stahl-Zölle',
        'S1': 'Iran / Hormuz',
        'S2': 'Rüstung / NATO',
        'S3': 'KI / Halbleiter',
        'S4': 'Silber / Gold',
        'S5': 'Rohstoffe',
    }
    thesis_name = THESIS_NAMES.get(strategy, strategy)

    # Regime-Beschreibung
    REGIME_DESC = {
        'BULL_CALM':     'stabiler Aufwärtstrend',
        'BULL_VOLATILE': 'volatiler Aufwärtstrend',
        'NEUTRAL':       'neutrales Marktumfeld',
        'CORRECTION':    'Korrektur-Phase',
        'BEAR':          'Bären-Markt',
        'CRISIS':        'Markt-Krise',
    }
    regime_desc = REGIME_DESC.get(regime, f'Regime {regime}')

    # Stärkste Faktoren identifizieren
    reasons = []
    strengths = []
    warnings = []

    # News-Momentum
    news_score = factors.get('news_momentum', 50)
    if news_score >= 80:
        reasons.append(f"starke News-Unterstützung für {thesis_name} ({news_score}/100)")
        strengths.append('News')
    elif news_score >= 60:
        reasons.append(f"positive News-Lage für {thesis_name}")

    # Technisch / RSI
    tech_score = factors.get('technical', 50)
    rsi = conviction.get('rsi', None)
    if rsi is not None:
        if rsi < 35:
            reasons.append(f"überverkauft (RSI {rsi:.0f}) — Rebound-Potential")
            strengths.append('RSI-Überverkauft')
        elif 35 <= rsi <= 55:
            reasons.append(f"RSI {rsi:.0f} im neutralen Bereich — kein Überhitzen")
        elif rsi > 70:
            warnings.append(f"RSI {rsi:.0f} überkauft — erhöhtes Rücksetzer-Risiko")

    # Regime
    if regime in ('BULL_CALM', 'BULL_VOLATILE', 'NEUTRAL'):
        reasons.append(f"{regime_desc} erlaubt Entry")
        strengths.append('Regime')
    elif regime == 'CORRECTION':
        warnings.append(f"Korrektur-Phase — Stop wichtiger als sonst")

    # Sektor-Rotation
    sector_score = factors.get('sector_rotation', 50)
    if sector_score >= 70:
        reasons.append("Sektor aktuell outperformend")
        strengths.append('Sektor')

    # Confluence
    conf_score = factors.get('confluence', 50)
    if conf_score >= 70:
        reasons.append("mehrere Signale bestätigen sich gegenseitig")

    # Backtest
    bt_score = factors.get('backtest', 50)
    if bt_score >= 70:
        reasons.append(f"Strategie {strategy} historisch stark (Backtest)")

    # VIX Kontext
    if vix:
        if vix < 18:
            reasons.append(f"VIX {vix:.1f} — sehr niedriges Markt-Stress-Level")
        elif vix < 25:
            pass  # normal, nicht erwähnen
        elif vix < 30:
            warnings.append(f"VIX {vix:.1f} — erhöhte Volatilität, Stops breiter halten")

    # Style-Hinweis
    style_hint = ""
    if style == 'day':
        style_hint = " [DAY TRADE — Zwangsschluss 21:50]"

    # Satz zusammenbauen
    if not reasons:
        reasons.append(f"Thesis {thesis_name} aktiv, Conviction-Score {score}/100")

    main_reason = reasons[0].capitalize()
    supporting  = reasons[1:3]

    explanation = f"**Warum {ticker}?** {main_reason}."
    if supporting:
        explanation += f" Zusätzlich: {'; '.join(supporting)}."
    if warnings:
        explanation += f" ⚠️ Risiko: {warnings[0]}."
    explanation += style_hint

    return explanation


def generate_and_store(trade_id: int) -> str | None:
    """
    Holt Trade-Daten aus DB, generiert Erklärung, speichert in notes.
    Returns: Erklärungstext
    """
    conn = get_db()
    trade = conn.execute(
        '''SELECT id, ticker, strategy, conviction, rsi_at_entry, regime_at_entry,
                  entry_price, stop_price, target_price, style, notes
           FROM paper_portfolio WHERE id=?''',
        (trade_id,)
    ).fetchone()

    if not trade:
        conn.close()
        return None

    # Conviction als Mini-Dict aufbauen (ohne vollständige Neuberechnung)
    conv_dict = {
        'score':   trade['conviction'] or 0,
        'regime':  trade['regime_at_entry'] or 'NEUTRAL',
        'rsi':     trade['rsi_at_entry'],
        'style':   trade['style'] or 'swing',
        'factors': {},
    }

    # VIX aus DB
    vix_row = conn.execute(
        "SELECT value FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if vix_row:
        conv_dict['vix'] = vix_row['value']

    explanation = build_explanation(trade['ticker'], trade['strategy'], conv_dict)

    # In trade_advisory speichern
    conn.execute('''
        INSERT OR REPLACE INTO trade_advisory
        (trade_id, entry_reasoning, ts)
        VALUES (?, ?, ?)
        ON CONFLICT(trade_id) DO UPDATE SET entry_reasoning=excluded.entry_reasoning
    ''', (trade_id, explanation, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

    return explanation


def ensure_journal_schema():
    conn = get_db()
    # Neue advisory-Tabelle (trennen von alter trade_advisory)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trade_advisory (
            trade_id        INTEGER PRIMARY KEY,
            entry_reasoning TEXT,
            exit_reasoning  TEXT,
            lesson          TEXT,
            ts              TEXT
        )
    ''')
    conn.commit()
    conn.close()


def get_explanation(trade_id: int) -> str | None:
    """Liest gespeicherte Erklärung für einen Trade."""
    conn = get_db()
    row = conn.execute(
        'SELECT entry_reasoning FROM trade_advisory WHERE trade_id=?', (trade_id,)
    ).fetchone()
    conn.close()
    return row['entry_reasoning'] if row else None


# ─── Batch: alle Trades ohne Erklärung befüllen ──────────────────────────────

def backfill_missing():
    """Generiert Erklärungen für alle Trades die noch keine haben."""
    ensure_journal_schema()
    conn = get_db()
    trades = conn.execute('''
        SELECT p.id FROM paper_portfolio p
        LEFT JOIN trade_advisory j ON p.id = j.trade_id
        WHERE j.entry_reasoning IS NULL
        ORDER BY p.entry_date DESC
    ''').fetchall()
    conn.close()

    count = 0
    for t in trades:
        e = generate_and_store(t['id'])
        if e:
            count += 1
    return count


if __name__ == '__main__':
    ensure_journal_schema()

    if '--backfill' in sys.argv:
        n = backfill_missing()
        print(f"✅ {n} Trade-Erklärungen generiert")

    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        trade_id = int(sys.argv[1])
        e = generate_and_store(trade_id)
        print(e or "Trade nicht gefunden")

    else:
        # Demo: letzte 3 Trades
        ensure_journal_schema()
        n = backfill_missing()
        print(f"Backfill: {n} neue Erklärungen\n")

        conn = get_db()
        rows = conn.execute('''
            SELECT p.ticker, p.strategy, p.conviction, j.entry_reasoning
            FROM paper_portfolio p
            JOIN trade_advisory j ON p.id = j.trade_id
            ORDER BY p.entry_date DESC LIMIT 5
        ''').fetchall()
        conn.close()
        for r in rows:
            print(f"[{r['strategy']} | Conv {r['conviction']}] {r['ticker']}")
            print(f"  {r['entry_reasoning']}\n")
