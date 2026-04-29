#!/usr/bin/env python3
"""
ceo_active_hunter.py — Phase 43 Pillar 2: Active Setup-Generierung.

Statt passiv auf Auto-Scanner zu warten, denkt Albert selbst:
  · Was sind die wichtigsten Macro-Themes gerade? (VIX, Geo, Sektor-Heatmap)
  · Welche News-Events der letzten 60min sind tradable?
  · Welche Open-Positions haben Yellow-Flags?
  · Welche aktiven Strategien sind in ihrer best_hour?

Output: bis zu N neue Proposals (source='ceo_active') in proposals.json,
die durch normale Guards laufen.

Usage:
  from ceo_active_hunter import hunt_for_setups
  new_props = hunt_for_setups(max_new=3)

CLI:
  python3 scripts/ceo_active_hunter.py [--max 3] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB              = WS / 'data' / 'trading.db'
PROPOSALS_FILE  = WS / 'data' / 'proposals.json'
DIRECTIVE_FILE  = WS / 'data' / 'ceo_directive.json'
STRATEGIES_FILE = WS / 'data' / 'strategies.json'

# ═══════════════════════════════════════════════════════════════════════════
# Context-Sammler
# ═══════════════════════════════════════════════════════════════════════════

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def gather_hunting_context() -> dict:
    """Sammelt allen Kontext für aktive Setup-Suche."""
    ctx = {
        'ts': _now_iso(),
        'directive': _load_json(DIRECTIVE_FILE, {}),
        'open_positions': [],
        'open_position_tickers': [],
        'recent_news': [],
        'recent_macro_events': [],
        'active_strategies': [],
        'sector_exposure': {},
        'cash_eur': 0.0,
        'fund_value': 25000,
        'open_count': 0,
        'today_already_opened': 0,
    }

    # 1. Open Positions
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        opens = c.execute("""
            SELECT ticker, strategy, entry_price, shares, stop_price,
                   target_price, entry_date, sector
            FROM paper_portfolio WHERE status='OPEN'
        """).fetchall()
        ctx['open_positions'] = [dict(r) for r in opens]
        ctx['open_position_tickers'] = [r['ticker'] for r in opens]
        ctx['open_count'] = len(opens)

        # Cash
        cash_row = c.execute(
            "SELECT value FROM paper_fund WHERE key='current_cash'"
        ).fetchone()
        if cash_row:
            ctx['cash_eur'] = float(cash_row[0])

        # Today's openings
        today = datetime.now().strftime('%Y-%m-%d')
        n_today = c.execute(
            "SELECT COUNT(*) FROM paper_portfolio "
            "WHERE entry_date LIKE ?", (f'{today}%',)
        ).fetchone()[0]
        ctx['today_already_opened'] = n_today

        # 2. News last 60min
        cutoff = (datetime.utcnow() - timedelta(minutes=60)).strftime('%Y-%m-%d %H:%M:%S')
        news = c.execute("""
            SELECT headline, source, sector, sentiment_label, relevance_score, tickers
            FROM news_events
            WHERE created_at >= ?
            ORDER BY relevance_score DESC, created_at DESC
            LIMIT 30
        """, (cutoff,)).fetchall()
        ctx['recent_news'] = [dict(n) for n in news]

        # 3. Macro Events last 6h
        try:
            macro = c.execute("""
                SELECT event_type, severity, impact_tickers, detected_at
                FROM macro_events
                WHERE detected_at >= ?
                ORDER BY severity DESC, detected_at DESC
                LIMIT 10
            """, ((datetime.utcnow() - timedelta(hours=6)).isoformat(),)).fetchall()
            ctx['recent_macro_events'] = [dict(m) for m in macro]
        except Exception:
            pass

        c.close()
    except Exception as e:
        print(f'[hunter] DB error: {e}', file=sys.stderr)

    # 4. Active Strategies
    strats = _load_json(STRATEGIES_FILE, {})
    if isinstance(strats, dict):
        for sid, s in strats.items():
            if not isinstance(s, dict):
                continue
            if s.get('status') != 'active':
                continue
            if s.get('_lifecycle_state') in ('SUSPENDED', 'RETIRED'):
                continue
            ctx['active_strategies'].append({
                'id': sid,
                'name': s.get('name', ''),
                'thesis': str(s.get('thesis', ''))[:160],
                'tickers': s.get('tickers', [])[:8],
                'sector': s.get('sector', ''),
                'health': s.get('health', 'unknown'),
                'lifecycle_state': s.get('_lifecycle_state', 'ACTIVE'),
                'win_rate': s.get('performance', {}).get('win_rate'),
                'expectancy': s.get('performance', {}).get('expectancy'),
            })

    # 5. Sector Exposure
    try:
        from portfolio_risk import get_exposure_breakdown
        b = get_exposure_breakdown()
        ctx['sector_exposure'] = b.get('by_sector', {})
    except Exception:
        pass

    return ctx


# ═══════════════════════════════════════════════════════════════════════════
# LLM-Hunter
# ═══════════════════════════════════════════════════════════════════════════

HUNTER_PROMPT_TEMPLATE = """Du bist Albert, autonomer CEO-Brain (Phase 43 Active-Hunter).
Es gibt KEINE pending Proposals, der Markt ist offen, und du sollst SELBST
Setups finden. Sei pragmatisch, nicht spekulativ — qualität > quantität.

═══ AKTUELLER STATE ═══
Mode: {mode} | VIX: {vix} | Geo: {geo}
Cash: {cash:.0f}EUR ({cash_pct:.0f}% vom Fund)
Open Positions: {n_open} ({open_tickers})
Heute schon eröffnet: {n_today} (max 7/Woche!)

Sektor-Exposure:
{sector_exposure_str}

═══ MACRO-EVENTS LETZTE 6H ═══
{macro_events_str}

═══ NEWS LETZTE 60min (top 10 nach Relevance) ═══
{news_str}

═══ AKTIVE STRATEGIEN ({n_active}) ═══
{strategies_str}

═══ DEINE AUFGABE ═══
Finde bis zu {max_new} hochwertige Setups die JETZT Sinn machen.
Beachte:
  · KEINE Duplikate zu Open-Positions ({open_tickers})
  · KEINE Strategien in SUSPENDED/RETIRED-State
  · KEINE Sektor-Cluster über 25%
  · Setup MUSS auf konkreter News, Macro-Event oder Strategy-Match basieren
  · Wenn nichts überzeugend: lieber 0 Setups als Schrott!

ANTWORT-FORMAT — STRIKT JSON:
{{
  "thinking": "1-3 Sätze: was siehst du gerade am Markt?",
  "setups": [
    {{
      "ticker": "XOM",
      "strategy": "PS5",
      "entry_price": 0,        // 0 = current market
      "stop_pct": 4,           // % unter entry (Phase 44b: war 6, enger für besseres R:R)
      "target_pct": 12,        // % über entry (3:1 R:R)
      "thesis": "1-2 Sätze warum jetzt",
      "trigger": "macro_event|news|strategy_match|technical",
      "trigger_ref": "Welches Event/News/Strategy macht das Setup",
      "confidence": 0.65,      // 0.0-1.0
      "size_eur": 1000         // 500-1500
    }}
  ]
}}

Keine setups = setups: []. Nur reines JSON, kein Markdown."""


def _build_hunter_prompt(ctx: dict, max_new: int = 3) -> str:
    directive = ctx['directive']
    cash_pct = (ctx['cash_eur'] / ctx['fund_value'] * 100) if ctx['fund_value'] else 0

    # Sektor-Exposure
    sec_lines = [f"  {k}: {v.get('pct', 0):.1f}%" for k, v in ctx['sector_exposure'].items()][:8]
    sector_exp_str = '\n'.join(sec_lines) or '  (none)'

    # Macro Events
    if ctx['recent_macro_events']:
        macro_lines = []
        for m in ctx['recent_macro_events'][:5]:
            macro_lines.append(
                f"  · [{m.get('severity', '?')}] {m.get('event_type', '?')} "
                f"({m.get('detected_at', '')[:16]}) → impact: {m.get('impact_tickers', '?')[:80]}"
            )
        macro_str = '\n'.join(macro_lines)
    else:
        macro_str = '  (keine in letzten 6h)'

    # News
    if ctx['recent_news']:
        news_lines = []
        for n in ctx['recent_news'][:10]:
            tickers = (n.get('tickers') or '').strip('[]"')[:30]
            sector = n.get('sector') or '?'
            sentiment = n.get('sentiment_label', '?')
            news_lines.append(
                f"  · [{sector}|{sentiment}|rel={n.get('relevance_score', 0):.1f}] "
                f"{n.get('headline', '')[:120]} "
                f"({n.get('source', '?')[:15]}) {tickers}"
            )
        news_str = '\n'.join(news_lines)
    else:
        news_str = '  (keine in letzten 60min)'

    # Strategies
    if ctx['active_strategies']:
        strat_lines = []
        for s in ctx['active_strategies'][:15]:
            wr = s.get('win_rate')
            wr_str = f"WR={wr*100:.0f}%" if wr is not None else "WR=?"
            exp_str = f"exp={s.get('expectancy', '?')}%" if s.get('expectancy') is not None else ""
            strat_lines.append(
                f"  · {s['id']:<10} [{s['lifecycle_state']:<10}] {wr_str} {exp_str} | "
                f"{s['name'][:30]} | tickers: {s['tickers']}"
            )
        strat_str = '\n'.join(strat_lines)
    else:
        strat_str = '  (keine)'

    return HUNTER_PROMPT_TEMPLATE.format(
        mode=directive.get('mode', '?'),
        vix=directive.get('vix', '?'),
        geo=directive.get('geo_alert_level', '?'),
        cash=ctx['cash_eur'],
        cash_pct=cash_pct,
        n_open=ctx['open_count'],
        open_tickers=', '.join(ctx['open_position_tickers'][:10]) or 'none',
        n_today=ctx['today_already_opened'],
        sector_exposure_str=sector_exp_str,
        macro_events_str=macro_str,
        news_str=news_str,
        n_active=len(ctx['active_strategies']),
        strategies_str=strat_str,
        max_new=max_new,
    )


def call_hunter_llm(prompt: str, model_hint: str = 'sonnet',
                     max_tokens: int = 1800) -> dict | None:
    """Calls LLM, parses JSON. Returns None on failure."""
    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint=model_hint, max_tokens=max_tokens)
    except Exception as e:
        print(f'[hunter] LLM call failed: {e}', file=sys.stderr)
        return None

    text = (text or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text
        if text.endswith('```'):
            text = text.rsplit('```', 1)[0]
    i, j = text.find('{'), text.rfind('}')
    if i < 0 or j < 0:
        print(f'[hunter] no JSON in response: {text[:200]}', file=sys.stderr)
        return None
    try:
        return json.loads(text[i:j+1])
    except Exception as e:
        print(f'[hunter] JSON parse error: {e}', file=sys.stderr)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Setup → Proposal Translator
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_live_price(ticker: str) -> float:
    """Phase 43f-fix: live_data ZUERST (EUR-konvertiert!). prices-Tabelle nur
    als Fallback — sie hat Original-Currency (z.B. EQNR.OL in NOK), was zu
    FX-Sanity-Blocks führt.

    Reihenfolge:
      1. core.live_data.get_price_eur (EUR-konvertiert für alle Märkte)
      2. paper_portfolio close_price (war auch EUR)
      3. prices-Tabelle als letzter Fallback (US-Tickers nur — dort = USD ≈ EUR)
    """
    # 1. live_data (EUR-konvertiert) — primärer Pfad
    try:
        from core.live_data import get_price_eur
        p = get_price_eur(ticker)
        if p and float(p) > 0:
            return float(p)
    except Exception:
        pass
    # 2. paper_portfolio close (auch EUR)
    try:
        c = sqlite3.connect(str(DB))
        row = c.execute(
            "SELECT close_price FROM paper_portfolio WHERE ticker=? "
            "AND close_price IS NOT NULL ORDER BY id DESC LIMIT 1",
            (ticker,)
        ).fetchone()
        c.close()
        if row and row[0]:
            return float(row[0])
    except Exception:
        pass
    # 3. prices-Tabelle (Original-Currency) — NUR für US-Tickers safe
    if '.' not in ticker:  # kein Suffix = vermutlich US-Ticker (USD ≈ EUR-Range)
        try:
            c = sqlite3.connect(str(DB))
            row = c.execute(
                "SELECT close FROM prices WHERE ticker=? "
                "ORDER BY date DESC LIMIT 1", (ticker,)
            ).fetchone()
            c.close()
            if row and row[0]:
                return float(row[0])
        except Exception:
            pass
    return 0.0


def _strategy_quality_check(strategy_id: str) -> tuple[bool, str]:
    """Phase 44b/Fix-4: Quality-Gate vor Proposal-Erzeugung.

    Erlaubt nur Strategien die entweder:
      · n >= 3 lifetime Trades haben (= existieren wirklich)
      · ODER explizit als 'experimental' markiert sind in strategies.json

    Verhindert dass Hunter Setups für 36 NEVER_TRADED-Strategien erzeugt
    die dann durch Guards abgelehnt werden (verifiziert: 0% Conversion).

    Returns: (is_quality, reason_if_not)
    """
    try:
        c = sqlite3.connect(str(DB))
        n = c.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE strategy=?",
            (strategy_id,)
        ).fetchone()[0]
        c.close()
        if n >= 3:
            return True, ''
        # Check experimental-Marker in strategies.json
        sf = WS / 'data' / 'strategies.json'
        if sf.exists():
            try:
                strats = json.loads(sf.read_text(encoding='utf-8'))
                meta = strats.get(strategy_id, {})
                if isinstance(meta, dict) and meta.get('experimental'):
                    return True, ''
            except Exception:
                pass
        return False, f'strategy_quality: n={n} (<3 lifetime trades, nicht experimental)'
    except Exception:
        return True, ''  # bei Fehler: nicht blockieren (defensiv)


def setups_to_proposals(setups: list[dict], thinking: str = '') -> list[dict]:
    """Konvertiere Hunter-Setups in proposals.json Format."""
    proposals = []
    now = _now_iso()
    for s in setups:
        if not isinstance(s, dict):
            continue
        ticker = s.get('ticker')
        strategy = s.get('strategy')
        if not ticker or not strategy:
            continue
        # Phase 44b/Fix-4: Strategy-Quality-Gate
        ok, reason = _strategy_quality_check(strategy)
        if not ok:
            print(f'[hunter] skip {ticker}/{strategy}: {reason}', file=sys.stderr)
            continue
        entry = float(s.get('entry_price') or 0)
        # Phase 44b: Default 4% / 12% = 3:1 R:R (PTJ-Style)
        stop_pct = float(s.get('stop_pct') or 4)
        target_pct = float(s.get('target_pct') or 12)
        # Phase 43-fix: wenn entry=0, hole Live-Preis aus DB
        if entry <= 0:
            entry = _resolve_live_price(ticker)
            if entry <= 0:
                print(f'[hunter] skip {ticker}: kein Live-Preis verfügbar', file=sys.stderr)
                continue
        stop_price = round(entry * (1 - stop_pct / 100), 2)
        target_price = round(entry * (1 + target_pct / 100), 2)
        proposals.append({
            'id': f"ceo_{uuid.uuid4().hex[:10]}",
            'ticker': ticker,
            'strategy': strategy,
            'entry_price': round(entry, 2),
            'stop_price': stop_price,
            'target_price': target_price,
            # Phase 43-fix: ceo_brain.py liest 'stop' und 'target' (nicht stop_price/target_price)
            'stop': stop_price,
            'target': target_price,
            'target_1': target_price,
            'stop_pct': stop_pct,
            'target_pct': target_pct,
            'thesis': str(s.get('thesis', ''))[:300],
            'trigger': s.get('trigger', 'ceo_active'),
            'trigger_ref': str(s.get('trigger_ref', ''))[:200],
            'confidence': float(s.get('confidence') or 0.5),
            'size_eur': float(s.get('size_eur') or 1000),
            'sector': s.get('sector', ''),
            'source': 'ceo_active',
            'status': 'pending',
            'created_at': now,
            'expires_at': (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            'ceo_thinking': thinking[:500],
        })
    return proposals


def append_to_proposals_file(new_proposals: list[dict]) -> int:
    """Append new proposals to proposals.json, dedup by ticker+strategy+24h."""
    if not new_proposals:
        return 0
    existing = _load_json(PROPOSALS_FILE, [])
    if isinstance(existing, dict):
        meta = {k: v for k, v in existing.items() if k != 'proposals'}
        existing = existing.get('proposals', [])
    else:
        meta = {}
    if not isinstance(existing, list):
        existing = []

    # Dedup: gleicher ticker+strategy in letzten 24h pending → skip
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    seen_keys = set()
    for p in existing:
        if not isinstance(p, dict):
            continue
        if p.get('status') in ('pending', 'active') and p.get('created_at', '') > cutoff:
            seen_keys.add(f"{p.get('ticker', '')}|{p.get('strategy', '')}")

    added = 0
    for np in new_proposals:
        key = f"{np['ticker']}|{np['strategy']}"
        if key in seen_keys:
            continue
        existing.append(np)
        seen_keys.add(key)
        added += 1

    # Save (mit meta wenn original ein dict war)
    out = {**meta, 'proposals': existing} if meta else existing
    PROPOSALS_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                               encoding='utf-8')
    return added


# ═══════════════════════════════════════════════════════════════════════════
# Hauptfunktion
# ═══════════════════════════════════════════════════════════════════════════

def hunt_for_setups(max_new: int = 3, dry_run: bool = False) -> dict:
    """Volle Pipeline: Context → LLM → Proposals.

    Returns: {
      'context_summary': str, 'thinking': str, 'setups_proposed': int,
      'proposals_written': int, 'dry_run': bool, 'setups': [...]
    }
    """
    print(f'[hunter] gathering context...', file=sys.stderr)
    ctx = gather_hunting_context()
    summary = (
        f"directive={ctx['directive'].get('mode', '?')}, "
        f"open={ctx['open_count']}, news_60min={len(ctx['recent_news'])}, "
        f"macro_6h={len(ctx['recent_macro_events'])}, "
        f"active_strats={len(ctx['active_strategies'])}, "
        f"today_opened={ctx['today_already_opened']}"
    )
    print(f'[hunter] context: {summary}', file=sys.stderr)

    # Sanity-Guards: HALT wenn nichts zu sehen
    if (not ctx['recent_news'] and not ctx['recent_macro_events']
            and ctx['today_already_opened'] >= 7):
        print('[hunter] no triggers + week-cap reached → skip', file=sys.stderr)
        return {
            'context_summary': summary, 'thinking': '',
            'setups_proposed': 0, 'proposals_written': 0,
            'dry_run': dry_run, 'setups': [], 'skipped_reason': 'no_triggers'
        }

    prompt = _build_hunter_prompt(ctx, max_new=max_new)
    print(f'[hunter] prompt size: {len(prompt)} chars', file=sys.stderr)

    response = call_hunter_llm(prompt)
    if not response:
        return {
            'context_summary': summary, 'thinking': '',
            'setups_proposed': 0, 'proposals_written': 0,
            'dry_run': dry_run, 'setups': [], 'error': 'llm_failed'
        }

    thinking = str(response.get('thinking', ''))[:500]
    setups = response.get('setups', [])
    if not isinstance(setups, list):
        setups = []
    print(f'[hunter] thinking: {thinking[:150]}', file=sys.stderr)
    print(f'[hunter] setups proposed: {len(setups)}', file=sys.stderr)

    proposals = setups_to_proposals(setups, thinking=thinking)
    written = 0 if dry_run else append_to_proposals_file(proposals)

    return {
        'context_summary': summary,
        'thinking': thinking,
        'setups_proposed': len(setups),
        'proposals_written': written,
        'dry_run': dry_run,
        'setups': setups,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=3, help='Max neue Setups (default 3)')
    ap.add_argument('--dry-run', action='store_true', help='Nichts schreiben')
    args = ap.parse_args()

    print(f'═══ CEO Active Hunter @ {_now_iso()} ═══')
    result = hunt_for_setups(max_new=args.max, dry_run=args.dry_run)

    print(f'\nContext: {result["context_summary"]}')
    print(f'Thinking: {result["thinking"]}')
    print(f'Setups proposed: {result["setups_proposed"]}')
    print(f'Proposals written: {result["proposals_written"]} (dry_run={result["dry_run"]})')

    if result.get('error'):
        print(f'❌ Error: {result["error"]}')
        return 1

    if result['setups']:
        print('\n--- Setups ---')
        for s in result['setups']:
            print(f"  · {s.get('ticker', '?'):<8} {s.get('strategy', '?')} "
                  f"conf={s.get('confidence', '?')} "
                  f"trigger={s.get('trigger', '?')}")
            print(f"    thesis: {(s.get('thesis', '') or '')[:120]}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
