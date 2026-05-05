#!/usr/bin/env python3
"""
current_truth.py — Phase 44ac: Canonical 'As-Of-Now' State-Pack.

Halluzinations-Wurzel: LLM-Pipelines lesen MD-Files mit historischen
References UND DB-State gemischt. Albert verwechselt 'gestern' mit 'heute',
'Vorschlag' mit 'aktuelle Position'.

Diese Datei liefert die EINE QUELLE DER WAHRHEIT die jeder LLM-Call als
verbindlichen Header bekommt:

  AS-OF: 2026-05-03T07:30:00 UTC (Berlin: 09:30)
  WEEKDAY: Sonntag
  MARKETS: alle geschlossen (Sa/So)

  OPEN POSITIONS (verifiziert aus DB):
    - MOS (PS5) entry 19.89, stop 21.68 (+9%), target 22.27
    - PAAS (PS4) entry 44.80, stop 49.26 (+10%), target 50.63

  ACTIVE STRATEGIES: 9 (S1, PS1, PS2, PS4, PS5, PS13, PS14, PS15, PT)

  CASH: 22.5k EUR

LLM-Pipelines bekommen das als FIRST CONTEXT BLOCK. Halluzinationen
ueber Positionen, Datum, Strategy-Status werden so unmoeglich (oder
sind direkt offensichtlich als Verstoss gegen den expliziten Header).

Run: python3 scripts/current_truth.py        # Print the pack
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'


def get_truth() -> dict:
    """Liefert die canonical truth as-of-now."""
    try:
        from zoneinfo import ZoneInfo
        bt = datetime.now(ZoneInfo('Europe/Berlin'))
    except Exception:
        bt = datetime.now()
    weekday_de = ['Montag','Dienstag','Mittwoch','Donnerstag','Freitag',
                   'Samstag','Sonntag'][bt.weekday()]
    is_weekend = bt.weekday() >= 5

    truth = {
        'as_of_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'as_of_berlin': bt.strftime('%Y-%m-%d %H:%M %Z'),
        'weekday': weekday_de,
        'is_weekend': is_weekend,
        'markets_status': 'CLOSED (Wochenende)' if is_weekend else 'siehe calendar_service',
        'open_positions': [],
        'active_strategies': [],
        'cash_eur': None,
    }

    if DB.exists():
        try:
            c = sqlite3.connect(str(DB))
            c.row_factory = sqlite3.Row
            for r in c.execute(
                "SELECT id, ticker, strategy, entry_price, stop_price, target_price, "
                "       shares FROM paper_portfolio WHERE status='OPEN'"
            ).fetchall():
                d = dict(r)
                d['stop_pct_from_entry'] = round((d['stop_price']/d['entry_price']-1)*100, 1) if d['entry_price'] else 0
                truth['open_positions'].append(d)
            cash_row = c.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()
            if cash_row:
                truth['cash_eur'] = round(float(cash_row[0]), 0)
            # Phase 45k+: closed trades letzte 7d (verhindert dass Claude sie
            # frisch aus der DB ziehen muss bei "Wochen-Zusammenfassung")
            truth['closed_7d'] = []
            for r in c.execute(
                "SELECT ticker, strategy, "
                "  substr(close_date,1,10) AS exit_date, "
                "  ROUND(pnl_eur,1) AS pnl_eur, "
                "  ROUND(pnl_pct*100,1) AS pnl_pct, "
                "  exit_type "
                "FROM paper_portfolio "
                "WHERE close_date >= date('now','-7 days') "
                "  AND status IN ('CLOSED','WIN','LOSS') "
                "  AND pnl_eur IS NOT NULL "
                "ORDER BY close_date DESC LIMIT 25"
            ):
                truth['closed_7d'].append(dict(r))
            agg = c.execute(
                "SELECT COUNT(*) n, "
                "  SUM(CASE WHEN pnl_eur>0 THEN 1 ELSE 0 END) wins, "
                "  SUM(CASE WHEN pnl_eur<0 THEN 1 ELSE 0 END) losses, "
                "  ROUND(SUM(pnl_eur),1) total_eur "
                "FROM paper_portfolio "
                "WHERE close_date >= date('now','-7 days') AND pnl_eur IS NOT NULL"
            ).fetchone()
            if agg:
                truth['closed_7d_agg'] = dict(agg)
            c.close()
        except Exception as e:
            truth['db_error'] = str(e)

    sf = WS / 'data' / 'strategies.json'
    if sf.exists():
        try:
            s = json.loads(sf.read_text(encoding='utf-8'))
            truth['active_strategies'] = sorted([
                sid for sid, v in s.items()
                if isinstance(v, dict) and v.get('status') == 'active'
            ])
        except Exception: pass

    # Phase 45k (Victor 2026-05-05): Single Source of Truth fuer Strategy-
    # Verdicts. Ohne diesen Block koennen LLM und CLI-Claude widerspruechliche
    # Aussagen ueber Strategien machen (PS5-Bug 05.05).
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from strategy_verdict import all_verdicts  # type: ignore
        verdicts = all_verdicts()
        truth['strategy_verdicts'] = [
            {
                'sid': v['sid'],
                'verdict': v['verdict'],
                'confidence': v['confidence'],
                'rec': v['recommendation'][:120],
                'conflicts': v['conflicts'],
            }
            for v in verdicts
        ]
        truth['strategy_conflicts'] = [
            v['sid'] for v in verdicts if v['conflicts']
        ]
    except Exception as e:
        truth['strategy_verdicts'] = []
        truth['strategy_verdict_error'] = str(e)

    return truth


def format_for_llm(truth: dict | None = None) -> str:
    """Formatiert canonical truth als Markdown-Header fuer LLM-Prompts."""
    if truth is None:
        truth = get_truth()

    lines = [
        '═══ CURRENT TRUTH (verbindliche As-Of-Now Fakten) ═══',
        f'AS-OF: {truth["as_of_berlin"]}  ({truth["weekday"]})',
        f'MARKETS: {truth["markets_status"]}',
        '',
    ]
    if truth.get('open_positions'):
        lines.append(f'OPEN POSITIONS ({len(truth["open_positions"])}):')
        for p in truth['open_positions']:
            lines.append(
                f"  - {p['ticker']} ({p['strategy']}) entry {p['entry_price']:.2f}, "
                f"stop {p['stop_price']:.2f} ({p['stop_pct_from_entry']:+.1f}% vom Entry), "
                f"target {p['target_price']:.2f}"
            )
    else:
        lines.append('OPEN POSITIONS: KEINE (0 offene Positionen)')
    lines.append('')
    if truth.get('active_strategies'):
        lines.append(f'ACTIVE STRATEGIES ({len(truth["active_strategies"])}): '
                      f'{", ".join(truth["active_strategies"])}')
    if truth.get('cash_eur') is not None:
        lines.append(f'CASH: {truth["cash_eur"]:.0f} EUR')
    lines.append('')

    # Phase 45k+: Closed Trades letzte 7 Tage (Wochen-Zusammenfassung Inputs)
    agg = truth.get('closed_7d_agg') or {}
    closed = truth.get('closed_7d') or []
    if agg.get('n'):
        lines.append(
            f'CLOSED 7d: {agg.get("n",0)} Trades '
            f'({agg.get("wins",0)}W/{agg.get("losses",0)}L) '
            f'PnL {agg.get("total_eur",0):+.1f} EUR'
        )
        for t in closed[:10]:
            lines.append(
                f'  - {t.get("exit_date","")}  {t["ticker"]:8s} ({t["strategy"]:8s}) '
                f'{t["pnl_eur"]:+7.1f} EUR / {t.get("pnl_pct",0):+5.1f}%  {t.get("exit_type","")}'
            )
        if len(closed) > 10:
            lines.append(f'  ... +{len(closed)-10} weitere')
        lines.append('')

    # Phase 45k: Strategy-Verdicts als verbindliche Single-Source-of-Truth
    sv = truth.get('strategy_verdicts') or []
    if sv:
        lines.append(f'STRATEGY VERDICTS ({len(sv)}) — EINZIGE gueltige Quelle:')
        # Nur Non-OK-Verdicts ausfuehrlich, OK/STRONG_EDGE compact
        groups: dict[str, list[str]] = {}
        for v in sv:
            groups.setdefault(v['verdict'], []).append(v['sid'])
        compact = ['STRONG_EDGE', 'OK']
        for verdict in compact:
            if verdict in groups:
                lines.append(f'  {verdict}: {", ".join(sorted(groups[verdict]))}')
        for v in sv:
            if v['verdict'] in compact:
                continue
            tag = '⚠ CONFLICT' if v['conflicts'] else v['verdict']
            lines.append(f'  [{tag}] {v["sid"]}: {v["rec"]}')
        if truth.get('strategy_conflicts'):
            lines.append('')
            lines.append(f'CONFLICTS BETWEEN SOURCES: {", ".join(truth["strategy_conflicts"])}')
            lines.append('  → Diese Strategien haben widerspruechliche Signale.')
            lines.append('  → KEINE Aussage ueber Edge ohne strategy_verdict() abzufragen.')
        lines.append('')

    lines.append('REGEL: Wenn du etwas ueber Positionen/Strategien/Datum schreibst,')
    lines.append('       MUSS es mit obigem Block uebereinstimmen. Kein Mention von')
    lines.append('       Tickers/Strategien die NICHT oben aufgelistet sind.')
    lines.append('       Strategy-Edge IMMER aus STRATEGY VERDICTS, nicht aus Erinnerung.')
    lines.append('═══════════════════════════════════════════════')
    return '\n'.join(lines)


def main() -> int:
    truth = get_truth()
    print(format_for_llm(truth))
    print()
    print('--- raw JSON ---')
    print(json.dumps(truth, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
