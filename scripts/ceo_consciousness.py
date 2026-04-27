#!/usr/bin/env python3
"""
ceo_consciousness.py — Phase 33: Smart-CEO 2.0 — Mehr Bewusstsein.

6 Komponenten:
  33a Calibration-Loop      — Brier-Score, Confidence-Korrektur
  33b Portfolio-Planning    — gemeinsame Selektion Top-N
  33c Memory-Hierarchy      — permanent / quartal / tag Lessons
  33d World-Model           — Calendar (Earnings, Fed, Geo)
  33e Tilt-Detection        — Streak/Drawdown-Mood
  33f Hypothesis-Generator  — proaktive Theme-Suche

Alle exportieren saubere APIs für ceo_brain.py / ceo_intelligence.py.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, stdev

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB                = WS / 'data' / 'trading.db'
DECISIONS_LOG     = WS / 'data' / 'ceo_decisions.jsonl'
LESSONS_LOG       = WS / 'data' / 'ceo_lessons.jsonl'
PERMANENT_LESSONS = WS / 'data' / 'ceo_permanent_lessons.jsonl'
CALIBRATION_FILE  = WS / 'data' / 'ceo_calibration.json'
MOOD_FILE         = WS / 'data' / 'ceo_mood.json'
HYPOTHESES_FILE   = WS / 'data' / 'ceo_hypotheses.jsonl'


# ═══════════════════════════════════════════════════════════════════════════
# 33a — Calibration-Loop (Brier-Score)
# ═══════════════════════════════════════════════════════════════════════════

def compute_calibration(window_days: int = 60) -> dict:
    """
    Vergleicht historische Confidence vs realisierte Win-Rate.
    Returns:
      {
        'bins': {0.5: {'predicted': 0.55, 'actual': 0.40, 'n': 8}, ...},
        'brier_score': 0.18,
        'overconfidence_bias': +0.12,  # Predicted > Actual = overconfident
        'sample_size': 47,
        'recommendation': 'reduce_confidence_by_0.10'
      }
    """
    if not DECISIONS_LOG.exists():
        return {'sample_size': 0, 'brier_score': None}

    cutoff = (datetime.now() - timedelta(days=window_days)).isoformat()
    decisions = []
    for ln in DECISIONS_LOG.read_text(encoding='utf-8').strip().split('\n'):
        try:
            d = json.loads(ln)
            if d.get('ts', '') >= cutoff and d.get('event') == 'execute' and d.get('trade_id'):
                decisions.append(d)
        except Exception:
            continue

    # Hole Outcome für jede Decision
    if not decisions:
        return {'sample_size': 0, 'brier_score': None}

    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    samples = []
    for d in decisions:
        row = c.execute(
            "SELECT pnl_eur FROM paper_portfolio WHERE id=? AND status IN ('WIN','LOSS','CLOSED')",
            (d.get('trade_id'),)
        ).fetchone()
        if not row or row['pnl_eur'] is None:
            continue
        actual_win = 1 if row['pnl_eur'] > 0 else 0
        confidence = float(d.get('confidence', 0.5))
        samples.append((confidence, actual_win))
    c.close()

    if len(samples) < 5:
        return {'sample_size': len(samples), 'brier_score': None,
                'recommendation': 'insufficient_data'}

    # Brier-Score
    brier = mean((conf - act) ** 2 for conf, act in samples)

    # Bins (0.5, 0.6, 0.7, 0.8, 0.9)
    bins = {}
    for lo in (0.5, 0.6, 0.7, 0.8, 0.9):
        hi = lo + 0.10
        bin_samples = [(c, a) for c, a in samples if lo <= c < hi]
        if not bin_samples:
            continue
        avg_conf = mean(c for c, _ in bin_samples)
        avg_actual = mean(a for _, a in bin_samples)
        bins[round(lo, 1)] = {
            'predicted': round(avg_conf, 2),
            'actual':    round(avg_actual, 2),
            'n':         len(bin_samples),
        }

    # Overall Bias
    avg_pred = mean(c for c, _ in samples)
    avg_act  = mean(a for _, a in samples)
    bias = avg_pred - avg_act  # positiv = overconfident

    if abs(bias) < 0.05:
        recommendation = 'no_adjustment'
    elif bias > 0:
        recommendation = f'reduce_confidence_by_{round(bias, 2)}'
    else:
        recommendation = f'increase_confidence_by_{round(abs(bias), 2)}'

    result = {
        'sample_size': len(samples),
        'brier_score': round(brier, 3),
        'overconfidence_bias': round(bias, 3),
        'avg_predicted': round(avg_pred, 3),
        'avg_actual': round(avg_act, 3),
        'bins': bins,
        'recommendation': recommendation,
        'computed_at': datetime.now().isoformat(timespec='seconds'),
    }

    # Persist
    CALIBRATION_FILE.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def adjust_confidence(raw_confidence: float) -> float:
    """Wendet die letzte Calibration-Korrektur auf eine raw Confidence an."""
    if not CALIBRATION_FILE.exists():
        return raw_confidence
    try:
        cal = json.loads(CALIBRATION_FILE.read_text(encoding='utf-8'))
        bias = cal.get('overconfidence_bias', 0)
        if abs(bias) < 0.05:
            return raw_confidence
        # Subtract overconfidence_bias
        adjusted = max(0.0, min(1.0, raw_confidence - bias))
        return round(adjusted, 2)
    except Exception:
        return raw_confidence


# ═══════════════════════════════════════════════════════════════════════════
# 33b — Portfolio-Level-Planning
# ═══════════════════════════════════════════════════════════════════════════

def select_optimal_subset(decisions: list[dict], cash_available: float,
                           max_positions: int = 5) -> list[dict]:
    """
    Aus N proposed EXECUTE-Decisions wähle die Top-K die das BESTE Portfolio
    ergeben. Greedy mit Score = expected_pct * confidence - correlation_penalty.

    Hard-Constraints:
      - Cash-Constraint
      - max_positions Cap
      - keine 2 Trades in derselben Strategy (würde unsere existing Diversifikations-
        Regeln spiegeln)
    """
    candidates = [d for d in decisions if d.get('action') == 'EXECUTE']
    if not candidates:
        return decisions

    # Score pro Candidate: expected_outcome × confidence
    for c in candidates:
        c['_score'] = c.get('expected_pct', 0) * c.get('confidence', 0.5)

    # Sort by score descending
    candidates.sort(key=lambda x: x['_score'], reverse=True)

    selected = []
    used_strategies = set()
    cash_used = 0.0

    for c in candidates:
        if len(selected) >= max_positions:
            break
        # Strategy-Diversification: max 1 pro Strategy
        if c['strategy'] in used_strategies:
            c['action'] = 'WATCH'  # gut, aber zu viel dieser Strategie
            c['reason'] = (c.get('reason', '') +
                          f' | DEMOTED: bereits {c["strategy"]} im Selected-Set')
            continue
        # Cash-Estimate (10% des Funds für Position als rough heuristic)
        est_position_eur = 1500  # rough — paper_trade_engine nimmt's später genauer
        if cash_used + est_position_eur > cash_available * 0.85:
            c['action'] = 'WATCH'
            c['reason'] = (c.get('reason', '') + ' | DEMOTED: Cash-Constraint')
            continue
        selected.append(c)
        used_strategies.add(c['strategy'])
        cash_used += est_position_eur

    # Mark non-selected EXECUTE candidates as WATCH
    selected_ids = {id(c) for c in selected}
    for c in candidates:
        if id(c) not in selected_ids and c.get('action') == 'EXECUTE':
            c['action'] = 'WATCH'

    return decisions


# ═══════════════════════════════════════════════════════════════════════════
# 33c — Strategic Memory Hierarchy
# ═══════════════════════════════════════════════════════════════════════════

def promote_to_permanent(lesson: dict, evidence_count: int = 3) -> bool:
    """
    Promote eine Lesson nach permanent wenn ähnliche Lesson schon
    >= evidence_count Mal aufgetreten ist.
    """
    if not LESSONS_LOG.exists():
        return False
    try:
        existing = []
        for ln in LESSONS_LOG.read_text(encoding='utf-8').strip().split('\n'):
            try:
                existing.append(json.loads(ln))
            except Exception:
                continue
        # Simple keyword-overlap detection
        target_lesson = (lesson.get('lesson') or '').lower()
        target_words = set(target_lesson.split())
        if len(target_words) < 4:
            return False

        matches = 0
        for e in existing:
            other = (e.get('lesson') or '').lower()
            other_words = set(other.split())
            overlap = len(target_words & other_words)
            if overlap >= max(4, len(target_words) // 2):
                matches += 1

        if matches >= evidence_count:
            # Schreibe in permanent
            PERMANENT_LESSONS.parent.mkdir(parents=True, exist_ok=True)
            with open(PERMANENT_LESSONS, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'ts': datetime.now().isoformat(timespec='seconds'),
                    'lesson': lesson.get('lesson', ''),
                    'category': lesson.get('category', 'permanent'),
                    'evidence_count': matches,
                    'promoted_from': 'auto_pattern_detection',
                }, ensure_ascii=False) + '\n')
            return True
    except Exception as e:
        print(f'[consciousness] promote error: {e}', file=sys.stderr)
    return False


def load_hierarchical_lessons() -> dict:
    """
    Returns: {
        'permanent': [...],   # nie löschen
        'recent_60d': [...],  # ceo_lessons.jsonl Inhalt
    }
    """
    out = {'permanent': [], 'recent_60d': []}
    if PERMANENT_LESSONS.exists():
        for ln in PERMANENT_LESSONS.read_text(encoding='utf-8').strip().split('\n'):
            try:
                out['permanent'].append(json.loads(ln))
            except Exception:
                continue
    if LESSONS_LOG.exists():
        cutoff = (datetime.now() - timedelta(days=60)).isoformat()
        for ln in LESSONS_LOG.read_text(encoding='utf-8').strip().split('\n'):
            try:
                d = json.loads(ln)
                if d.get('ts', '') >= cutoff:
                    out['recent_60d'].append(d)
            except Exception:
                continue
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 33d — World-Model + Calendar
# ═══════════════════════════════════════════════════════════════════════════

def get_upcoming_events(tickers: list[str], days_ahead: int = 7) -> dict:
    """
    Returns: {
      'earnings': [{ticker, date, days_away}, ...],
      'macro': [{event, date, days_away}, ...],  # Fed/CPI/NFP wenn in DB
      'geo_alerts': current geo_alert_level
    }
    """
    out = {'earnings': [], 'macro': [], 'geo_alerts': 'unknown'}
    cutoff_date = datetime.now() + timedelta(days=days_ahead)

    # Earnings aus DB
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        # earnings_calendar Tabelle
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='earnings_calendar'"
        ).fetchone()
        if rows:
            placeholders = ','.join('?' * len(tickers)) if tickers else "''"
            tk_list = tickers if tickers else ['']
            cur = c.execute(f"""
                SELECT ticker, earnings_date FROM earnings_calendar
                WHERE ticker IN ({placeholders})
                  AND earnings_date BETWEEN ? AND ?
                ORDER BY earnings_date
            """, tk_list + [datetime.now().strftime('%Y-%m-%d'),
                            cutoff_date.strftime('%Y-%m-%d')])
            for r in cur:
                try:
                    e_dt = datetime.fromisoformat(str(r['earnings_date'])[:10])
                    out['earnings'].append({
                        'ticker': r['ticker'],
                        'date': str(r['earnings_date'])[:10],
                        'days_away': (e_dt - datetime.now()).days,
                    })
                except Exception:
                    continue
        c.close()
    except Exception as e:
        print(f'[consciousness] earnings error: {e}', file=sys.stderr)

    # Geo-Alert aus CEO-Direktive
    try:
        d = json.loads((WS / 'data' / 'ceo_directive.json').read_text(encoding='utf-8'))
        out['geo_alerts'] = d.get('geo_alert_level', 'unknown')
    except Exception:
        pass

    return out


# ═══════════════════════════════════════════════════════════════════════════
# 33e — Tilt-Detection / System-Mood
# ═══════════════════════════════════════════════════════════════════════════

def detect_mood(window_trades: int = 10) -> dict:
    """
    Analysiert letzte N closed Trades + computed Goal-Trend.
    Returns:
      {
        'mood': 'normal' | 'tilt' | 'overconfident',
        'recent_streak': '+3' or '-2',
        'recent_pnl_eur': ...,
        'recommendation': 'reduce_size' | 'normal' | 'careful_optimism',
        'size_multiplier': 1.0 | 0.5 | 1.2,
      }
    """
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT pnl_eur, close_date FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
            ORDER BY close_date DESC LIMIT ?
        """, (window_trades,)).fetchall()
        c.close()
    except Exception:
        return {'mood': 'unknown', 'size_multiplier': 1.0}

    if not rows:
        return {'mood': 'normal', 'recent_streak': '0',
                'recent_pnl_eur': 0, 'size_multiplier': 1.0,
                'recommendation': 'normal'}

    # Streak
    streak_type = 'win' if (rows[0]['pnl_eur'] or 0) > 0 else 'loss'
    streak_len = 0
    for r in rows:
        is_win = (r['pnl_eur'] or 0) > 0
        if (is_win and streak_type == 'win') or (not is_win and streak_type == 'loss'):
            streak_len += 1
        else:
            break

    streak_sign = '+' if streak_type == 'win' else '-'
    recent_pnl = sum((r['pnl_eur'] or 0) for r in rows)

    mood = 'normal'
    multiplier = 1.0
    recommendation = 'normal'

    if streak_type == 'loss' and streak_len >= 3:
        mood = 'tilt'
        multiplier = 0.5
        recommendation = 'reduce_size_by_50pct'
    elif streak_type == 'win' and streak_len >= 5:
        mood = 'overconfident'
        multiplier = 0.8  # leicht dampening (nicht voll, weil Wins sind gut)
        recommendation = 'careful_optimism_dampening'
    elif streak_type == 'loss' and streak_len >= 2 and recent_pnl < -200:
        mood = 'caution'
        multiplier = 0.7
        recommendation = 'tighter_stops'

    result = {
        'mood': mood,
        'recent_streak': f'{streak_sign}{streak_len}',
        'recent_pnl_eur': round(recent_pnl, 0),
        'size_multiplier': multiplier,
        'recommendation': recommendation,
        'window_trades': len(rows),
        'computed_at': datetime.now().isoformat(timespec='seconds'),
    }
    MOOD_FILE.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 33f — Hypothesis-Generator (proaktive Theme-Suche)
# ═══════════════════════════════════════════════════════════════════════════

def generate_hypotheses() -> list[dict]:
    """
    CEO als Forscher: identifiziere Themes/Sektoren die im Portfolio
    UNTERREPRÄSENTIERT sind aber in News-Frequenz oder Performance signal liefern.

    Output: Liste von Hypothesen die discoverable wären.
    """
    hypotheses = []
    try:
        from portfolio_risk import _get_open_positions, get_sector
        opens = _get_open_positions()
        open_sectors = {get_sector(p['ticker']) for p in opens}
    except Exception:
        open_sectors = set()

    # Welche Sektoren sind NICHT im Portfolio aber in News stark vertreten?
    try:
        c = sqlite3.connect(str(DB))
        cutoff = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
        rows = c.execute("""
            SELECT tickers FROM news_events
            WHERE created_at >= ? AND tickers IS NOT NULL
        """, (cutoff,)).fetchall()
        c.close()

        from portfolio_risk import get_sector as _gs
        sector_freq = {}
        for r in rows:
            tks = (r[0] or '').split(',')
            for tk in tks:
                tk = tk.strip().upper()
                if tk:
                    s = _gs(tk)
                    sector_freq[s] = sector_freq.get(s, 0) + 1

        # Underrepresentation-Score: sektor_freq / portfolio_presence
        for sector, freq in sector_freq.items():
            if sector in ('unknown', '?'):
                continue
            in_portfolio = sector in open_sectors
            if freq >= 5 and not in_portfolio:
                hypotheses.append({
                    'type': 'underrepresented_sector',
                    'sector': sector,
                    'news_frequency_14d': freq,
                    'in_portfolio': False,
                    'suggestion': f'Sektor "{sector}" hat {freq} News-Treffer '
                                  f'in 14d, ist nicht im Portfolio. '
                                  f'Discovery-Run mit Sektor-Filter prüfen.',
                })
    except Exception as e:
        print(f'[consciousness] hypothesis news error: {e}', file=sys.stderr)

    # Persist (max 50 Hypothesen)
    if hypotheses:
        try:
            HYPOTHESES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(HYPOTHESES_FILE, 'a', encoding='utf-8') as f:
                for h in hypotheses[:5]:
                    h['ts'] = datetime.now().isoformat(timespec='seconds')
                    f.write(json.dumps(h, ensure_ascii=False) + '\n')
        except Exception:
            pass

    return hypotheses[:5]


# ═══════════════════════════════════════════════════════════════════════════
# Main — täglich aktualisieren
# ═══════════════════════════════════════════════════════════════════════════

def main() -> int:
    print(f'─── CEO-Consciousness @ {datetime.now().isoformat(timespec="seconds")} ───')

    # 33a: Calibration
    cal = compute_calibration(window_days=60)
    print(f'\n33a CALIBRATION: brier={cal.get("brier_score")} '
          f'bias={cal.get("overconfidence_bias")} (n={cal.get("sample_size")})')
    print(f'   Recommendation: {cal.get("recommendation")}')

    # 33e: Mood
    mood = detect_mood(window_trades=10)
    print(f'\n33e MOOD: {mood["mood"]} '
          f'(streak {mood["recent_streak"]}, pnl {mood["recent_pnl_eur"]:+.0f}€)')
    print(f'   → size_multiplier {mood["size_multiplier"]}, '
          f'rec: {mood["recommendation"]}')

    # 33f: Hypotheses
    hyps = generate_hypotheses()
    print(f'\n33f HYPOTHESES: {len(hyps)} new')
    for h in hyps[:3]:
        print(f'   · [{h["type"]}] {h["suggestion"][:120]}')

    # 33d: World-Events
    try:
        from portfolio_risk import _get_open_positions
        open_tickers = [p['ticker'] for p in _get_open_positions()]
    except Exception:
        open_tickers = []
    events = get_upcoming_events(open_tickers, days_ahead=7)
    print(f'\n33d WORLD: earnings_in_7d={len(events["earnings"])} '
          f'geo_alert={events["geo_alerts"]}')
    for e in events['earnings'][:3]:
        print(f'   · {e["ticker"]} earnings in {e["days_away"]}d ({e["date"]})')

    # Discord-Push wenn was Bemerkenswertes
    push_msgs = []
    if mood['mood'] != 'normal':
        push_msgs.append(f"🎭 Mood: **{mood['mood']}** (streak {mood['recent_streak']}) "
                         f"→ size_multiplier {mood['size_multiplier']}")
    if cal.get('overconfidence_bias') and abs(cal['overconfidence_bias']) > 0.10:
        push_msgs.append(f"🎯 Calibration: bias **{cal['overconfidence_bias']:+.2f}** "
                         f"(n={cal['sample_size']}) → {cal['recommendation']}")
    if hyps:
        push_msgs.append(f"💡 {len(hyps)} neue Hypothesen "
                         f"(z.B. {hyps[0]['type']}: {hyps[0].get('sector','?')})")

    if push_msgs:
        try:
            from discord_dispatcher import send_alert, TIER_LOW
            send_alert('🧠 **CEO-Consciousness Update**\n\n' + '\n'.join(push_msgs),
                       tier=TIER_LOW, category='consciousness',
                       dedupe_key=f'cons_{datetime.now().strftime("%Y-%m-%d")}')
        except Exception:
            pass

    return 0


if __name__ == '__main__':
    sys.exit(main())
