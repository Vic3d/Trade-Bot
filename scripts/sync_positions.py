#!/usr/bin/env python3
"""
sync_positions.py — Single Source of Truth Sync
=================================================
Liest positions-live.md (einzige Wahrheitsquelle) und synchronisiert:
  1. trading_config.json → positions Array (für Monitor)
  2. trading.db         → open trades (für Paper-Lab und Reporting)

PFLICHT: Nach JEDER Positions-Änderung ausführen.
Wird auch automatisch am Anfang jedes Monitor-Runs aufgerufen.

Usage:
  python3 sync_positions.py          # Sync durchführen
  python3 sync_positions.py --check  # Nur anzeigen, nicht schreiben
"""

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE     = Path(__file__).parent.parent
POSITIONS_MD  = WORKSPACE / 'memory/positions-live.md'
CONFIG_JSON   = WORKSPACE / 'trading_config.json'
DB_PATH       = WORKSPACE / 'data/trading.db'

DRY_RUN = '--check' in sys.argv


def parse_positions_md() -> list[dict]:
    """
    Parst die aktive Positionen-Tabelle aus positions-live.md.
    Format: | Name (Ticker) | Entry | Stop | Letzter Kurs | P&L | Notiz |
    """
    text = POSITIONS_MD.read_text(encoding='utf-8')

    # Finde den aktive Positionen-Block
    active_section = re.search(
        r'## 🟢 Aktive Positionen\s*\n.*?\n\|[-|]+\|\n(.*?)(?=\n---|\n## |\Z)',
        text, re.DOTALL
    )
    if not active_section:
        print("⚠️  Keine aktiven Positionen in positions-live.md gefunden.")
        return []

    rows = []
    for line in active_section.group(1).strip().split('\n'):
        line = line.strip()
        if not line.startswith('|') or line.startswith('|---'):
            continue
        cols = [c.strip() for c in line.strip('|').split('|')]
        if len(cols) < 4:
            continue

        name_ticker = cols[0]  # z.B. "Palantir (PLTR)"
        entry_raw   = cols[1]  # z.B. "132.11€"
        stop_raw    = cols[2]  # z.B. "127.00€"
        kurs_raw    = cols[3]  # z.B. "124.29€" oder "—"
        notiz       = cols[5] if len(cols) > 5 else ''

        # Ticker aus Klammern extrahieren
        ticker_match = re.search(r'\(([^)]+)\)', name_ticker)
        if not ticker_match:
            continue
        ticker = ticker_match.group(1).upper()

        # Name ohne Ticker
        name = re.sub(r'\s*\([^)]+\)', '', name_ticker).strip()

        # Zahlen extrahieren
        def to_float(s):
            s = s.replace('€', '').replace('%', '').strip()
            try:
                return float(s)
            except (ValueError, TypeError):
                return None

        entry = to_float(entry_raw)
        stop  = to_float(stop_raw)
        kurs  = to_float(kurs_raw.replace('—', ''))

        if entry is None:
            continue

        rows.append({
            'ticker':  ticker,
            'name':    name,
            'entry':   entry,
            'stop':    stop,
            'current': kurs,
            'note':    notiz.strip(),
        })

    return rows


def sync_to_config(positions: list[dict]):
    """Aktualisiert trading_config.json positions (dict-Format: {TICKER: {...}})."""
    cfg = json.loads(CONFIG_JSON.read_text(encoding='utf-8'))

    config_positions = cfg.get('positions', {})
    # Normalisiere: kann dict oder list sein
    if isinstance(config_positions, list):
        # Konvertiere list → dict
        config_positions = {p['ticker'].upper(): p for p in config_positions if isinstance(p, dict) and 'ticker' in p}

    updated = 0
    added   = 0

    for pos in positions:
        ticker = pos['ticker']
        if ticker in config_positions:
            # Stop aktualisieren (stop_eur Feld)
            entry_cfg = config_positions[ticker]
            old_stop = entry_cfg.get('stop_eur') or entry_cfg.get('stop')
            new_stop = pos['stop']
            if new_stop is not None and old_stop != new_stop:
                if 'stop_eur' in entry_cfg:
                    entry_cfg['stop_eur'] = new_stop
                else:
                    entry_cfg['stop'] = new_stop
                print(f"  📝 {ticker}: Stop {old_stop} → {new_stop}")
                updated += 1
            else:
                print(f"  ✓  {ticker}: Stop unverändert ({old_stop})")
        else:
            # Neue Position anlegen
            config_positions[ticker] = {
                'name':        pos['name'],
                'yahoo':       ticker,
                'currency':    'EUR',
                'entry_eur':   pos['entry'],
                'stop_eur':    pos['stop'],
                'targets_eur': [],
                'notes':       pos['note'],
                'strategy':    'manual',
            }
            print(f"  ➕ {ticker} neu in Config eingefügt")
            added += 1

    cfg['positions'] = config_positions

    if not DRY_RUN:
        CONFIG_JSON.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
    print(f"  Config: {updated} aktualisiert, {added} hinzugefügt")


def sync_to_db(positions: list[dict]):
    """Synchronisiert aktive Positionen in trading.db."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    updated = 0
    inserted = 0
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')

    for pos in positions:
        ticker = pos['ticker']

        # Suche existierenden Real-Trade (nicht day_trade)
        existing = db.execute(
            "SELECT id, stop, entry_price FROM trades WHERE ticker=? AND status='OPEN' AND trade_type='real'",
            (ticker,)
        ).fetchone()

        if existing:
            # Stop updaten
            old_stop = existing['stop']
            new_stop = pos['stop']
            if new_stop is not None and old_stop != new_stop:
                if not DRY_RUN:
                    db.execute(
                        "UPDATE trades SET stop=? WHERE id=?",
                        (new_stop, existing['id'])
                    )
                print(f"  🗄️  DB {ticker}: Stop {old_stop} → {new_stop}")
                updated += 1
        else:
            # Neuen Eintrag anlegen
            if not DRY_RUN and pos['entry']:
                db.execute("""
                    INSERT INTO trades
                    (ticker, strategy, direction, entry_price, entry_date, stop, status,
                     trade_type, portfolio_type, thesis)
                    VALUES (?, 'manual', 'LONG', ?, ?, ?, 'OPEN', 'real', 'real', ?)
                """, (
                    ticker,
                    pos['entry'],
                    now[:10],
                    pos['stop'],
                    pos['note'] or f"Manuell importiert aus positions-live.md"
                ))
                print(f"  🗄️  DB {ticker}: Neu angelegt (Entry {pos['entry']}€, Stop {pos['stop']}€)")
                inserted += 1

        # Positionen die in DB offen sind, aber nicht mehr in positions-live.md → schließen
    live_tickers = {p['ticker'] for p in positions}
    open_real = db.execute(
        "SELECT id, ticker FROM trades WHERE status='OPEN' AND trade_type='real'"
    ).fetchall()
    closed = 0
    for row in open_real:
        if row['ticker'].upper() not in live_tickers:
            if not DRY_RUN:
                db.execute(
                    "UPDATE trades SET status='CLOSED', exit_date=? WHERE id=?",
                    (now[:10], row['id'])
                )
            print(f"  🗄️  DB {row['ticker']}: Als CLOSED markiert (nicht mehr aktiv)")
            closed += 1

    if not DRY_RUN:
        db.commit()
    db.close()
    print(f"  DB: {updated} aktualisiert, {inserted} neu, {closed} geschlossen")


def main():
    print("🔄 POSITIONS SYNC — Single Source of Truth")
    print(f"   Quelle: {POSITIONS_MD.name}")
    print(f"   Modus:  {'DRY RUN (--check)' if DRY_RUN else 'LIVE SYNC'}")
    print()

    positions = parse_positions_md()
    if not positions:
        print("❌ Keine Positionen gefunden — Abbruch.")
        return

    print(f"📋 {len(positions)} aktive Positionen gefunden:")
    for p in positions:
        stop_str = f"Stop: {p['stop']}€" if p['stop'] else "kein Stop"
        print(f"   {p['ticker']:10} Entry: {p['entry']}€ | {stop_str}")
    print()

    print("📤 Sync → trading_config.json:")
    sync_to_config(positions)
    print()

    print("📤 Sync → trading.db:")
    sync_to_db(positions)
    print()

    if not DRY_RUN:
        # Timestamp in positions-live.md updaten
        ts = datetime.now().strftime('%Y-%m-%d %H:%M CET')
        text = POSITIONS_MD.read_text(encoding='utf-8')
        text = re.sub(
            r'\*\*Zuletzt aktualisiert:\*\*.*',
            f'**Zuletzt aktualisiert:** {ts} (Auto-Sync)',
            text
        )
        POSITIONS_MD.write_text(text, encoding='utf-8')

        # ── Dashboard neu generieren ──────────────────────────────────────────
        print()
        print("📊 Dashboard neu generieren (generate_dashdata.py)...")
        gen_script = Path(__file__).parent / 'generate_dashdata.py'
        if gen_script.exists():
            import subprocess
            result = subprocess.run(
                ['python3', str(gen_script)],
                capture_output=True, text=True, timeout=30,
                cwd=str(WORKSPACE)
            )
            if result.returncode == 0:
                print("  ✅ dashdata.js aktualisiert")
            else:
                print(f"  ⚠️  generate_dashdata.py Fehler: {result.stderr[:300]}")
        else:
            print("  ⚠️  generate_dashdata.py nicht gefunden — Dashboard nicht aktualisiert")

        print(f"\n✅ Sync abgeschlossen — {ts}")
    else:
        print("✅ Dry-Run abgeschlossen — keine Änderungen geschrieben")


if __name__ == '__main__':
    main()
