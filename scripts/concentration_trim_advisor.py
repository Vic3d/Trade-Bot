#!/usr/bin/env python3
"""
Concentration Trim Advisor — Sub-9 (2026-04-23)
================================================
Erkennt Klumpenrisiken im offenen Portfolio und schlaegt eine Trim-Aktion
per Discord vor. Sells werden NIE automatisch ausgefuehrt — Victor
entscheidet manuell (Stop-Loss ist heilig, Sell-Logik gleichermassen).

Schwellen:
  - Single-Position > 30% des Total-Equity (cash + open) → Trim auf 25%
  - Top-3 Konzentration > 70% → Hinweis (kein konkreter Trim-Vorschlag)

Cooldown: 1 Alert pro Ticker pro 12h, sonst Spam.
Hinweis-Datei: data/trim_advisor_state.json

USAGE:
    python3 scripts/concentration_trim_advisor.py [--quiet] [--dry-run]
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DATA = WS / 'data'
DB = DATA / 'trading.db'
STATE = DATA / 'trim_advisor_state.json'

SINGLE_TRIGGER_PCT = 30.0   # > 30% → Trim-Vorschlag
SINGLE_TARGET_PCT = 25.0    # auf 25% reduzieren
TOP3_TRIGGER_PCT = 70.0     # > 70% Top-3 → Hinweis
COOLDOWN_HOURS = 12


def _load_state() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    except Exception as e:
        print(f'state save failed: {e}', file=sys.stderr)


def _cooldown_ok(state: dict, key: str) -> bool:
    last = state.get(key)
    if not last:
        return True
    try:
        dt = datetime.fromisoformat(last)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600 >= COOLDOWN_HOURS
    except Exception:
        return True


def _get_cash() -> float:
    """Liest aktuellen Cash-Stand aus paper_fund (neueste Zeile)."""
    try:
        conn = sqlite3.connect(str(DB))
        conn.row_factory = sqlite3.Row
        # paper_fund hat mehrere Schemas — lese tolerant
        row = conn.execute(
            "SELECT * FROM paper_fund ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return 0.0
        # Spalten-Heuristik
        for col in ('cash', 'cash_eur', 'cash_balance', 'balance'):
            try:
                v = row[col]
                if v is not None:
                    return float(v)
            except (KeyError, IndexError):
                continue
        return 0.0
    except Exception as e:
        print(f'cash read failed: {e}', file=sys.stderr)
        return 0.0


def _get_open_positions() -> list[dict]:
    """Holt offene Positionen mit aktuellem Marktwert (entry_price * shares
    als Naeherung — kein Live-Lookup hier um leichtgewichtig zu bleiben)."""
    if not DB.exists():
        return []
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, ticker, shares, entry_price, stop_price "
            "FROM paper_portfolio WHERE UPPER(status)='OPEN'"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        shares = float(r['shares'] or 0)
        entry = float(r['entry_price'] or 0)
        cost = shares * entry
        if cost <= 0:
            continue
        out.append({
            'id': r['id'],
            'ticker': r['ticker'],
            'shares': shares,
            'entry_price': entry,
            'stop_price': r['stop_price'],
            'cost_eur': cost,
        })
    return out


def analyze() -> list[dict]:
    """Returnt Liste von Findings: {kind, ticker, pct, suggested_action, ...}."""
    findings: list[dict] = []
    cash = _get_cash()
    positions = _get_open_positions()
    open_total = sum(p['cost_eur'] for p in positions)
    equity = cash + open_total
    if equity <= 0:
        return findings

    # Sortieren nach Groesse
    positions.sort(key=lambda p: p['cost_eur'], reverse=True)

    # Single-Position Trigger
    for p in positions:
        pct = p['cost_eur'] / equity * 100
        if pct > SINGLE_TRIGGER_PCT:
            target_eur = equity * (SINGLE_TARGET_PCT / 100)
            trim_eur = p['cost_eur'] - target_eur
            trim_shares = round(trim_eur / p['entry_price'], 2) if p['entry_price'] > 0 else 0
            findings.append({
                'kind': 'SINGLE_OVER_LIMIT',
                'ticker': p['ticker'],
                'pct': round(pct, 1),
                'cost_eur': round(p['cost_eur'], 2),
                'equity_eur': round(equity, 2),
                'shares_total': p['shares'],
                'trim_shares': trim_shares,
                'trim_eur': round(trim_eur, 2),
                'target_pct': SINGLE_TARGET_PCT,
            })

    # Top-3 Trigger
    if len(positions) >= 3:
        top3_cost = sum(p['cost_eur'] for p in positions[:3])
        top3_pct = top3_cost / equity * 100
        if top3_pct > TOP3_TRIGGER_PCT:
            findings.append({
                'kind': 'TOP3_CONCENTRATION',
                'tickers': [p['ticker'] for p in positions[:3]],
                'pct': round(top3_pct, 1),
                'cost_eur': round(top3_cost, 2),
                'equity_eur': round(equity, 2),
            })

    return findings


def _format_alert(f: dict) -> str:
    if f['kind'] == 'SINGLE_OVER_LIMIT':
        return (
            f"⚠️ **Klumpenrisiko: {f['ticker']}**\n"
            f"Position = {f['pct']}% des Equity ({f['cost_eur']:.0f}€ / {f['equity_eur']:.0f}€)\n"
            f"Schwelle: > {SINGLE_TRIGGER_PCT}% — Vorschlag: Trim auf {f['target_pct']}%\n"
            f"→ Verkaufen: **{f['trim_shares']:.2f} Shares** (~{f['trim_eur']:.0f}€)\n"
            f"Aktion: Manuell in Trade Republic ausfuehren oder per Discord zustimmen."
        )
    if f['kind'] == 'TOP3_CONCENTRATION':
        return (
            f"⚠️ **Top-3 Konzentration**\n"
            f"{', '.join(f['tickers'])} = {f['pct']}% des Equity ({f['cost_eur']:.0f}€)\n"
            f"Schwelle: > {TOP3_TRIGGER_PCT}% — Diversifikation erhoehen empfohlen."
        )
    return f"⚠️ Unbekanntes Finding: {f}"


def _send_alert(msg: str) -> None:
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_dispatcher import send_alert as _dispatch, TIER_MEDIUM
        _dispatch(msg, tier=TIER_MEDIUM, category='risk')
    except Exception:
        try:
            from discord_sender import send
            send(msg)
        except Exception as e:
            print(f'Discord send failed: {e}', file=sys.stderr)


def run(quiet: bool = False, dry_run: bool = False) -> int:
    findings = analyze()
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if not findings:
        if not quiet:
            print(f'[{ts}] Konzentration OK ✅')
        return 0

    state = _load_state()
    sent = 0
    for f in findings:
        key = f.get('ticker') or f['kind']
        msg = _format_alert(f)
        print(msg)
        if dry_run:
            continue
        if not _cooldown_ok(state, key):
            print(f'  [{key}] cooldown aktiv — kein Discord-Alert')
            continue
        _send_alert(msg)
        state[key] = ts
        sent += 1

    if not dry_run:
        _save_state(state)
    print(f'\n[{ts}] {len(findings)} Finding(s), {sent} Discord-Alert(s) gesendet')
    return 0 if sent == 0 else 1


def main():
    quiet = '--quiet' in sys.argv
    dry = '--dry-run' in sys.argv
    sys.exit(run(quiet=quiet, dry_run=dry))


if __name__ == '__main__':
    main()
