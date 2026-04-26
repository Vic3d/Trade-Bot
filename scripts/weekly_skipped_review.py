#!/usr/bin/env python3
"""
weekly_skipped_review.py — Mo 08:00 CEST: Review verworfener Trade-Setups.

Liest entry_gate_log der letzten 7 Tage, gruppiert nach Block-Reason,
identifiziert Top-3 "missed alpha" Kandidaten:
  - Welche Tickers wurden mehrfach blocked, sind seitdem deutlich gestiegen?
  - Welche Block-Gates feuern zu oft (möglicher Tuning-Bedarf)?

Output: Discord-Push am Montag morgen + Anhang in memory/skipped-review.md.

Mechanik "Missed Alpha":
  Für jeden geblockten Ticker (>=1 Block in letzten 7d):
    - Hole Preis bei Block-Zeitpunkt aus prices-Tabelle
    - Vergleiche mit aktuellem Preis
    - Wenn Anstieg >5% → "missed"

Discord-Format:
  📋 Wochenrückblick verworfene Trades (W17/26)
  Top-3 Gates: GATE0Q (8x), GATE2_GARBAGE (5x), GATE0r (3x)
  💔 Missed Alpha:
    NVDA: 4x blocked (FALLING_KNIFE), seitdem +12.4%
    PLTR: 2x blocked (Quarantäne), seitdem +8.1%
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB   = WS / 'data' / 'trading.db'
OUT  = WS / 'memory' / 'skipped-review.md'
DAYS = 7


def _fetch_recent_blocks() -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=DAYS)).strftime('%Y-%m-%d')
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT timestamp, ticker, strategy, gate_triggered, reason
        FROM entry_gate_log
        WHERE timestamp >= ?
        ORDER BY timestamp DESC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_price_at(ticker: str, ts: str) -> float | None:
    """Holt nächstgelegenen Preis aus prices-Tabelle."""
    try:
        conn = sqlite3.connect(str(DB))
        # prices Schema: ticker, date, close (typisch)
        row = conn.execute("""
            SELECT close FROM prices
            WHERE ticker = ? AND date <= ?
            ORDER BY date DESC LIMIT 1
        """, (ticker, ts[:10])).fetchone()
        conn.close()
        return float(row[0]) if row else None
    except Exception:
        return None


def _get_current_price(ticker: str) -> float | None:
    try:
        conn = sqlite3.connect(str(DB))
        row = conn.execute(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,)
        ).fetchone()
        conn.close()
        return float(row[0]) if row else None
    except Exception:
        return None


def _compute_missed_alpha(blocks: list[dict]) -> list[dict]:
    """Pro Ticker: berechne Performance seit erstem Block."""
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for b in blocks:
        by_ticker[b['ticker']].append(b)

    missed = []
    for ticker, evts in by_ticker.items():
        first = min(evts, key=lambda e: e['timestamp'])
        p_then = _get_price_at(ticker, first['timestamp'])
        p_now  = _get_current_price(ticker)
        if not p_then or not p_now or p_then <= 0:
            continue
        pct = (p_now - p_then) / p_then * 100
        gates = Counter(e['gate_triggered'] for e in evts)
        top_gate = gates.most_common(1)[0][0]
        missed.append({
            'ticker': ticker,
            'blocks': len(evts),
            'main_gate': top_gate,
            'pct_since_first_block': round(pct, 2),
            'first_block_ts': first['timestamp'][:16],
        })

    # Sort by pct desc — größte missed alpha first
    missed.sort(key=lambda m: m['pct_since_first_block'], reverse=True)
    return missed[:5]


def _format_discord(blocks: list[dict], missed: list[dict]) -> str:
    if not blocks:
        return '📋 **Wochenrückblick verworfener Trades**\n\nLetzte 7 Tage: keine Blockierungen registriert.'

    gate_counts = Counter(b['gate_triggered'] for b in blocks)
    top_gates = gate_counts.most_common(5)

    lines = [
        f'📋 **Wochenrückblick verworfener Trades** (letzte {DAYS}d, {len(blocks)} Blocks)',
        '',
        '**Top Block-Gates:**',
    ]
    for gate, n in top_gates:
        lines.append(f'  · `{gate}` — {n}x')

    if missed:
        lines.append('')
        lines.append('**💔 Missed Alpha** (Tickers die nach Block deutlich gestiegen sind):')
        any_real = False
        for m in missed:
            if m['pct_since_first_block'] >= 5.0:
                lines.append(
                    f"  · **{m['ticker']}** — {m['blocks']}x blocked ({m['main_gate']}), "
                    f"seitdem **{m['pct_since_first_block']:+.1f}%**"
                )
                any_real = True
        if not any_real:
            lines.append('  · _Kein blockierter Ticker ist signifikant gestiegen — Gates funktionieren._')

    lines.append('')
    lines.append('_Wenn ein Gate zu oft feuert oder zu viel Alpha frisst: Schwelle prüfen._')
    return '\n'.join(lines)


def _write_memory(text: str) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime('%Y-%m-%d')
    block = f'\n## {today} — Weekly Skipped-Trades Review\n\n{text}\n'
    with open(OUT, 'a', encoding='utf-8') as f:
        f.write(block)


def main() -> int:
    blocks = _fetch_recent_blocks()
    missed = _compute_missed_alpha(blocks) if blocks else []
    msg = _format_discord(blocks, missed)
    print(msg)
    _write_memory(msg)
    try:
        from discord_dispatcher import send_alert, TIER_MEDIUM
        send_alert(msg, tier=TIER_MEDIUM, category='weekly_review',
                   dedupe_key=f'skipped_review_{datetime.now().strftime("%Y-W%U")}')
    except Exception as e:
        print(f'[weekly_skipped] Discord-Send-Fehler: {e}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
