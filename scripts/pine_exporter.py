#!/usr/bin/env python3
"""
pine_exporter.py — Phase 40f: Pine Script v6 Export für TradingView.

Konvertiert TradeMind-Strategien (z.B. PS14, PS_CCJ) in Pine Script v6
damit Du sie in TradingView visuell prüfen + backtesten kannst.

Coverage: Basic strategies (entry/stop/target). Komplexe Patterns
(Multi-Indicator, ML-basiert) werden als Kommentar markiert.

CLI:
  python3 scripts/pine_exporter.py PS14
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
STRATEGIES_FILE = WS / 'data' / 'strategies.json'
EXPORT_DIR = WS / 'data' / 'pine_exports'


def export_strategy_to_pine(strategy_id: str) -> str:
    """Returns Pine Script v6 code als String."""
    try:
        strategies = json.loads(STRATEGIES_FILE.read_text(encoding='utf-8'))
    except Exception as e:
        return f'// ERROR loading strategies.json: {e}'

    sdata = strategies.get(strategy_id)
    if not sdata or not isinstance(sdata, dict):
        return f'// Strategy {strategy_id} nicht gefunden'

    name = sdata.get('name', strategy_id)
    thesis = (sdata.get('thesis', '') or '')[:200]
    tickers = sdata.get('tickers', [])
    stop_pct = sdata.get('stop_pct', 0.08) * 100
    target_pct = sdata.get('target_pct', 0.15) * 100
    direction = sdata.get('direction', 'LONG').upper()

    # Try to detect specific indicators from thesis text
    use_rsi = any(kw in thesis.lower() for kw in ['rsi', 'oversold', 'überverkauft'])
    use_ma = any(kw in thesis.lower() for kw in ['ma', 'moving average', 'ema'])

    pine = f"""// ════════════════════════════════════════════════════════════════
// AUTO-GENERATED Pine Script v6 from TradeMind
// Strategy: {strategy_id} — {name}
// Direction: {direction}
// Tickers: {', '.join(tickers[:5])}
// Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
//
// THESIS:
// {thesis}
// ════════════════════════════════════════════════════════════════

//@version=6
strategy("TradeMind {strategy_id}", overlay=true,
         initial_capital=25000,
         default_qty_type=strategy.percent_of_equity,
         default_qty_value=6,
         commission_type=strategy.commission.percent,
         commission_value=0.1)

// ── Inputs ─────────────────────────────────────────────────────────
i_stop_pct   = input.float({stop_pct:.1f}, "Stop-Loss %", minval=1, maxval=20) / 100
i_target_pct = input.float({target_pct:.1f}, "Take-Profit %", minval=2, maxval=50) / 100
i_min_hold   = input.int(2, "Min Holding Days", minval=1)

// ── Indicators ─────────────────────────────────────────────────────
ma50  = ta.sma(close, 50)
ma200 = ta.sma(close, 200)
rsi   = ta.rsi(close, 14)
atr   = ta.atr(14)

"""

    # Entry-Logik basierend auf Thesis-Hints
    entry_conditions = []
    if use_rsi:
        if 'oversold' in thesis.lower() or 'überverkauft' in thesis.lower():
            entry_conditions.append('rsi < 35')
        else:
            entry_conditions.append('rsi > 50 and rsi < 70')
    if use_ma:
        entry_conditions.append('close > ma50')
    if not entry_conditions:
        # Fallback: trend + momentum
        entry_conditions.append('close > ma50')
        entry_conditions.append('rsi > 40 and rsi < 75')

    entry_logic = ' and '.join(entry_conditions)

    pine += f"""// ── Entry Logic ────────────────────────────────────────────────────
entry_signal = {entry_logic}

if (entry_signal and strategy.position_size == 0)
    strategy.entry("Long", strategy.long)

// ── Exit Logic ─────────────────────────────────────────────────────
if (strategy.position_size > 0)
    entry_price = strategy.position_avg_price
    stop_price  = entry_price * (1 - i_stop_pct)
    target_price = entry_price * (1 + i_target_pct)
    strategy.exit("TP/SL", "Long", stop=stop_price, limit=target_price)

// ── Visual ─────────────────────────────────────────────────────────
plot(ma50, "MA50", color=color.blue)
plot(ma200, "MA200", color=color.orange)
hline(70, "RSI Overbought", color=color.red, linestyle=hline.style_dashed)
hline(30, "RSI Oversold", color=color.green, linestyle=hline.style_dashed)

// ── Stats ─────────────────────────────────────────────────────────
// TradeMind Original Performance (last 90 days):
//   Win-Rate: see TradeMind Daily Report
//   PnL: see TradeMind Realized PnL
"""

    return pine


def export_to_file(strategy_id: str) -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    pine = export_strategy_to_pine(strategy_id)
    fname = f'{strategy_id}_{datetime.now().strftime("%Y%m%d")}.pine'
    out = EXPORT_DIR / fname
    out.write_text(pine, encoding='utf-8')
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: pine_exporter.py <STRATEGY_ID>')
        return 1
    sid = sys.argv[1]
    out = export_to_file(sid)
    print(f'Exported → {out}')
    print('---')
    print(out.read_text(encoding='utf-8')[:1500])
    return 0


if __name__ == '__main__':
    sys.exit(main())
