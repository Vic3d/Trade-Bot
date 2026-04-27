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
MEMORY = WS / 'memory'
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atomic_json import atomic_write_json

DATA = WS / 'data'
DB = DATA / 'trading.db'
STRATS = DATA / 'strategies.json'
VERDICTS_FILE = DATA / 'deep_dive_verdicts.json'
MACRO_FILE = DATA / 'macro_regime.json'
FLIP_LOG = DATA / 'auto_deepdive_flips.json'
PROTOCOL_FILE = MEMORY / 'deepdive-protokoll.md'

# Guardrails — Victor 2026-04-20: Regeln aufs Minimum (wir müssen traden um zu lernen)
REFRESH_IF_AGE_DAYS = 5
KAUFEN_MIN_CONVICTION = 35  # Fallback-Rule-Engine
WARTEN_MIN_CONVICTION = 20

# LLM-Config (Victor 2026-04-20: echter 6-Schritt Deep Dive per Claude Sonnet)
LLM_MODEL = 'claude-sonnet-4-5'
LLM_MAX_TOKENS = 2000


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


# ─────────── LLM Deep Dive (Victor 2026-04-20) ───────────

def _get_api_key() -> str | None:
    key = os.environ.get('ANTHROPIC_API_KEY', '')
    if key:
        return key
    env_file = WS / 'deploy' / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            if line.startswith('ANTHROPIC_API_KEY=') and len(line) > 19:
                return line.split('=', 1)[1].strip()
    return None


def _tech_snapshot(ticker: str) -> dict:
    """Technische Daten aus DB: Preis, MA50/200, RSI, 52W, Performance."""
    tech: dict = {}
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT close, date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 252",
            (ticker,),
        ).fetchall()
        c.close()
        closes = [r['close'] for r in rows if r['close']]
        if not closes:
            return tech
        tech['current']  = round(closes[0], 2)
        tech['high_52w'] = round(max(closes[:min(252, len(closes))]), 2)
        tech['low_52w']  = round(min(closes[:min(252, len(closes))]), 2)
        tech['dist_52wh_pct'] = round((closes[0] - tech['high_52w']) / tech['high_52w'] * 100, 1)
        if len(closes) >= 50:
            tech['ma50'] = round(sum(closes[:50]) / 50, 2)
        if len(closes) >= 200:
            tech['ma200'] = round(sum(closes[:200]) / 200, 2)
        if len(closes) >= 15:
            gains = [max(closes[i-1] - closes[i], 0) for i in range(1, 15)]
            losses = [max(closes[i] - closes[i-1], 0) for i in range(1, 15)]
            ag = sum(gains) / 14 or 0.001
            al = sum(losses) / 14 or 0.001
            tech['rsi14'] = round(100 - 100 / (1 + ag / al), 1)
        if len(closes) >= 63:
            tech['perf_3m_pct'] = round((closes[0] - closes[62]) / closes[62] * 100, 1)
        if len(closes) >= 126:
            tech['perf_6m_pct'] = round((closes[0] - closes[125]) / closes[125] * 100, 1)
    except Exception as e:
        log.warning(f'  {ticker}: tech snapshot failed: {e}')
    return tech


def _recent_news(ticker: str, limit: int = 10) -> list[str]:
    """News aus overnight_events — LIKE-Match auf headline oder entities."""
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        # Schema: id, timestamp, headline, source, entities, ...
        rows = c.execute(
            """
            SELECT headline, source, timestamp
            FROM overnight_events
            WHERE (headline LIKE ? OR entities LIKE ?)
              AND timestamp >= datetime('now', '-30 days')
            ORDER BY timestamp DESC LIMIT ?
            """,
            (f'%{ticker}%', f'%{ticker}%', limit),
        ).fetchall()
        c.close()
        out = []
        for r in rows:
            h = (r['headline'] or '')[:150]
            src = r['source'] or '?'
            ts = str(r['timestamp'] or '')[:10]
            out.append(f'[{ts}] {h} ({src})')
        return out
    except Exception as e:
        log.warning(f'  {ticker}: news fetch failed: {e}')
        return []


def _strategy_context(ticker: str) -> dict:
    strats = _load_json(STRATS, {})
    for sid, cfg in strats.items():
        if not isinstance(cfg, dict):
            continue
        t_single = str(cfg.get('ticker', '')).upper()
        t_list = [str(t).upper() for t in cfg.get('tickers', [])]
        if t_single == ticker.upper() or ticker.upper() in t_list:
            return {
                'id': sid,
                'name': cfg.get('name', ''),
                'thesis': str(cfg.get('thesis', ''))[:300],
                'status': cfg.get('status', 'active'),
            }
    return {}


def _parse_llm_verdict(response: str) -> tuple[str, dict]:
    """Extrahiert Verdict + Entry/Stop/Ziel aus LLM-Antwort."""
    import re
    resp_up = response.upper()
    # Verdict
    verdict = 'WARTEN'
    if 'NICHT KAUFEN' in resp_up or 'NICHT_KAUFEN' in resp_up or 'DO NOT BUY' in resp_up:
        verdict = 'NICHT_KAUFEN'
    elif 'KAUFEN' in resp_up:
        # Check ob direkt davor ein "NICHT" steht (Stellen-Check)
        idx = resp_up.find('KAUFEN')
        prefix = resp_up[max(0, idx-15):idx]
        if 'NICHT' in prefix:
            verdict = 'NICHT_KAUFEN'
        else:
            verdict = 'KAUFEN'
    elif 'WARTEN' in resp_up or 'WAIT' in resp_up:
        verdict = 'WARTEN'

    extras: dict = {}
    # Entry / Stop / Ziel_1 aus strukturiertem Verdict-Block
    for key, patterns in {
        'entry':  [r'entry[:\s]*([0-9]+\.?[0-9]*)', r'einstieg[:\s]*([0-9]+\.?[0-9]*)'],
        'stop':   [r'stop[- ]?loss[:\s]*([0-9]+\.?[0-9]*)', r'stop[:\s]*([0-9]+\.?[0-9]*)'],
        'ziel_1': [r'ziel[- _]?1[:\s]*([0-9]+\.?[0-9]*)', r'target[- _]?1?[:\s]*([0-9]+\.?[0-9]*)'],
    }.items():
        for pat in patterns:
            m = re.search(pat, response, re.IGNORECASE)
            if m:
                try:
                    extras[key] = float(m.group(1))
                    break
                except Exception:
                    pass
    return verdict, extras


def _llm_deep_dive(ticker: str, strategy_ctx: dict | None = None) -> dict | None:
    """
    Echter 6-Schritt Deep Dive per Claude Sonnet.
    Returns dict {verdict, entry, stop, ziel_1, key_findings, raw_response}
    oder None bei API-Fehler (Caller soll Rule-Fallback nutzen).
    """
    api_key = _get_api_key()
    if not api_key:
        log.warning(f'  {ticker}: ANTHROPIC_API_KEY fehlt → Rule-Fallback')
        return None

    try:
        import anthropic
    except ImportError:
        log.warning(f'  {ticker}: anthropic package fehlt → Rule-Fallback')
        return None

    tech = _tech_snapshot(ticker)
    news = _recent_news(ticker)
    strat = strategy_ctx or _strategy_context(ticker)

    protocol = ''
    if PROTOCOL_FILE.exists():
        protocol = PROTOCOL_FILE.read_text(encoding='utf-8')[:3500]

    tech_str = '\n'.join(f'  {k}: {v}' for k, v in tech.items()) if tech else '  (keine Daten in DB)'
    news_str = '\n'.join(f'  - {n}' for n in news) if news else '  (keine News in letzten 30 Tagen)'
    strat_str = (f"Strategie {strat.get('id')}: {strat.get('name')}\n"
                 f"Thesis: {strat.get('thesis', '')[:250]}\n"
                 f"Status: {strat.get('status')}") if strat else 'Keine Strategie zugeordnet — reine Ticker-Analyse'

    prompt = f"""Du bist Albert, der AI-CEO von TradeMind. Führe jetzt einen vollständigen 6-Schritt Deep Dive für {ticker} durch.

TECHNISCHE DATEN (aus DB):
{tech_str}

RECENT NEWS (letzte 30 Tage):
{news_str}

STRATEGIE-KONTEXT:
{strat_str}

DEEP DIVE PROTOKOLL (exakt befolgen):
{protocol}

ANWEISUNG:
- Schritt 1-6 systematisch durchgehen.
- Schritt 4 (Leiche im Keller): ALLE 8 Fragen explizit beantworten.
- Wo Daten fehlen: "Daten fehlen — manuell prüfen" statt halluzinieren.
- Schließe mit einem maschinenlesbaren Trading-Verdict Block im Format:

VERDICT: KAUFEN|WARTEN|NICHT_KAUFEN
ENTRY: <zahl>
STOP: <zahl>
ZIEL_1: <zahl>
KEY_FINDINGS: <3-5 stichpunkte, max 300 zeichen>

Bei NICHT_KAUFEN oder WARTEN: ENTRY/STOP/ZIEL_1 trotzdem setzen (hypothetisch) oder 0."""

    try:
        import sys as _llmsys
        from pathlib import Path as _LP
        _llmsys.path.insert(0, str(_LP(__file__).resolve().parent.parent))
        from core.llm_client import call_llm as _call_llm
        raw, _usage = _call_llm(prompt, model_hint='sonnet', max_tokens=LLM_MAX_TOKENS)
        raw = (raw or '').strip()
    except Exception as e:
        log.warning(f'  {ticker}: LLM-Call fehlgeschlagen: {str(e)[:120]}')
        return None

    verdict, extras = _parse_llm_verdict(raw)

    # key_findings extrahieren
    key_findings = ''
    import re as _re
    m = _re.search(r'KEY_FINDINGS[:\s]*(.+?)(?:\n\n|\Z)', raw, _re.IGNORECASE | _re.DOTALL)
    if m:
        key_findings = m.group(1).strip()[:500]

    return {
        'verdict': verdict,
        'entry': extras.get('entry'),
        'stop': extras.get('stop'),
        'ziel_1': extras.get('ziel_1'),
        'key_findings': key_findings or raw[-400:],
        'raw_length': len(raw),
    }


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

    # ── Aggregate score (Victor 2026-04-20: Baseline damit auch ohne Strategy KAUFEN möglich) ──
    score = 0
    if conviction_score is not None:
        score += conviction_score
    else:
        score += 40  # Baseline wenn keine Strategy existiert (sonst kommt nie KAUFEN raus)
    score += max(-15, min(15, insider_raw // 4))
    score += max(-10, min(10, macro_score // 4))
    # 52W-Drawdown dämpft (aber blockt nicht mehr hart)
    if high_52w and high_52w > 0:
        _dd = (price - high_52w) / high_52w
        if _dd < -0.40:
            score -= 15
        elif _dd < -0.25:
            score -= 8
    result['score'] = score

    # ── Verdict Decision Tree (Victor 2026-04-20: Regeln auf Minimum) ──
    # Hard-Blocks nur bei extrem negativem Insider/Macro — sonst KAUFEN erlaubt.
    has_bearish_insider = result['insider_bias'] == 'BEARISH' and insider_raw <= -80
    macro_risk_off = result['macro_bias'] == 'BEARISH' and macro_score <= -50

    if score >= KAUFEN_MIN_CONVICTION and not has_bearish_insider and not macro_risk_off:
        result['verdict'] = 'KAUFEN'
    elif score >= WARTEN_MIN_CONVICTION:
        result['verdict'] = 'WARTEN'
    else:
        result['verdict'] = 'NICHT_KAUFEN'

    # KEIN Strategy-Block mehr — Victor: "Wir gewinnen keine Erkenntnis, wenn wir nicht traden."
    # KEIN hardcoded KAUFEN→WARTEN Flip mehr — Auto Deep Dive entscheidet.

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
    # Victor 2026-04-20: global trading — non-US (.DE, .PA, .L etc.) nicht mehr rausfiltern

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

        # Victor 2026-04-20: LLM-Deep-Dive als Primär-Pfad, Rule als Fallback
        analysis = None
        llm_result = None
        try:
            strategy_ctx = _strategy_context(ticker)
            llm_result = _llm_deep_dive(ticker, strategy_ctx)
        except Exception as e:
            log.warning(f'  {ticker} LLM failed: {e}')
            llm_result = None

        if llm_result is not None:
            # Baue Analysis-Dict aus LLM-Ergebnis
            analysis = {
                'ticker': ticker,
                'verdict': llm_result['verdict'],
                'score': 100 if llm_result['verdict'] == 'KAUFEN' else (
                         50 if llm_result['verdict'] == 'WARTEN' else 0),
                'conviction': None,
                'insider_bias': None,
                'macro_bias': None,
                'strategy': (strategy_ctx.get('id') if strategy_ctx else None),
                'reasons': [f"LLM Sonnet: {llm_result['verdict']}",
                            f"key_findings: {(llm_result.get('key_findings') or '')[:200]}"],
                'llm_entry': llm_result.get('entry'),
                'llm_stop': llm_result.get('stop'),
                'llm_ziel_1': llm_result.get('ziel_1'),
                'llm_key_findings': llm_result.get('key_findings', ''),
                'source_override': 'auto_deepdive_llm',
            }
        else:
            # Fallback auf Rule-Engine wenn LLM nicht verfügbar
            try:
                analysis = _analyze_ticker(ticker)
            except Exception as e:
                log.warning(f'{ticker} rule-analyze failed: {e}')
                continue

        new_entry = _build_verdict_entry(analysis)
        # LLM-Quelle + Extras reichern
        if llm_result is not None:
            new_entry['source']   = 'auto_deepdive_llm'
            new_entry['analyst']  = 'Albert'  # → wird als "echter Deep Dive" anerkannt
            new_entry['entry']    = llm_result.get('entry')
            new_entry['stop']     = llm_result.get('stop')
            new_entry['ziel_1']   = llm_result.get('ziel_1')
            new_entry['key_findings'] = {'summary': llm_result.get('key_findings', '')}
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
