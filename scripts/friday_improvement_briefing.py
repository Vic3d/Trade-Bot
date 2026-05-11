#!/usr/bin/env python3
"""
friday_improvement_briefing.py — Phase 45n (Victor 2026-05-05).

Wochen-Abschluss-Briefing fuer Victor jeden Freitag 18:00 CET.

User-Direktive:
  "Schicke mir Freitag-Abend Verbesserungsvorschlaege fuer das System,
   basierend auf den Beobachtungen der Woche."

Datenquellen (alle der letzten 7 Tage):
  - data/cli_audit_violations.jsonl       — CLI-Claude-Halluzinationen
  - data/halluzination_log.jsonl          — Albert-Halluzinationen
  - data/halluzination_sweep_report.jsonl — Sweeper-Aggregate
  - data/strategy_verdict_conflicts.jsonl — widerspruechliche Quellen
  - data/tool_usage_inventory.jsonl       — welche Skripte tot
  - data/quant_metrics.json               — Mission-KPI-Status
  - paper_portfolio (DB)                  — Trades, PnL der Woche

Output:
  - data/friday_briefings/{YYYY-MM-DD}.md (markdown, persistent)
  - Discord-HIGH-Push (an Victor, Channel 1492225799062032484)

CLI:
  python3 scripts/friday_improvement_briefing.py            # Run + Discord
  python3 scripts/friday_improvement_briefing.py --dry-run  # Nur stdout
"""
from __future__ import annotations
import json, os, sqlite3, sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
OUT_DIR = WS / 'data' / 'friday_briefings'


def _read_jsonl(path: Path, since_days: int = 7) -> list[dict]:
    if not path.exists(): return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    out = []
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    ts_raw = obj.get('ts') or obj.get('timestamp') or obj.get('date')
                    if ts_raw:
                        try:
                            ts = datetime.fromisoformat(str(ts_raw).replace('Z', '+00:00'))
                            if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
                            if ts < cutoff: continue
                        except Exception: pass
                    out.append(obj)
                except Exception: continue
    except Exception: pass
    return out


def _hallu_summary() -> dict:
    cli = _read_jsonl(WS / 'data' / 'cli_audit_violations.jsonl')
    albert = _read_jsonl(WS / 'data' / 'halluzination_log.jsonl')
    kinds_cli, kinds_albert = Counter(), Counter()
    for r in cli:
        for v in r.get('violations') or []:
            kinds_cli[v.get('kind') or v.get('type') or 'unknown'] += 1
    for r in albert:
        for v in r.get('violations') or []:
            kinds_albert[v.get('kind') or 'unknown'] += 1
    return {
        'n_cli_events': len(cli),
        'n_albert_events': len(albert),
        'top_kinds_cli': kinds_cli.most_common(5),
        'top_kinds_albert': kinds_albert.most_common(5),
    }


def _conflict_summary() -> dict:
    rows = _read_jsonl(WS / 'data' / 'strategy_verdict_conflicts.jsonl', 7)
    sids = Counter(r.get('sid', 'unknown') for r in rows)
    return {'n_conflicts': len(rows), 'top_sids': sids.most_common(5)}


def _tool_usage_summary() -> dict:
    rows = _read_jsonl(WS / 'data' / 'tool_usage_inventory.jsonl', 7)
    if not rows:
        return {'note': 'tool_usage_inventory leer (Tracker noch jung)'}
    last = rows[-1]
    return {
        'n_scripts_total': last.get('n_scripts_total', 0),
        'n_scripts_used_24h_lastrun': last.get('n_scripts_used_24h', 0),
        'pct_used_lastrun': last.get('pct_used', 0),
    }


def _trade_week_summary() -> dict:
    out = {'closed_n': 0, 'wins': 0, 'losses': 0, 'pnl_eur': 0,
           'open_n': 0, 'cash_eur': 0}
    if not DB.exists(): return out
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        agg = c.execute(
            "SELECT COUNT(*) n, "
            " SUM(CASE WHEN pnl_eur>0 THEN 1 ELSE 0 END) wins, "
            " SUM(CASE WHEN pnl_eur<0 THEN 1 ELSE 0 END) losses, "
            " ROUND(SUM(pnl_eur),1) total "
            "FROM paper_portfolio WHERE close_date >= date('now','-7 days') "
            "AND pnl_eur IS NOT NULL"
        ).fetchone()
        if agg:
            out.update({'closed_n': agg['n'] or 0, 'wins': agg['wins'] or 0,
                        'losses': agg['losses'] or 0, 'pnl_eur': agg['total'] or 0})
        out['open_n'] = c.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'").fetchone()[0]
        cash = c.execute(
            "SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()
        if cash: out['cash_eur'] = round(float(cash[0]), 0)
        c.close()
    except Exception as e:
        out['db_error'] = str(e)
    return out


def _mission_kpi_status() -> dict:
    """Aktueller Stand der 5 Mission-KPIs."""
    out = {}
    qf = WS / 'data' / 'quant_metrics.json'
    if qf.exists():
        try:
            q = json.loads(qf.read_text(encoding='utf-8'))
            at = q.get('all_time') or {}
            l30 = q.get('last_30d') or {}
            out['sharpe_lifetime'] = at.get('sharpe')
            out['sharpe_30d'] = l30.get('sharpe')
            out['mission_verdict_30d'] = q.get('mission_verdict_30d')
            out['mission_verdict_all_time'] = q.get('mission_verdict_all_time')
        except Exception: pass
    return out


def _generate_recommendations(data: dict) -> list[dict]:
    """Heuristik-basierte Empfehlungen aus den Wochen-Daten."""
    recs = []
    h = data['halluzinations']
    if h['n_cli_events'] > 5:
        recs.append({
            'priority': 'HIGH',
            'topic': f'CLI-Halluzinationen haeufen sich ({h["n_cli_events"]}/Woche)',
            'action': f'Detector-Pattern erweitern fuer dominante Klasse: {h["top_kinds_cli"][:1]}',
        })
    if h['n_albert_events'] > 10:
        recs.append({
            'priority': 'HIGH',
            'topic': f'Albert-Halluzinationen haeufen sich ({h["n_albert_events"]}/Woche)',
            'action': 'Truth-Inject im LLM-Wrapper verschaerfen oder System-Prompt klaerer',
        })

    c = data['conflicts']
    if c['n_conflicts'] > 0:
        sids = ', '.join(s for s, _ in c['top_sids'][:3])
        recs.append({
            'priority': 'MED',
            'topic': f'{c["n_conflicts"]} Strategy-Verdict-Konflikte ({sids})',
            'action': 'Diese SIDs manuell pruefen — welche Quelle ist wirklich richtig?',
        })

    t = data['tool_usage']
    if t.get('pct_used_lastrun', 100) < 5:
        recs.append({
            'priority': 'LOW',
            'topic': f'Nur {t.get("pct_used_lastrun")}% der Skripte aktiv',
            'action': 'Tool-Usage-Tracker zeigt viele Tote — am 04.06 Aufraumen-Run',
        })

    tr = data['trades']
    if tr['closed_n'] < 3:
        recs.append({
            'priority': 'HIGH',
            'topic': f'Nur {tr["closed_n"]} Closed Trades / Woche — zu wenig fuer Edge-Detection',
            'action': 'Hunter-Threshold weiter senken oder neue Setups freigeben',
        })
    if tr['open_n'] < 2 and tr['cash_eur'] > 25000:
        recs.append({
            'priority': 'MED',
            'topic': f'Bot sitzt auf {tr["cash_eur"]:.0f} EUR Cash mit nur {tr["open_n"]} Position',
            'action': 'Conviction-Threshold weiter relaxen oder Universum erweitern',
        })

    m = data['mission']
    sl = m.get('sharpe_lifetime')
    if sl is not None and sl < 1.0:
        recs.append({
            'priority': 'MED',
            'topic': f'Sharpe Lifetime = {sl:.2f} (Mission-Ziel >2)',
            'action': 'Strategien mit negativem PF identifizieren und retiren',
        })
    s30 = m.get('sharpe_30d')
    if s30 is not None and s30 < 0:
        recs.append({
            'priority': 'HIGH',
            'topic': f'Sharpe 30d = {s30:.2f} negativ — Trend nach unten',
            'action': 'Letzte 30d-Trades analysieren: gemeinsamer Failure-Mode?',
        })

    if not recs:
        recs.append({
            'priority': 'INFO',
            'topic': 'Keine kritischen Patterns diese Woche',
            'action': 'System laeuft sauber. Weiter beobachten, nichts aendern.',
        })
    return recs


def collect() -> dict:
    return {
        'week_ending': datetime.now().date().isoformat(),
        'halluzinations': _hallu_summary(),
        'conflicts': _conflict_summary(),
        'tool_usage': _tool_usage_summary(),
        'trades': _trade_week_summary(),
        'mission': _mission_kpi_status(),
    }


def render_markdown(data: dict, recs: list[dict]) -> str:
    lines = [
        f'# Friday Improvement Briefing — {data["week_ending"]}',
        '',
        '_Auto-generiert. Basierend auf Audit-Logs der letzten 7 Tage._',
        '',
        '## Wochen-Performance',
        '',
        f'- Closed Trades: {data["trades"]["closed_n"]} '
        f'({data["trades"]["wins"]}W/{data["trades"]["losses"]}L) '
        f'PnL **{data["trades"]["pnl_eur"]:+.1f} EUR**',
        f'- Open Positions: {data["trades"]["open_n"]}',
        f'- Cash: {data["trades"]["cash_eur"]:.0f} EUR',
        '',
        '## Halluzinations-Audit',
        '',
        f'- CLI-Claude: {data["halluzinations"]["n_cli_events"]} Events, '
        f'top: {data["halluzinations"]["top_kinds_cli"]}',
        f'- Albert: {data["halluzinations"]["n_albert_events"]} Events, '
        f'top: {data["halluzinations"]["top_kinds_albert"]}',
        '',
        '## Quellen-Konflikte',
        '',
        f'- {data["conflicts"]["n_conflicts"]} strategy_verdict-Konflikte',
        f'- Top SIDs: {data["conflicts"]["top_sids"]}',
        '',
        '## Tool-Usage',
        '',
        f'- {data["tool_usage"]}',
        '',
        '## Mission-KPIs',
        '',
        f'- Sharpe lifetime: {data["mission"].get("sharpe_lifetime")}',
        f'- Sharpe 30d: {data["mission"].get("sharpe_30d")}',
        f'- Verdict 30d: {data["mission"].get("mission_verdict_30d")}',
        f'- Verdict all-time: {data["mission"].get("mission_verdict_all_time")}',
        '',
        '## Verbesserungsvorschlaege',
        '',
    ]
    prio_order = {'HIGH': 0, 'MED': 1, 'LOW': 2, 'INFO': 3}
    for r in sorted(recs, key=lambda x: prio_order.get(x['priority'], 9)):
        lines.append(f'### [{r["priority"]}] {r["topic"]}')
        lines.append(f'> {r["action"]}')
        lines.append('')

    # Phase 45s: Narrativ-Block
    try:
        narrative = _friday_narrative(data, recs)
        if narrative:
            lines.append('## 📖 Wochen-Narrativ')
            lines.append('')
            lines.append(narrative)
    except Exception:
        pass

    return '\n'.join(lines)


def _friday_narrative(data: dict, recs: list[dict]) -> str:
    """Phase 45s: 5-7 Saetze Wochenabschluss via narrative_generator."""
    facts: list[str] = []
    tr = data.get('trades') or {}
    facts.append(f"WOCHE: {tr.get('closed_n',0)} Trades ({tr.get('wins',0)}W/{tr.get('losses',0)}L), PnL {tr.get('pnl_eur',0):+.1f} EUR")
    facts.append(f"OPEN: {tr.get('open_n',0)} Positionen, Cash {tr.get('cash_eur',0):.0f} EUR")
    h = data.get('halluzinations') or {}
    facts.append(f"HALLUZINATIONS: CLI {h.get('n_cli_events',0)}, Albert {h.get('n_albert_events',0)} Events")
    if h.get('top_kinds_albert'):
        facts.append(f"  top Albert-Kinds: {h['top_kinds_albert']}")
    c = data.get('conflicts') or {}
    facts.append(f"VERDICT-KONFLIKTE: {c.get('n_conflicts',0)}")
    m = data.get('mission') or {}
    facts.append(f"MISSION: Sharpe lifetime {m.get('sharpe_lifetime')}, 30d {m.get('sharpe_30d')}, verdict 30d {m.get('mission_verdict_30d')}")
    if recs:
        facts.append(f"TOP-RECOMMENDATIONS:")
        for r in recs[:5]:
            facts.append(f"  [{r['priority']}] {r['topic']}: {r['action'][:140]}")
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from narrative_generator import build_narrative  # type: ignore
        return build_narrative(facts, briefing_type='friday')
    except Exception:
        return '\n'.join(facts)


def push_discord(text: str) -> None:
    """Discord-HIGH push (Phase 45an Fix — send_alert statt dispatch)."""
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_dispatcher import send_alert  # type: ignore
        from datetime import datetime as _dt
        send_alert(text, tier="HIGH", category="friday_briefing",
                   dedupe_key=f"friday_{_dt.now().date()}")
    except Exception as e:
        print(f'[discord push failed: {e}]', file=sys.stderr)


def main() -> int:
    dry = '--dry-run' in sys.argv
    data = collect()
    recs = _generate_recommendations(data)
    md = render_markdown(data, recs)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f'{data["week_ending"]}.md'
    out_path.write_text(md, encoding='utf-8')

    print(md)
    if not dry:
        # Discord nur Top-3 + Footer
        prio_order = {'HIGH': 0, 'MED': 1, 'LOW': 2, 'INFO': 3}
        top_recs = sorted(recs, key=lambda x: prio_order.get(x['priority'], 9))[:3]
        msg_lines = [f'📋 **Friday Briefing — {data["week_ending"]}**', '']
        msg_lines.append(
            f'Wochen-PnL: **{data["trades"]["pnl_eur"]:+.1f}€** '
            f'({data["trades"]["wins"]}W/{data["trades"]["losses"]}L)'
        )
        msg_lines.append('')
        msg_lines.append('**Verbesserungs-Top-3:**')
        for r in top_recs:
            msg_lines.append(f'• [{r["priority"]}] {r["topic"]}')
            msg_lines.append(f'  → {r["action"]}')
        msg_lines.append('')
        msg_lines.append(f'_Volle Datei: data/friday_briefings/{data["week_ending"]}.md_')
        push_discord('\n'.join(msg_lines))
    return 0


if __name__ == '__main__':
    sys.exit(main())
