#!/usr/bin/env python3
"""
tranche_ab_report.py — A/B-Test Auswertung TRANCHES vs FULL_TRAIL.

Test-Periode: 2026-04-30 (Start) → 2026-05-30 (Ende).
Trade-ID Paritaet entscheidet Mode (gerade=TRANCHES, ungerade=FULL_TRAIL).

Reportiert:
  - N pro Variante
  - Total P&L, Avg-P&L, Win-Rate
  - Avg-Win, Avg-Loss, Profit-Faktor
  - Statistik-Empfehlung
"""
from __future__ import annotations
import os, sqlite3, sys
from pathlib import Path
from datetime import datetime

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'

START = '2026-04-30'
END   = '2026-05-30'


def _stats(rows):
    n = len(rows)
    if n == 0:
        return None
    pnls = [r['pnl_eur'] or 0 for r in rows]
    total = sum(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    wr = 100 * len(wins) / n if n else 0
    avg_win = sum(wins)/len(wins) if wins else 0
    avg_loss = sum(losses)/len(losses) if losses else 0
    pf = (sum(wins) / abs(sum(losses))) if losses else float('inf')
    return {
        'n': n, 'total': total, 'avg': total/n,
        'wr': wr, 'avg_win': avg_win, 'avg_loss': avg_loss,
        'pf': pf, 'open': sum(1 for r in rows if r['status']=='OPEN'),
        'closed': sum(1 for r in rows if r['status'] in ('CLOSED','WIN','LOSS')),
    }


def main():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, ticker, strategy, status, pnl_eur, "
        "       COALESCE(tranche_mode,'TRANCHES') AS mode, "
        "       entry_date, close_date "
        "FROM paper_portfolio "
        "WHERE entry_date >= ? AND entry_date <= ?",
        (START, END + 'T23:59:59')
    ).fetchall()
    c.close()

    tranche = [r for r in rows if r['mode'] == 'TRANCHES']
    full    = [r for r in rows if r['mode'] == 'FULL_TRAIL']

    s_t = _stats(tranche)
    s_f = _stats(full)

    print(f'═══ TRANCHE A/B-TEST {START} → {END} ═══')
    print(f'Total Trades: {len(rows)}  (Tranche={len(tranche)}, FullTrail={len(full)})')
    print()
    print(f'{"Metric":<22} {"TRANCHES":>14} {"FULL_TRAIL":>14}')
    print('-' * 52)
    if s_t and s_f:
        for k, label in [
            ('n','Total N'), ('open','Open'), ('closed','Closed'),
            ('total','P&L EUR'), ('avg','Avg P&L'), ('wr','Win-Rate %'),
            ('avg_win','Avg Win'), ('avg_loss','Avg Loss'), ('pf','Profit-Factor'),
        ]:
            t = s_t[k]; f = s_f[k]
            t_s = f'{t:>+14.2f}' if isinstance(t, float) else f'{t:>14}'
            f_s = f'{f:>+14.2f}' if isinstance(f, float) else f'{f:>14}'
            print(f'{label:<22} {t_s} {f_s}')

        print()
        diff = s_f['total'] - s_t['total']
        winner = 'FULL_TRAIL' if diff > 0 else 'TRANCHES'
        print(f'Δ P&L: {diff:+.2f}€  →  Sieger: {winner}')
        if s_t['n'] < 8 or s_f['n'] < 8:
            print('⚠️ Sample zu klein (<8 pro Variante) — Ergebnis nicht robust.')
        elif abs(diff) < 100:
            print('⚠️ Differenz <100€ — Unterschied gering, evtl. Test verlaengern.')
        else:
            print(f'✅ Klares Signal — {winner} dauerhaft uebernehmen.')
    else:
        print('Noch keine Trades in der Test-Periode.')


if __name__ == '__main__':
    main()
