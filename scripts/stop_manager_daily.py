#!/usr/bin/env python3
"""
stop_manager_daily.py — Phase 44n: Professional Stop-Management.

Ersetzt die intraday-getriebene Macro-Reactor-Logik durch sauberen
Daily-Cycle nach Boersenschluss. Profis ziehen Stops einmal pro Tag
nach Close, nicht intraday. Das eliminiert Mikro-Stop-Outs.

Kern-Logik (Chandelier Exit + VIX-Regime):

  ATR(14)         = mean(high-low) der letzten 14 daily bars
  HWM             = highest close seit Entry
  VIX_mult        = je nach Markt-Regime (s.u.)
  trial_stop      = HWM - VIX_mult x ATR
  new_stop        = max(current_stop, trial_stop)  ← Ratchet, nur nach oben

VIX-Regime:
  < 15  calm    → 2.0 x ATR
  15-25 normal  → 2.5 x ATR
  25-40 elev.   → 3.0 x ATR
  > 40  crisis  → 3.5 x ATR

Schutzregeln:
  1) Position-Alter < 24h → kein Stop-Move (Atemluft)
  2) Position-Profit < 5% → kein Trail (Tagesvolatilitaet)
  3) Stop bewegt sich nur HOCH, nie runter (Ratchet)
  4) Time-Stop: wenn 14d flat (-2% bis +2%) → Exit-Empfehlung

Run:
  python3 scripts/stop_manager_daily.py            # echte Updates
  python3 scripts/stop_manager_daily.py --dry-run  # nur Vorschlaege
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
LOG_FILE = WS / 'data' / 'stop_manager_log.jsonl'
COMMODITY_CACHE = WS / 'data' / 'commodity_prices.json'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vix_multiplier() -> tuple[float, float]:
    """Liest VIX aus commodity_prices.json. Gibt (vix_value, atr_multiplier)."""
    try:
        if COMMODITY_CACHE.exists():
            d = json.loads(COMMODITY_CACHE.read_text(encoding='utf-8'))
            vix = d.get('prices', {}).get('^VIX', {}).get('spot')
            if vix is None:
                return 25.0, 2.5
            v = float(vix)
            if v < 15:   return v, 2.0
            if v < 25:   return v, 2.5
            if v < 40:   return v, 3.0
            return v, 3.5
    except Exception:
        pass
    return 25.0, 2.5  # Default normal


def _compute_atr_pct(c: sqlite3.Connection, ticker: str, n: int = 14) -> float | None:
    """ATR als Prozentwert vom letzten Close."""
    rows = c.execute(
        "SELECT high, low, close FROM prices WHERE ticker=? "
        "ORDER BY date DESC LIMIT ?", (ticker, n)
    ).fetchall()
    if len(rows) < 5:
        return None
    closes = [float(r[2]) for r in rows if r[2]]
    if not closes:
        return None
    avg_range = sum((float(h) - float(l)) for h, l, _ in rows) / len(rows)
    last_close = closes[0]
    return avg_range / last_close if last_close > 0 else None


def _compute_hwm(c: sqlite3.Connection, ticker: str, entry_date: str) -> float | None:
    """Highest close seit entry_date."""
    try:
        ed = entry_date[:10]
        row = c.execute(
            "SELECT MAX(high) FROM prices WHERE ticker=? AND date >= ?",
            (ticker, ed)
        ).fetchone()
        return float(row[0]) if row and row[0] else None
    except Exception:
        return None


def _is_position_flat_too_long(c: sqlite3.Connection, ticker: str,
                                  entry_price: float, entry_date: str,
                                  flat_days: int = 14) -> tuple[bool, float]:
    """True wenn Position seit flat_days nicht aus -2%/+2% rausgekommen ist."""
    try:
        ed = entry_date[:10]
        rows = c.execute(
            "SELECT date, close FROM prices WHERE ticker=? AND date >= ? "
            "ORDER BY date ASC", (ticker, ed)
        ).fetchall()
        if len(rows) < flat_days:
            return False, 0.0
        max_excursion = 0.0
        for _, close in rows:
            pct = abs((float(close) - entry_price) / entry_price * 100)
            max_excursion = max(max_excursion, pct)
        return max_excursion < 2.0, max_excursion
    except Exception:
        return False, 0.0


def review_open_positions(dry_run: bool = False) -> dict:
    if not DB.exists():
        return {'error': 'no_db'}
    vix, mult = _vix_multiplier()
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    opens = c.execute(
        "SELECT id, ticker, strategy, entry_price, stop_price, target_price, "
        "       shares, entry_date FROM paper_portfolio WHERE status='OPEN'"
    ).fetchall()

    actions = []
    summary = {'reviewed': 0, 'stop_moved': 0, 'flat_exit_reco': 0,
                'cooldown_skipped': 0, 'no_atr_data': 0, 'no_profit': 0}

    for r in opens:
        summary['reviewed'] += 1
        tid, ticker, strategy = r['id'], r['ticker'], r['strategy']
        entry = float(r['entry_price'] or 0)
        stop = float(r['stop_price'] or 0)
        entry_date = r['entry_date'] or ''

        # Live aus prices-Tabelle (letzter Close)
        last_close_row = c.execute(
            "SELECT close, date FROM prices WHERE ticker=? "
            "ORDER BY date DESC LIMIT 1", (ticker,)
        ).fetchone()
        if not last_close_row:
            continue
        last_close = float(last_close_row[0])
        unr_pct = (last_close - entry) / entry * 100 if entry else 0

        # 24h-Cooldown
        try:
            ed = datetime.fromisoformat(entry_date.replace('Z', '+00:00'))
            hours_since = (datetime.now(timezone.utc) - ed).total_seconds() / 3600
        except Exception:
            hours_since = 999
        if hours_since < 24:
            summary['cooldown_skipped'] += 1
            continue

        # Time-Stop Check (14d flat)
        flat, excursion = _is_position_flat_too_long(c, ticker, entry, entry_date, flat_days=14)
        if flat:
            actions.append({
                'tid': tid, 'ticker': ticker, 'action': 'TIME_EXIT_RECOMMENDED',
                'reason': f'14d flat (max excursion {excursion:.1f}%)',
                'live': last_close, 'entry': entry, 'unr_pct': round(unr_pct, 2),
            })
            summary['flat_exit_reco'] += 1
            continue

        # Profit-Check: nur trailen ab >= 5% gruen
        if unr_pct < 5:
            summary['no_profit'] += 1
            continue

        # ATR + HWM
        atr_pct = _compute_atr_pct(c, ticker)
        if atr_pct is None:
            summary['no_atr_data'] += 1
            continue
        hwm = _compute_hwm(c, ticker, entry_date) or last_close

        # Chandelier Exit: trial = HWM * (1 - mult * ATR%)
        trial_stop = hwm * (1 - mult * atr_pct)
        # Ratchet: nur nach oben
        new_stop = max(stop, trial_stop)
        # Sanity: niemals ueber live (sonst sofortiger Hit)
        new_stop = min(new_stop, last_close * 0.97)
        new_stop = round(new_stop, 4)

        if new_stop > stop + 0.01:  # Mindestbewegung 0.01€
            actions.append({
                'tid': tid, 'ticker': ticker, 'action': 'STOP_TRAIL',
                'old_stop': stop, 'new_stop': new_stop,
                'live': last_close, 'hwm': hwm, 'atr_pct': round(atr_pct*100, 2),
                'vix': vix, 'mult': mult, 'unr_pct': round(unr_pct, 2),
                'reason': f'Chandelier: HWM {hwm:.2f} - {mult}x ATR {atr_pct*100:.2f}%',
            })
            summary['stop_moved'] += 1
            if not dry_run:
                c.execute(
                    "UPDATE paper_portfolio SET stop_price=?, "
                    "  notes=COALESCE(notes,'') || ? WHERE id=?",
                    (new_stop,
                     f' | DAILY-TRAIL {stop:.2f}->{new_stop:.2f} (HWM {hwm:.2f} VIX {vix:.0f} mult {mult})',
                     tid))
                c.commit()

    c.close()

    # Audit-Log
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': _now(), 'dry_run': dry_run, 'vix': vix, 'mult': mult,
            'summary': summary, 'actions': actions,
        }, ensure_ascii=False) + '\n')

    return {'ts': _now(), 'vix': vix, 'mult': mult,
            'summary': summary, 'actions': actions}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    r = review_open_positions(dry_run=args.dry_run)
    print(f'═══ Stop Manager @ {r["ts"][:16]} (VIX {r["vix"]:.1f}, mult {r["mult"]}) ═══')
    print(f'  Summary: {r["summary"]}')
    if r['actions']:
        print(f'\nActions ({len(r["actions"])}):')
        for a in r['actions']:
            if a['action'] == 'STOP_TRAIL':
                print(f"  📈 {a['ticker']:<10} stop {a['old_stop']:.2f} → {a['new_stop']:.2f} "
                      f"(live {a['live']:.2f}, +{a['unr_pct']:.1f}%, ATR {a['atr_pct']:.2f}%)")
            elif a['action'] == 'TIME_EXIT_RECOMMENDED':
                print(f"  ⏱️  {a['ticker']:<10} TIME-EXIT empfohlen — {a['reason']}")
    if args.dry_run:
        print('\n[DRY RUN — nichts geaendert]')
    return 0


if __name__ == '__main__':
    sys.exit(main())
