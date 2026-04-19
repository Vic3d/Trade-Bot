#!/usr/bin/env python3
"""
Auto Deep Dive — Phase 12
==========================

Rule-based automated Deep Dive that refreshes verdicts before Guard 0c2
(14-day cutoff) fires. No LLM calls → zero token cost.

Decision tree:
  1) Load thesis status + conviction score (Factor 1-4 from Phase 3)
  2) Apply Phase 10 (insider) + Phase 11 (macro) modifiers
  3) Check falling-knife + 52W-drawdown guardrails (Guard 0d logic)
  4) Emit one of: KAUFEN / WARTEN / NICHT_KAUFEN
  5) Write to data/deep_dive_verdicts.json with source='auto_deepdive_rule'
     (Phase 3: kennzeichnet regel-basierte Verdicts ehrlich, damit
      ENTRY-Gate in autonomous_ceo.py diese NICHT als echten 6-Schritt
      Deep Dive akzeptiert. WARTEN/NICHT_KAUFEN bleiben defensiv gültig.)
  6) Flip detection: verdict change triggers Discord alert

Runs nightly 02:30 CET. Covers:
  - All OPEN portfolio tickers (re-evaluate)
  - All strategies.json tickers (watchlist)
  - Any ticker with expiring verdict (age > 10 days)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')
from pathlib import Path

log = logging.getLogger('auto_deepdive')

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atomic_json import atomic_write_json

DATA = WS / 'data'
DB = DATA / 'trading.db'
STRATS = DATA / 'strategies.json'
VERDICTS_FILE = DATA / 'deep_dive_verdicts.json'
MACRO_FILE = DATA / 'macro_regime.json'
FLIP_LOG = DATA / 'auto_deepdive_flips.json'

# Guardrails
REFRESH_IF_AGE_DAYS = 5  # Phase 24 aggressive: 10→5 (häufigere Verdict-Refreshes)
KAUFEN_MIN_CONVICTION = 55
WARTEN_MIN_CONVICTION = 35


# ─────────── Helpers ───────────

def _load_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        log.warning(f'load {p.name} failed: {e}')
    return default


def _save_json(p: Path, data) -> None:
    try:
        atomic_write_json(p, data, ensure_ascii=True)
    except Exception as e:
        log.warning(f'save {p.name} failed: {e}')


def _latest_price(ticker: str) -> float | None:
    try:
        c = sqlite3.connect(str(DB))
        row = c.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        c.close()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _high_52w(ticker: str) -> float | None:
    try:
        c = sqlite3.connect(str(DB))
        row = c.execute(
            "SELECT MAX(high) FROM prices WHERE ticker=? "
            "AND date >= date('now', '-365 days')",
            (ticker,),
        ).fetchone()
        c.close()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _collect_tickers() -> set[str]:
    out: set[str] = set()
    # Portfolio
    try:
        c = sqlite3.connect(str(DB))
        rows = c.execute(
            "SELECT DISTINCT ticker FROM trades WHERE status='OPEN'"
        ).fetchall()
        for r in rows:
            if r[0]:
                out.add(str(r[0]).upper())
        c.close()
    except Exception as e:
        log.warning(f'portfolio fetch: {e}')

    # Strategies watchlist
    try:
        raw = _load_json(STRATS, {})
        for sid, cfg in raw.items():
            if not isinstance(cfg, dict):
                continue
            t = cfg.get('ticker')
            if t:
                out.add(str(t).upper())
    except Exception as e:
        log.warning(f'strategies fetch: {e}')

    # Expiring verdicts
    try:
        verdicts = _load_json(VERDICTS_FILE, {})
        for t in verdicts.keys():
            out.add(str(t).upper())
    except Exception:
        pass

    return out


def _strategy_for_ticker(ticker: str) -> str | None:
    """Finds best matching active strategy for a ticker."""
    strategies = _load_json(STRATS, {})
    for sid, cfg in strategies.items():
        if not isinstance(cfg, dict):
            continue
        if str(cfg.get('ticker', '')).upper() == ticker.upper():
            if cfg.get('status', 'active').lower() == 'active':
                return sid
    return None


# ─────────── Core Analysis ───────────

def _analyze_ticker(ticker: str) -> dict:
    """Runs the full 4-signal analysis for a ticker."""
    result: dict = {
        'ticker': ticker,
        'score': 0,
        'conviction': None,
        'insider_bias': None,
        'macro_bias': None,
        'thesis_status': 'unknown',
        'reasons': [],
        'verdict': 'WARTEN',
        'strategy': None,
    }

    price = _latest_price(ticker)
    if price is None:
        result['reasons'].append('no price data')
        result['verdict'] = 'WARTEN'
        return result

    strategy = _strategy_for_ticker(ticker)
    result['strategy'] = strategy

    # ── Signal 1: Conviction Score via scorer (if strategy present) ──
    conviction_score = None
    if strategy:
        try:
            from intelligence.conviction_scorer import calculate_conviction
            cv = calculate_conviction(
                ticker=ticker,
                strategy=strategy,
                entry_price=price,
                stop=price * 0.93,
                target=price * 1.15,
            )
            conviction_score = cv.get('score', 0)
            result['conviction'] = conviction_score
            result['reasons'].append(
                f"conviction={conviction_score} ({cv.get('recommendation', '?')})"
            )
            if cv.get('block_reason'):
                result['reasons'].append(f"block: {cv['block_reason'][:80]}")
                result['verdict'] = 'NICHT_KAUFEN'
                result['score'] = -100
                return result
        except Exception as e:
            result['reasons'].append(f'conviction-err: {e}')

    # ── Signal 2: Insider (Phase 10) ──
    try:
        from intelligence.sec_edgar import insider_signal
        sig = insider_signal(ticker, days=30, use_cache=True)
        result['insider_bias'] = sig.get('bias', 'NEUTRAL')
        insider_raw = int(sig.get('score', 0))
        result['reasons'].append(
            f"insider={result['insider_bias']} ({insider_raw:+d})"
        )
    except Exception as e:
        result['insider_bias'] = 'NEUTRAL'
        insider_raw = 0
        result['reasons'].append(f'insider-err: {str(e)[:40]}')

    # ── Signal 3: Macro Regime (Phase 11) ──
    macro = _load_json(MACRO_FILE, {})
    result['macro_bias'] = macro.get('bias', 'NEUTRAL')
    macro_score = macro.get('score', 0) or 0
    result['reasons'].append(
        f"macro={result['macro_bias']} ({macro_score:+d})"
    )

    # ── Signal 4: 52W drawdown + trend sanity ──
    high_52w = _high_52w(ticker)
    if high_52w and high_52w > 0:
        dd = (price - high_52w) / high_52w
        result['reasons'].append(f'52w_dd={dd*100:+.0f}%')
        # If deeply underwater + negative macro → caution
        if dd < -0.40:
            result['reasons'].append('deep 52W drawdown')

    # ── Aggregate score ──
    score = 0
    if conviction_score is not None:
        score += conviction_score
    score += max(-15, min(15, insider_raw // 4))
    score += max(-10, min(10, macro_score // 4))
    result['score'] = score

    # ── Verdict Decision Tree ──
    has_bearish_insider = result['insider_bias'] == 'BEARISH' and insider_raw <= -40
    macro_risk_off = result['macro_bias'] == 'BEARISH' and macro_score <= -25

    if score >= KAUFEN_MIN_CONVICTION and not has_bearish_insider and not macro_risk_off:
        result['verdict'] = 'KAUFEN'
    elif score >= WARTEN_MIN_CONVICTION:
        result['verdict'] = 'WARTEN'
    else:
        result['verdict'] = 'NICHT_KAUFEN'

    # Safety: if no strategy available, never auto-KAUFEN (no thesis to defend)
    if not strategy and result['verdict'] == 'KAUFEN':
        result['verdict'] = 'WARTEN'
        result['reasons'].append('no active strategy → WARTEN')

    # Phase 3: Rule-based analysis darf NIEMALS KAUFEN ausstellen.
    # Ein echter 6-Schritt-Deep-Dive (Leiche im Keller, Katalysator, Bewertung etc.)
    # ist Voraussetzung für ENTRY. Rule-Engine flaggt nur Kandidaten auf WARTEN,
    # die dann via DEEP_DIVE-Action in autonomous_ceo vom LLM echt analysiert werden.
    # Defensive Verdicts (NICHT_KAUFEN) bleiben erlaubt, da sie nur blockieren.
    if result['verdict'] == 'KAUFEN':
        result['verdict'] = 'WARTEN'
        result['reasons'].append('rule→WARTEN (KAUFEN nur via echtem Deep Dive)')

    return result


def _build_verdict_entry(analysis: dict) -> dict:
    now = datetime.now(_BERLIN)
    expires = now + timedelta(days=12)
    return {
        'ticker': analysis['ticker'],
        'verdict': analysis['verdict'],
        'date': now.strftime('%Y-%m-%d'),
        'updated_at': now.isoformat(timespec='seconds'),
        'expires': expires.strftime('%Y-%m-%d'),
        'source': 'auto_deepdive_rule',
        'analyst': 'auto_deepdive',
        'strategy': analysis.get('strategy'),
        'score': analysis['score'],
        'conviction': analysis['conviction'],
        'insider_bias': analysis['insider_bias'],
        'macro_bias': analysis['macro_bias'],
        'reasons': analysis['reasons'],
    }


def _log_flip(ticker: str, old: str, new: str, reasons: list[str]) -> None:
    flips = _load_json(FLIP_LOG, [])
    flips.append({
        'ticker': ticker,
        'timestamp': datetime.now(_BERLIN).isoformat(timespec='seconds'),
        'old_verdict': old,
        'new_verdict': new,
        'reasons': reasons[:5],
    })
    _save_json(FLIP_LOG, flips[-200:])


def _notify_flip(ticker: str, old: str, new: str, reasons: list[str]) -> None:
    """Queued — erscheint im Daily Digest, nicht sofort."""
    try:
        from discord_queue import queue_event
        body = f'{old or "—"} → **{new}** | {"; ".join(reasons[:3])}'
        priority = 'warning' if new == 'NICHT_KAUFEN' else 'info'
        queue_event(priority, f'Deep Dive Flip: {ticker}', body, source='Auto Deep Dive')
    except Exception:
        pass


# ─────────── Main ───────────

def run(force_all: bool = False) -> dict:
    tickers = _collect_tickers()
    # Strip non-US that our signals don't support well
    tickers = {t for t in tickers if '.' not in t and '-' not in t}

    log.info(f'Auto Deep Dive: {len(tickers)} tickers')

    verdicts = _load_json(VERDICTS_FILE, {})
    stats = {
        'processed': 0, 'refreshed': 0, 'skipped_fresh': 0, 'flipped': 0,
        'KAUFEN': 0, 'WARTEN': 0, 'NICHT_KAUFEN': 0,
    }

    for ticker in sorted(tickers):
        existing = verdicts.get(ticker, {})
        exist_source = existing.get('source', '')
        exist_date = existing.get('date', '')

        # Do not overwrite trusted discord_deepdive verdicts unless stale
        is_fresh = False
        if exist_date:
            try:
                age = (datetime.now(_BERLIN) - datetime.fromisoformat(exist_date)).days
                is_fresh = age <= REFRESH_IF_AGE_DAYS
            except Exception:
                pass

        # Phase 5: "Echter Deep Dive" erkennen — NICHT überschreiben!
        # Kriterien (eins reicht):
        #   a) explizite source='discord_deepdive' / 'albert_discord' / 'deep_dive' / 'Albert'
        #   b) analyst-Feld startet mit "Albert" (Legacy-Format)
        #   c) key_findings-Objekt vorhanden (6-Schritt Protokoll-Signatur)
        #   d) kompletter Trade-Plan (entry, stop, ziel_1 alle gesetzt)
        def _is_real_deep_dive(v: dict) -> bool:
            src = str(v.get('source', '')).lower()
            if src in ('discord_deepdive', 'albert_discord', 'deep_dive', 'albert'):
                return True
            analyst = str(v.get('analyst', ''))
            if analyst and analyst.lower().startswith('albert'):
                return True
            if isinstance(v.get('key_findings'), dict) and v['key_findings']:
                return True
            if v.get('entry') and v.get('stop') and v.get('ziel_1'):
                return True
            return False

        # Skip if echter Deep Dive + fresh — NIEMALS überschreiben
        if not force_all and is_fresh and _is_real_deep_dive(existing):
            stats['skipped_fresh'] += 1
            continue
        # Skip if rule-based + fresh (accept both new 'auto_deepdive_rule'
        # and legacy 'autonomous_ceo' marker to keep backward-compat)
        if not force_all and is_fresh and exist_source in ('auto_deepdive_rule', 'autonomous_ceo'):
            stats['skipped_fresh'] += 1
            continue

        try:
            analysis = _analyze_ticker(ticker)
        except Exception as e:
            log.warning(f'{ticker} analyze failed: {e}')
            continue

        new_entry = _build_verdict_entry(analysis)
        old_verdict = existing.get('verdict')

        # Preserve echte Deep-Dive-Verdicts vor Rule-Override
        # (Ein manuell erstellter Deep Dive darf NIE von der Rule-Engine
        # überschrieben werden — auch nicht mit NICHT_KAUFEN. Wenn die
        # Rule-Engine etwas Besorgniserregendes findet, muss Albert neu
        # analysieren. Protection ist hart.)
        if _is_real_deep_dive(existing) and not force_all:
            stats['skipped_fresh'] += 1
            continue

        verdicts[ticker] = new_entry
        stats['processed'] += 1
        stats['refreshed'] += 1
        stats[new_entry['verdict']] = stats.get(new_entry['verdict'], 0) + 1

        if old_verdict and old_verdict != new_entry['verdict']:
            stats['flipped'] += 1
            _log_flip(ticker, old_verdict, new_entry['verdict'], analysis['reasons'])
            _notify_flip(ticker, old_verdict, new_entry['verdict'], analysis['reasons'])

        log.info(
            f"  {ticker:6} {new_entry['verdict']:13} "
            f"score={analysis['score']:+4d} "
            f"{'; '.join(analysis['reasons'][:3])[:80]}"
        )

    _save_json(VERDICTS_FILE, verdicts)
    return stats


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    force = '--force' in sys.argv
    stats = run(force_all=force)
    print('\n── Auto Deep Dive Summary ──')
    for k, v in stats.items():
        print(f'  {k:15} {v}')


if __name__ == '__main__':
    main()
