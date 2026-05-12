#!/usr/bin/env python3
"""
re_entry_watchlist.py — Phase 45av (Victor 2026-05-12).

Tradermacher-Lehre: "Die größten Moves kommen aus Fehlmoves. Wenn eine Position
ausgestoppt wurde + dann nochmal positiv dreht → STÄRKERES Signal als das erste."

Mechanik:
  1. Wenn Trade ausgestoppt wird (paper_exit_manager → STOP), füge Ticker zur
     re_entry_watchlist hinzu mit:
       - original_entry_price
       - original_stop_price
       - days_to_watch (Default 14)

  2. Täglich prüfen: hat Live-Preis den original_entry wieder genommen?
     - Ja + Volumen-Bestätigung → FAILED_BREAKOUT_RECLAIM Setup-Signal feuern
     - Nein → weiter beobachten bis days_to_watch abgelaufen

Output:
  - data/re_entry_watchlist.jsonl (state)
  - data/setup_signals.jsonl (signals, kompatibel mit live_trigger_watcher)

Run: täglich 22:00 + manual via paper_exit_manager-Hook.
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
WATCHLIST = WS / 'data' / 're_entry_watchlist.jsonl'
SIGNALS_LOG = WS / 'data' / 'setup_signals.jsonl'

DEFAULT_DAYS_TO_WATCH = 14
RECLAIM_THRESHOLD = 1.005  # Live muss original_entry * 1.005 erreichen


def _load_watchlist() -> list[dict]:
    if not WATCHLIST.exists(): return []
    out = []
    try:
        with open(WATCHLIST, encoding='utf-8') as f:
            for line in f:
                try: out.append(json.loads(line))
                except Exception: pass
    except Exception: pass
    return out


def _save_watchlist(items: list[dict]) -> None:
    WATCHLIST.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHLIST, 'w', encoding='utf-8') as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False, default=str) + '\n')


def add_to_watchlist(ticker: str, original_entry: float, original_stop: float,
                      strategy: str = None, trade_id: int = None,
                      days_to_watch: int = DEFAULT_DAYS_TO_WATCH) -> None:
    """Wird vom paper_exit_manager aufgerufen wenn Trade ausgestoppt wird."""
    now = datetime.now(timezone.utc)
    items = _load_watchlist()
    # Dedupe: gleicher Ticker mit aktivem Eintrag → skip
    if any(i['ticker'] == ticker and i.get('status') == 'WATCHING' for i in items):
        return
    items.append({
        'ticker': ticker,
        'original_entry': round(original_entry, 4),
        'original_stop': round(original_stop, 4),
        'strategy': strategy,
        'original_trade_id': trade_id,
        'added_at': now.isoformat(timespec='seconds'),
        'expires_at': (now + timedelta(days=days_to_watch)).isoformat(timespec='seconds'),
        'status': 'WATCHING',
        'reclaim_threshold': round(original_entry * RECLAIM_THRESHOLD, 4),
    })
    _save_watchlist(items)


def check_for_reclaims() -> dict:
    """Täglicher Job: prüfe alle WATCHING-Einträge."""
    items = _load_watchlist()
    if not items: return {'n_watching': 0, 'n_signals': 0}

    now = datetime.now(timezone.utc)
    signals_generated = 0
    changes = []

    for item in items:
        if item.get('status') != 'WATCHING':
            continue
        # Expired?
        try:
            exp = datetime.fromisoformat(item['expires_at'].replace('Z', '+00:00'))
            if now > exp:
                item['status'] = 'EXPIRED'
                changes.append(f'EXPIRED:{item["ticker"]}')
                continue
        except Exception: pass

        # Live-Preis EUR holen
        ticker = item['ticker']
        try:
            sys.path.insert(0, str(WS / 'scripts'))
            from position_pnl import get_live_price_eur
            live_eur, live_native, last_date = get_live_price_eur(ticker)
        except Exception:
            live_eur = None
        if not live_eur: continue

        threshold = item['reclaim_threshold']
        if live_eur >= threshold:
            # Volumen-Bestätigung
            vol_ok = True  # default true, könnte verschärft werden
            try:
                c = sqlite3.connect(str(DB))
                rows = c.execute(
                    "SELECT volume FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 21",
                    (ticker,)
                ).fetchall()
                c.close()
                if len(rows) >= 21:
                    today_vol = rows[0][0] or 0
                    avg_vol = sum(r[0] for r in rows[1:21] if r[0]) / 20
                    vol_ok = today_vol > avg_vol * 1.2
            except Exception: pass

            if vol_ok:
                # FAILED_BREAKOUT_RECLAIM-Signal feuern
                signal = {
                    'ts': now.isoformat(timespec='seconds'),
                    'ticker': ticker,
                    'pattern': 'FAILED_BREAKOUT_RECLAIM',
                    'confidence': 0.75,  # höher als regulärer Pattern
                    'last_close': round(live_eur, 2),
                    'original_entry': item['original_entry'],
                    'original_stop': item['original_stop'],
                    'original_strategy': item.get('strategy'),
                    'days_since_stop_out': (now - datetime.fromisoformat(
                        item['added_at'].replace('Z', '+00:00'))).days,
                    'entry_hint': f'Re-Take über {item["original_entry"]:.2f} bestätigt — Setup ist STÄRKER als das erste (Tradermacher-Lehre)',
                    'stop_hint': f'Stop unter {item["original_stop"]:.2f} (= alter Stop)',
                }
                SIGNALS_LOG.parent.mkdir(parents=True, exist_ok=True)
                with open(SIGNALS_LOG, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(signal, ensure_ascii=False) + '\n')
                signals_generated += 1

                item['status'] = 'RECLAIMED'
                item['reclaimed_at'] = now.isoformat(timespec='seconds')
                item['reclaim_price_eur'] = round(live_eur, 2)
                changes.append(f'RECLAIMED:{ticker} → signal fired')

                # CEO-Inbox
                try:
                    from ceo_inbox import write_event
                    write_event(
                        event_type='re_entry.reclaim',
                        message=f'{ticker}: Fehlausbruch-Reclaim! Original-Entry {item["original_entry"]} wieder erreicht. Setup ist stärker als das ursprüngliche.',
                        severity='info', category='health',
                        user_pinged=False, payload=signal,
                    )
                except Exception: pass

    _save_watchlist(items)
    return {
        'n_watching': sum(1 for i in items if i.get('status') == 'WATCHING'),
        'n_signals': signals_generated,
        'changes': changes,
    }


def auto_add_from_recent_stops() -> dict:
    """Fügt kürzlich ausgestoppte Trades automatisch zur Watchlist hinzu.
    Backfill-Funktion falls paper_exit_manager nicht hooked ist.
    """
    if not DB.exists(): return {}
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = c.execute(
        "SELECT id, ticker, strategy, entry_price, stop_price FROM paper_portfolio "
        "WHERE close_date >= ? AND exit_type LIKE 'STOP%'", (cutoff,)
    ).fetchall()
    c.close()
    added = 0
    for r in rows:
        if r['entry_price'] and r['stop_price']:
            add_to_watchlist(
                r['ticker'], r['entry_price'], r['stop_price'],
                strategy=r['strategy'], trade_id=r['id']
            )
            added += 1
    return {'auto_added': added}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='Daily check for reclaims')
    ap.add_argument('--backfill', action='store_true', help='Auto-add recent stops')
    ap.add_argument('--list', action='store_true', help='List current watchlist')
    args = ap.parse_args()

    if args.list:
        items = _load_watchlist()
        print(json.dumps(items, indent=2, default=str, ensure_ascii=False))
        return 0
    if args.backfill:
        r = auto_add_from_recent_stops()
        print(json.dumps(r, indent=2, default=str))
        return 0
    # Default: check
    r = check_for_reclaims()
    print(json.dumps(r, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
