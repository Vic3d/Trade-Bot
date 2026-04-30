#!/usr/bin/env python3
"""
ceo_strategy_review.py — Phase 44g: CEO ueberprueft alle Strategien per LLM.

Nach aggressivem Auto-Deprecate laeuft der CEO ueber ALLE verbleibenden
Strategien (status active/None/watchlist/watching/EVALUATING) und entscheidet:

  KEEP   — Strategie ist relevant, weiter aktiv
  WATCH  — Strategie ist grenzwertig, beobachten
  RETIRE — Strategie ist tot, status='retired'

Inputs pro Strategie:
  - thesis text
  - tickers list
  - lifetime stats (n trades, PnL, WR)
  - last trade date
  - aktuelle Macro-Lage (ceo_directive + last 5 macro_events)

LLM-Output: JSON {decision, reason}

Run:
  python3 scripts/ceo_strategy_review.py             # echte Reviews + Apply
  python3 scripts/ceo_strategy_review.py --dry-run   # nur Vorschlag
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
STRATS_FILE = WS / 'data' / 'strategies.json'
DIRECTIVE_FILE = WS / 'data' / 'ceo_directive.json'
REVIEW_LOG = WS / 'data' / 'ceo_strategy_review_log.jsonl'

PERMANENT_BLOCKED = {'AR-AGRA', 'AR-HALB', 'DT1', 'DT2', 'DT3', 'DT4', 'DT5'}
LIVE_STATUS = {'active', None, '', 'watchlist', 'watching', 'EVALUATING'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _gather_strategy_data(sid: str, meta: dict, c: sqlite3.Connection) -> dict:
    """Sammelt Statistik-Snapshot pro Strategie."""
    n_lifetime = c.execute(
        "SELECT COUNT(*) FROM paper_portfolio WHERE strategy=?", (sid,)
    ).fetchone()[0]
    pnl = c.execute(
        "SELECT COALESCE(SUM(pnl_eur),0) FROM paper_portfolio WHERE strategy=?",
        (sid,)
    ).fetchone()[0] or 0
    wins = c.execute(
        "SELECT COUNT(*) FROM paper_portfolio "
        "WHERE strategy=? AND status IN ('WIN','CLOSED') AND pnl_eur > 0",
        (sid,)
    ).fetchone()[0]
    n_closed = c.execute(
        "SELECT COUNT(*) FROM paper_portfolio "
        "WHERE strategy=? AND status IN ('WIN','LOSS','CLOSED','RESET_CLOSED')",
        (sid,)
    ).fetchone()[0]
    last_trade = c.execute(
        "SELECT MAX(entry_date) FROM paper_portfolio WHERE strategy=?", (sid,)
    ).fetchone()[0]
    n_30d = c.execute(
        "SELECT COUNT(*) FROM paper_portfolio "
        "WHERE strategy=? AND substr(entry_date,1,10) >= date('now','-30 days')",
        (sid,)
    ).fetchone()[0]

    wr = (100.0 * wins / n_closed) if n_closed else 0
    days_since = None
    if last_trade:
        try:
            d = datetime.fromisoformat(last_trade.replace('Z',''))
            days_since = (datetime.now() - d.replace(tzinfo=None)).days
        except Exception: pass

    return {
        'sid': sid,
        'thesis': (meta.get('thesis') or '')[:300],
        'tickers': (meta.get('tickers') or [])[:8],
        'status': meta.get('status'),
        'n_lifetime': n_lifetime,
        'n_closed': n_closed,
        'wins': wins,
        'wr_pct': round(wr, 1),
        'pnl_eur': round(pnl, 2),
        'n_30d': n_30d,
        'days_since_last_trade': days_since,
    }


def _macro_context(c: sqlite3.Connection) -> str:
    try:
        directive = {}
        if DIRECTIVE_FILE.exists():
            directive = json.loads(DIRECTIVE_FILE.read_text(encoding='utf-8'))
        events = c.execute(
            "SELECT event_type, magnitude, summary FROM macro_events "
            "WHERE substr(detected_at,1,10) >= date('now','-7 days') "
            "ORDER BY detected_at DESC LIMIT 6"
        ).fetchall()
        ev_str = '; '.join(f'{r[0]}({r[1]:.1f}): {(r[2] or "")[:60]}' for r in events)
        return (f"CEO Directive: {directive.get('mode','?')} ({directive.get('reason','?')[:80]}). "
                f"Macro 7d: {ev_str or 'ruhig'}")
    except Exception as e:
        return f'macro context err: {e}'


REVIEW_SYSTEM = """Du bist Albert, der TradeMind-CEO. Bewerte jede Strategie nuechtern auf Lebensfaehigkeit.

Kriterien:
- Hat sie eine echte Edge gezeigt (n>=3 closed, PnL positiv, WR>40%)?
- Ist die These im aktuellen Macro-Kontext noch relevant?
- Wurde sie kuerzlich (30d) aktiv getradet?
- Ist die Ticker-Liste sauber und passt zur These?

Entscheide: KEEP / WATCH / RETIRE
- KEEP: relevante These, Daten ok ODER plausibel ohne Daten weil Macro passt
- WATCH: grenzwertig, beobachten 30d
- RETIRE: tote These, schlechte PnL, oder veraltet

Antworte ausschliesslich mit JSON: {"decision": "KEEP|WATCH|RETIRE", "reason": "max 80 char"}"""


def _review_one(s: dict, macro: str) -> dict:
    """Ruft LLM fuer eine Strategie. Faellt zurueck auf Heuristik bei Fehler."""
    prompt = (
        f"Strategie: {s['sid']}\n"
        f"Status: {s['status']}\n"
        f"Thesis: {s['thesis']}\n"
        f"Tickers: {', '.join(s['tickers']) if s['tickers'] else '(leer!)'}\n"
        f"Stats: lifetime={s['n_lifetime']} trades, closed={s['n_closed']}, "
        f"wins={s['wins']}, WR={s['wr_pct']}%, PnL={s['pnl_eur']:+.0f}EUR, "
        f"30d={s['n_30d']}, days_since_last={s['days_since_last_trade']}\n"
        f"Macro: {macro}\n\n"
        f"Antwort als JSON."
    )
    try:
        from core.llm_client import call_llm
        text, meta = call_llm(prompt, model_hint='sonnet',
                              max_tokens=200, system=REVIEW_SYSTEM)
        # Parse JSON aus text
        import re
        m = re.search(r'\{[^}]*"decision"[^}]*\}', text, re.S)
        if m:
            j = json.loads(m.group(0))
            return {'decision': j.get('decision','WATCH').upper(),
                    'reason': j.get('reason','')[:120],
                    'source': 'llm'}
    except Exception as e:
        pass

    # Heuristik-Fallback
    if s['n_lifetime'] == 0 and (s['days_since_last_trade'] or 999) > 60:
        return {'decision': 'RETIRE', 'reason': 'No lifetime trades, 60d cold', 'source': 'heuristic'}
    if s['n_closed'] >= 3 and s['pnl_eur'] < 0:
        return {'decision': 'RETIRE', 'reason': f'PnL {s["pnl_eur"]:+.0f}€ over {s["n_closed"]} closed', 'source': 'heuristic'}
    if s['n_closed'] >= 3 and s['wr_pct'] >= 50 and s['pnl_eur'] > 0:
        return {'decision': 'KEEP', 'reason': f'WR {s["wr_pct"]}%, PnL {s["pnl_eur"]:+.0f}€', 'source': 'heuristic'}
    return {'decision': 'WATCH', 'reason': 'insufficient data', 'source': 'heuristic'}


def run(dry_run: bool = False, limit: int | None = None) -> dict:
    strats = json.loads(STRATS_FILE.read_text(encoding='utf-8'))
    c = sqlite3.connect(str(DB))

    candidates = []
    for sid, meta in strats.items():
        if not isinstance(meta, dict): continue
        if sid in PERMANENT_BLOCKED: continue
        if meta.get('status') not in LIVE_STATUS: continue
        candidates.append(_gather_strategy_data(sid, meta, c))

    if limit: candidates = candidates[:limit]
    macro = _macro_context(c)
    c.close()

    print(f'[review] {len(candidates)} strategies to review')
    print(f'[review] macro: {macro[:120]}')

    reviews = []
    for i, s in enumerate(candidates, 1):
        r = _review_one(s, macro)
        r['sid'] = s['sid']
        r['stats'] = {'n': s['n_lifetime'], 'pnl': s['pnl_eur'],
                       'wr': s['wr_pct'], '30d': s['n_30d']}
        reviews.append(r)
        print(f'  [{i:>2}/{len(candidates)}] {s["sid"]:<14} → {r["decision"]:<7} '
              f'({r["source"]}) {r["reason"][:70]}')

    by_dec = {'KEEP':0, 'WATCH':0, 'RETIRE':0}
    for r in reviews: by_dec[r['decision']] = by_dec.get(r['decision'],0)+1

    if not dry_run:
        # Apply: RETIRE → status='retired', WATCH → status='watching', KEEP → status='active'
        today = datetime.now().strftime('%Y-%m-%d')
        for r in reviews:
            sid = r['sid']
            if sid not in strats: continue
            if r['decision'] == 'RETIRE':
                strats[sid]['status'] = 'retired'
            elif r['decision'] == 'WATCH':
                strats[sid]['status'] = 'watching'
            else:  # KEEP
                strats[sid]['status'] = 'active'
            strats[sid]['_ceo_review_at'] = _now()
            strats[sid]['_ceo_review_reason'] = r['reason']
            strats[sid].setdefault('genesis', {}).setdefault('feedback_history', []).append({
                'date': today, 'action': f'ceo_review_{r["decision"].lower()}',
                'reason': r['reason'], 'source': r.get('source','llm'),
            })
        STRATS_FILE.write_text(json.dumps(strats, indent=2, ensure_ascii=False),
                                encoding='utf-8')

        REVIEW_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(REVIEW_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': _now(), 'reviews': reviews},
                                ensure_ascii=False) + '\n')

        # Discord-Push (post-fact)
        try:
            from discord_dispatcher import send_alert, TIER_LOW
            msg = (f'🧠 **CEO Strategy Review** ({len(reviews)} reviewed)\n'
                   f'KEEP: {by_dec["KEEP"]} | WATCH: {by_dec["WATCH"]} | RETIRE: {by_dec["RETIRE"]}\n')
            ret = [r for r in reviews if r['decision']=='RETIRE'][:10]
            if ret:
                msg += '\nRetired:\n' + '\n'.join(f"  · `{r['sid']}` — {r['reason'][:60]}" for r in ret)
            send_alert(msg, tier=TIER_LOW, category='ceo_strategy_review',
                       dedupe_key=f'ceo_review_{today}')
        except Exception: pass

    return {'ts': _now(), 'reviewed': len(reviews), 'by_decision': by_dec,
            'reviews': reviews, 'dry_run': dry_run}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=None)
    args = ap.parse_args()
    r = run(dry_run=args.dry_run, limit=args.limit)
    print()
    print(f'═══ Review @ {r["ts"][:16]} ═══')
    print(f'  Reviewed: {r["reviewed"]}')
    print(f'  By decision: {r["by_decision"]}')
    if r['dry_run']:
        print('  [DRY RUN]')


if __name__ == '__main__':
    main()
