#!/usr/bin/env python3
"""
Feature Analyzer — Phase 1 Auswertung
======================================
Analysiert welche Features mit Trade-Outcomes korrelieren.
Läuft wöchentlich ab 50+ Trades mit Feature-Daten.

Usage:
  python3 feature_analyzer.py           # Vollständige Analyse
  python3 feature_analyzer.py --quick   # Kurze Übersicht
"""

import sqlite3
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'
REPORT_FILE = WS / 'memory/feature-analysis.md'
MIN_TRADES_FOR_ANALYSIS = 30  # Unter diesem Wert: zu wenig Daten


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def load_closed_with_features() -> list[dict]:
    """Lädt alle geschlossenen Trades die Feature-Daten haben."""
    conn = get_db()
    rows = conn.execute("""
        SELECT
            ticker, strategy, pnl_eur, pnl_pct, exit_type,
            rsi_at_entry, volume_ratio, vix_at_entry, atr_pct_at_entry,
            ma50_distance, day_of_week, hour_of_entry,
            sector_momentum, spy_5d_return,
            CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END as win
        FROM paper_portfolio
        WHERE status IN ('WIN', 'CLOSED', 'LOSS')
          AND rsi_at_entry IS NOT NULL
          AND pnl_eur IS NOT NULL
        ORDER BY close_date DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def bucket_analysis(trades: list[dict], feature: str, buckets: list[tuple]) -> list[dict]:
    """
    Teilt Trades in Buckets auf und berechnet Win-Rate pro Bucket.
    buckets: [(label, min, max), ...]
    """
    results = []
    for label, lo, hi in buckets:
        bucket_trades = [
            t for t in trades
            if t.get(feature) is not None and lo <= t[feature] < hi
        ]
        if not bucket_trades:
            continue
        wins = sum(t['win'] for t in bucket_trades)
        avg_pnl = sum(t['pnl_pct'] or 0 for t in bucket_trades) / len(bucket_trades)
        results.append({
            'label': label,
            'trades': len(bucket_trades),
            'win_rate': wins / len(bucket_trades),
            'avg_pnl_pct': round(avg_pnl, 2),
        })
    return results


def correlation(trades: list[dict], feature: str) -> float | None:
    """Berechnet Pearson-Korrelation zwischen Feature und Win (0/1)."""
    valid = [(t[feature], t['win']) for t in trades if t.get(feature) is not None]
    if len(valid) < 10:
        return None
    n = len(valid)
    xs = [v[0] for v in valid]
    ys = [v[1] for v in valid]
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx = (sum((x-mx)**2 for x in xs))**0.5
    dy = (sum((y-my)**2 for y in ys))**0.5
    if dx == 0 or dy == 0:
        return 0.0
    return round(num / (dx * dy), 3)


def analyze() -> dict:
    """Hauptanalyse: alle Features vs. Trade-Outcomes."""
    trades = load_closed_with_features()

    if len(trades) < MIN_TRADES_FOR_ANALYSIS:
        return {
            'status': 'insufficient_data',
            'trades_with_features': len(trades),
            'needed': MIN_TRADES_FOR_ANALYSIS,
            'message': f"Nur {len(trades)} Trades mit Features. {MIN_TRADES_FOR_ANALYSIS - len(trades)} weitere nötig."
        }

    # ── RSI-Buckets ──
    rsi_buckets = bucket_analysis(trades, 'rsi_at_entry', [
        ('Überverkauft (<30)',   0,  30),
        ('Neutral-Low (30-45)', 30, 45),
        ('Neutral (45-60)',     45, 60),
        ('Neutral-High (60-70)',60, 70),
        ('Überkauft (70-80)',   70, 80),
        ('Extrem (80+)',        80, 100),
    ])

    # ── VIX-Buckets ──
    vix_buckets = bucket_analysis(trades, 'vix_at_entry', [
        ('Bull (<18)',          0,  18),
        ('Neutral (18-25)',    18,  25),
        ('Risk-Off (25-32)',   25,  32),
        ('Fear (32+)',         32, 100),
    ])

    # ── Volume-Ratio-Buckets ──
    vol_buckets = bucket_analysis(trades, 'volume_ratio', [
        ('Tief (<0.7)',         0,   0.7),
        ('Normal (0.7-1.3)',   0.7,  1.3),
        ('Erhöht (1.3-2.0)',   1.3,  2.0),
        ('Stark (2.0+)',       2.0, 99.0),
    ])

    # ── MA50 Distanz ──
    ma50_buckets = bucket_analysis(trades, 'ma50_distance', [
        ('Stark darunter (<-10%)', -99, -10),
        ('Darunter (-10 bis -3%)', -10,  -3),
        ('Nahe MA50 (-3 bis +3%)',  -3,   3),
        ('Darüber (+3 bis +10%)',    3,  10),
        ('Stark darüber (>+10%)',   10,  99),
    ])

    # ── Wochentag ──
    day_names = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag']
    weekday_stats = {}
    for d in range(5):
        d_trades = [t for t in trades if t.get('day_of_week') == d]
        if d_trades:
            wins = sum(t['win'] for t in d_trades)
            weekday_stats[day_names[d]] = {
                'trades': len(d_trades),
                'win_rate': round(wins / len(d_trades), 3),
                'avg_pnl': round(sum(t['pnl_pct'] or 0 for t in d_trades) / len(d_trades), 2)
            }

    # ── Korrelationen ──
    correlations = {}
    for feat in ['rsi_at_entry', 'volume_ratio', 'vix_at_entry',
                 'atr_pct_at_entry', 'ma50_distance', 'sector_momentum', 'spy_5d_return']:
        c = correlation(trades, feat)
        if c is not None:
            correlations[feat] = c

    # Sortiert nach absolutem Korrelationswert
    sorted_corr = sorted(correlations.items(), key=lambda x: abs(x[1]), reverse=True)

    return {
        'status': 'ok',
        'trades_analyzed': len(trades),
        'overall_win_rate': round(sum(t['win'] for t in trades) / len(trades), 3),
        'rsi_buckets': rsi_buckets,
        'vix_buckets': vix_buckets,
        'volume_buckets': vol_buckets,
        'ma50_buckets': ma50_buckets,
        'weekday_stats': weekday_stats,
        'correlations': dict(sorted_corr),
        'top_predictors': [feat for feat, _ in sorted_corr[:3]],
    }


def generate_report(analysis: dict) -> str:
    """Erstellt Markdown-Report."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lines = [
        f"# Feature Analysis Report",
        f"*Generiert: {now} | Phase 1 — Feature Tracking*",
        "",
    ]

    if analysis['status'] == 'insufficient_data':
        lines += [
            f"## ⏳ Noch nicht genug Daten",
            "",
            f"- Trades mit Features: **{analysis['trades_with_features']}**",
            f"- Benötigt: **{analysis['needed']}**",
            f"- Fehlend: **{analysis['needed'] - analysis['trades_with_features']}** weitere Trades",
            "",
            "*Sammle weiter Trades — der Analyzer läuft automatisch wöchentlich.*"
        ]
        return '\n'.join(lines)

    lines += [
        f"## 📊 Übersicht",
        f"- Analysierte Trades: **{analysis['trades_analyzed']}**",
        f"- Gesamt Win-Rate: **{analysis['overall_win_rate']:.0%}**",
        f"- Top Predictoren: **{', '.join(analysis['top_predictors'])}**",
        "",
    ]

    # Korrelationen
    lines += ["## 🔗 Feature-Korrelationen (mit Trade-Outcome)", "",
              "| Feature | Korrelation | Interpretation |",
              "|---------|-------------|----------------|"]
    for feat, corr in analysis['correlations'].items():
        strength = "stark" if abs(corr) > 0.3 else "moderat" if abs(corr) > 0.15 else "schwach"
        direction = "↑ höher = besser" if corr > 0 else "↓ niedriger = besser"
        lines.append(f"| {feat} | {corr:+.3f} | {strength} — {direction} |")
    lines.append("")

    # RSI Buckets
    if analysis['rsi_buckets']:
        lines += ["## 📈 RSI bei Entry", "",
                  "| RSI-Range | Trades | Win-Rate | Avg P&L% |",
                  "|-----------|--------|----------|----------|"]
        for b in analysis['rsi_buckets']:
            best = " ⭐" if b['win_rate'] == max(x['win_rate'] for x in analysis['rsi_buckets']) else ""
            lines.append(f"| {b['label']} | {b['trades']} | {b['win_rate']:.0%}{best} | {b['avg_pnl_pct']:+.1f}% |")
        lines.append("")

    # VIX Buckets
    if analysis['vix_buckets']:
        lines += ["## 📊 VIX bei Entry", "",
                  "| VIX-Range | Trades | Win-Rate | Avg P&L% |",
                  "|-----------|--------|----------|----------|"]
        for b in analysis['vix_buckets']:
            best = " ⭐" if b['win_rate'] == max(x['win_rate'] for x in analysis['vix_buckets']) else ""
            lines.append(f"| {b['label']} | {b['trades']} | {b['win_rate']:.0%}{best} | {b['avg_pnl_pct']:+.1f}% |")
        lines.append("")

    # Weekday
    if analysis['weekday_stats']:
        lines += ["## 📅 Wochentag bei Entry", "",
                  "| Tag | Trades | Win-Rate | Avg P&L% |",
                  "|-----|--------|----------|----------|"]
        for day, s in analysis['weekday_stats'].items():
            best = " ⭐" if s['win_rate'] == max(x['win_rate'] for x in analysis['weekday_stats'].values()) else ""
            lines.append(f"| {day} | {s['trades']} | {s['win_rate']:.0%}{best} | {s['avg_pnl']:+.1f}% |")

    lines += ["", "---",
              f"*Nächste Update: wenn 50+ weitere Trades geschlossen sind oder manuell via `feature_analyzer.py`*"]

    return '\n'.join(lines)


if __name__ == '__main__':
    args = sys.argv[1:]
    print("[Feature Analyzer] Starte Analyse...")

    result = analyze()

    if '--quick' in args:
        if result['status'] == 'insufficient_data':
            print(f"  ⏳ {result['message']}")
        else:
            print(f"  ✅ {result['trades_analyzed']} Trades | Win-Rate {result['overall_win_rate']:.0%}")
            print(f"  Top Predictoren: {', '.join(result['top_predictors'])}")
            for feat, corr in list(result['correlations'].items())[:3]:
                print(f"    {feat}: {corr:+.3f}")
    else:
        report = generate_report(result)
        REPORT_FILE.write_text(report, encoding="utf-8")
        print(f"  ✅ Report geschrieben: {REPORT_FILE}")
        if result['status'] == 'ok':
            print(f"  Top Predictoren: {', '.join(result['top_predictors'])}")
            print(f"  Korrelationen:")
            for feat, corr in result['correlations'].items():
                bar = '█' * int(abs(corr) * 20)
                print(f"    {feat:25s}: {corr:+.3f} {bar}")
