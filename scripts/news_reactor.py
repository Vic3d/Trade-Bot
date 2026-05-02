#!/usr/bin/env python3
"""
news_reactor.py — Phase 44t: Continuous News-to-Action-Bridge.

Schliesst die Luecke: News landen in DB, aber niemand verbindet sie mit
offenen Positionen. Dieser Job laeuft alle 15min und macht das.

Pipeline:
1. Lade neue news_events seit letztem Run (state-tracked)
2. PLUS Live-Pull: Bloomberg/Reuters/Finnhub fuer offene Tickers
3. Filter: relevant fuer offene Positionen ODER aktive Strategien?
   (matching: ticker explizit erwaehnt, ODER Sektor-Keyword, ODER Strategy-Thema)
4. Pro relevanten News: LLM bewertet Impact (HOLD/WATCH/REVIEW_STOP/EXIT_NOW)
5. Bei REVIEW_STOP/EXIT_NOW → Notification + Discord-Push
6. Smart-Throttle: max 1 LLM-Call pro Ticker pro Stunde (cost control)

Output:
  data/news_reactor_state.json    (last_seen_news_ids, last_eval_per_ticker)
  data/news_reactor_log.jsonl     (Audit alle Bewertungen)
  data/macro_position_notifications.jsonl (re-uses existing pipeline)
  Discord-Push bei HIGH-Impact

Run: python3 scripts/news_reactor.py
"""
from __future__ import annotations
import json, os, re, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
STATE = WS / 'data' / 'news_reactor_state.json'
LOG = WS / 'data' / 'news_reactor_log.jsonl'
NOTIF = WS / 'data' / 'macro_position_notifications.jsonl'

THROTTLE_SECONDS = 3600   # max 1 Bewertung pro Ticker pro Stunde
MAX_LLM_CALLS_PER_RUN = 8  # Cost-Cap pro Run


SYSTEM = """Du bist Albert. Bewerte ein einzelnes News-Item bezogen auf eine
KONKRETE offene Position. Sei nuechtern, ehrlich, kein Hype.

Optionen:
  HOLD          = News ist irrelevant ODER staerkt These — keine Aktion
  WATCH         = News ist beachtenswert — Stop pruefen wenn naechster macro_review
  REVIEW_STOP   = News widerspricht These materiell — Stop sollte ueberdacht werden
  EXIT_NOW      = These materiell invalidiert — sofortiger Exit-Vorschlag

Antworte ausschliesslich mit JSON:
{"impact": "HOLD|WATCH|REVIEW_STOP|EXIT_NOW",
 "reason": "max 200 char",
 "confidence": 0.0-1.0}"""


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding='utf-8'))
    return {'last_seen_news_id': 0, 'last_eval_per_ticker': {}}


def _save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2), encoding='utf-8')


def _load_open_positions() -> list[dict]:
    if not DB.exists(): return []
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, ticker, strategy, entry_price, stop_price, target_price "
        "FROM paper_portfolio WHERE status='OPEN'"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def _load_active_strategies() -> dict[str, dict]:
    sf = WS / 'data' / 'strategies.json'
    if not sf.exists(): return {}
    d = json.loads(sf.read_text(encoding='utf-8'))
    out = {}
    for sid, s in d.items():
        if isinstance(s, dict) and s.get('status') == 'active':
            out[sid] = {
                'thesis': s.get('thesis', ''),
                'tickers': s.get('tickers', []),
            }
    return out


def _ticker_relevance(headline: str, ticker: str) -> bool:
    """Matcht Ticker explizit ODER Firmen-Synonym im Headline."""
    h = headline.lower()
    t = ticker.lower()
    if t in h: return True
    # Bekannte Synonyme
    synonyms = {
        'mos': ['mosaic'],
        'paas': ['pan american silver'],
        'eqnr.ol': ['equinor'],
        'tte.pa': ['totalenergies', 'total energies'],
        'bayn.de': ['bayer'],
        'pypl': ['paypal'],
        'rhm.de': ['rheinmetall'],
        'nvo': ['novo nordisk'],
    }
    for s in synonyms.get(t, []):
        if s in h: return True
    return False


def _strategy_relevance(headline: str, strat: dict) -> bool:
    """Matcht Strategy-Thesis-Keywords im Headline."""
    h = headline.lower()
    thesis = strat.get('thesis', '').lower()
    # Extrahiere markante Wörter aus Thesis (>=4 Buchstaben, keine Stoppwörter)
    stops = {'fuer', 'durch', 'mit', 'sind', 'wird', 'kann', 'auch'}
    words = [w for w in re.findall(r'[a-zäöü]{5,}', thesis)
             if w not in stops][:5]
    for w in words:
        if w in h: return True
    return False


def _fetch_new_news(state: dict, hours: int = 4) -> list[dict]:
    """DB: news_events seit letzter ID; PLUS Live-Pull pro Open-Ticker."""
    out = []
    seen_ids = set()

    # 1. DB seit letzter ID
    if DB.exists():
        try:
            c = sqlite3.connect(str(DB))
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT id, headline, source, created_at FROM news_events "
                "WHERE id > ? AND created_at >= datetime('now','-{}h') "
                "ORDER BY id ASC LIMIT 200".format(hours),
                (state.get('last_seen_news_id', 0),)
            ).fetchall()
            c.close()
            for r in rows:
                out.append({'id': r['id'], 'headline': r['headline'],
                             'source': r['source'], 'date': r['created_at'],
                             'origin': 'db'})
                seen_ids.add(r['id'])
        except Exception as e:
            print(f'[news_reactor] db err: {e}')

    # 2. Live-Pull pro Open-Ticker (Finnhub)
    try:
        from news_fetcher import finnhub_company
        positions = _load_open_positions()
        for p in positions[:5]:  # cap auf 5 tickers
            tk = p['ticker']
            for n in finnhub_company(tk, days_back=1, n=4) or []:
                hl = n.get('title') or ''
                key = hl[:80].lower()
                if not hl or key in [x['headline'][:80].lower() for x in out]:
                    continue
                out.append({'id': f'fh_{tk}_{abs(hash(hl))%99999}',
                             'headline': hl,
                             'source': f'Finnhub/{tk}',
                             'date': n.get('date', ''),
                             'origin': 'finnhub_live'})
    except Exception as e:
        print(f'[news_reactor] finnhub err: {e}')

    # 3. Live-Pull Bloomberg fuer offene Sektoren
    try:
        from news_fetcher import bloomberg, reuters
        for n in bloomberg(['markets', 'energy'], n=4, max_age_hours=4) or []:
            hl = n.get('title') or ''
            key = hl[:80].lower()
            if not hl or key in [x['headline'][:80].lower() for x in out]: continue
            out.append({'id': f'bb_{abs(hash(hl))%99999}',
                         'headline': hl, 'source': n.get('source','Bloomberg'),
                         'date': n.get('date',''), 'origin': 'bloomberg_live'})
        for n in reuters(['markets','energy'], n=3, max_age_hours=4) or []:
            hl = n.get('title') or ''
            key = hl[:80].lower()
            if not hl or key in [x['headline'][:80].lower() for x in out]: continue
            out.append({'id': f'rt_{abs(hash(hl))%99999}',
                         'headline': hl, 'source': n.get('source','Reuters'),
                         'date': n.get('date',''), 'origin': 'reuters_live'})
    except Exception: pass

    # Update state mit max DB-id
    if seen_ids:
        state['last_seen_news_id'] = max(seen_ids)
    return out


def _evaluate_news_position(news: dict, position: dict) -> dict:
    prompt = (
        f"Position: {position['ticker']} (Strategie {position['strategy']})\n"
        f"  Entry: {position['entry_price']}\n"
        f"  Stop:  {position['stop_price']}\n"
        f"  Target: {position['target_price']}\n\n"
        f"News-Item:\n"
        f"  [{news.get('source','?')}] {news.get('headline','')}\n\n"
        f"Bewertung als JSON."
    )
    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=200, system=SYSTEM)
        m = re.search(r'\{.*\}', text, re.S)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        return {'impact': 'HOLD', 'reason': f'LLM-fail: {e}', 'confidence': 0.0}
    return {'impact': 'HOLD', 'reason': 'no parse', 'confidence': 0.0}


def _can_eval_now(state: dict, ticker: str) -> bool:
    """Throttle: max 1 LLM-call pro ticker pro THROTTLE_SECONDS."""
    last = state.get('last_eval_per_ticker', {}).get(ticker)
    if not last: return True
    try:
        last_dt = datetime.fromisoformat(last.replace('Z','+00:00'))
        return (datetime.now(timezone.utc) - last_dt).total_seconds() >= THROTTLE_SECONDS
    except Exception:
        return True


def _record_eval(state: dict, ticker: str) -> None:
    state.setdefault('last_eval_per_ticker', {})[ticker] = _now()


def _write_notification(news: dict, position: dict, eval_result: dict) -> None:
    """Schreibt in macro_position_notifications.jsonl — re-use existing pipeline."""
    NOTIF.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        'ts': _now(),
        'trade_id': position['id'], 'ticker': position['ticker'],
        'strategy': position['strategy'],
        'event_type': 'NEWS_REACTOR',
        'entry_price': position['entry_price'],
        'live_price': None,  # wird vom macro_stop_review geupdated
        'unrealized_pct': None,
        'current_stop': position['stop_price'],
        'stop_distance_pct': None,
        'recommendation': eval_result.get('impact', 'HOLD'),
        'reason': eval_result.get('reason', ''),
        'news': {'headline': news.get('headline'), 'source': news.get('source')},
    }
    with open(NOTIF, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def run() -> dict:
    state = _load_state()
    positions = _load_open_positions()
    if not positions:
        return {'ts': _now(), 'note': 'no_open_positions', 'evaluated': 0}

    strats = _load_active_strategies()
    new_news = _fetch_new_news(state, hours=4)
    if not new_news:
        _save_state(state)
        return {'ts': _now(), 'note': 'no_new_news', 'evaluated': 0}

    # Match news to positions
    relevances = []  # list of (news, position)
    for n in new_news:
        for p in positions:
            if _ticker_relevance(n['headline'], p['ticker']):
                relevances.append((n, p, 'ticker_match'))
                continue
            # Strategy-thema match (sekundär)
            strat = strats.get(p['strategy'])
            if strat and _strategy_relevance(n['headline'], strat):
                relevances.append((n, p, 'strategy_match'))

    # Throttle + Cost-Cap
    eval_count = 0
    results = []
    pushed = []
    for news, pos, match_type in relevances:
        if eval_count >= MAX_LLM_CALLS_PER_RUN: break
        if not _can_eval_now(state, pos['ticker']):
            continue
        ev = _evaluate_news_position(news, pos)
        eval_count += 1
        _record_eval(state, pos['ticker'])
        rec = {'ts': _now(), 'ticker': pos['ticker'], 'match': match_type,
               'news': news.get('headline','')[:200],
               'source': news.get('source'), 'eval': ev}
        results.append(rec)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        if ev.get('impact') in ('REVIEW_STOP', 'EXIT_NOW'):
            _write_notification(news, pos, ev)
            pushed.append(rec)

    _save_state(state)

    # Discord-Push fuer pushed
    if pushed:
        try:
            from discord_dispatcher import send_alert, TIER_HIGH
            lines = [f'📰 **News-Reactor** — {len(pushed)} Position(en) brauchen Review:\n']
            for p in pushed[:5]:
                icon = '🚨' if p['eval'].get('impact') == 'EXIT_NOW' else '⚠️'
                lines.append(f"{icon} **{p['ticker']}** ({p['eval'].get('impact')}, "
                              f"conf {p['eval'].get('confidence',0):.0%})")
                lines.append(f"   📰 {p['news'][:130]}")
                lines.append(f"   → {p['eval'].get('reason','')[:140]}\n")
            send_alert('\n'.join(lines)[:1900], tier=TIER_HIGH,
                        category='news_reactor')
        except Exception as e: print(f'discord push err: {e}')

    return {
        'ts': _now(), 'new_news': len(new_news),
        'relevant': len(relevances), 'evaluated': eval_count,
        'pushed': len(pushed),
    }


def main() -> int:
    r = run()
    print(f'═══ News-Reactor @ {r.get("ts","")[:16]} ═══')
    print(f'  New news: {r.get("new_news",0)}, Relevant: {r.get("relevant",0)}, '
          f'Evaluated: {r.get("evaluated",0)}, Pushed: {r.get("pushed",0)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
