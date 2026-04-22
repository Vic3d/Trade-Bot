#!/usr/bin/env python3
"""
One-shot migration: news_events.published_at → ISO 8601 UTC
============================================================
Bug-Fix: news_events speicherte RFC 822-Strings ("Wed, 22 Apr 2026 14:49"),
SQLite date()-Funktionen konnten damit nicht filtern → 7d-Filter lieferten 0 Treffer.

Dieses Script konvertiert alle existierenden Rows in ISO 8601 UTC.
Idempotent — kann mehrfach ausgefuehrt werden.

Run: python3 scripts/maintenance/migrate_news_published_at.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from core.news_pipeline import normalize_published_at  # noqa: E402

DB = WS / 'data' / 'trading.db'


def main():
    if not DB.exists():
        print(f'❌ DB nicht gefunden: {DB}')
        return 1
    conn = sqlite3.connect(str(DB))
    rows = conn.execute(
        "SELECT id, published_at FROM news_events"
    ).fetchall()
    print(f'Gefunden: {len(rows)} Rows')

    converted = 0
    already_iso = 0
    null_filled = 0
    for rid, pub in rows:
        if pub and len(pub) >= 19 and pub[4] == '-' and 'T' in pub:
            already_iso += 1
            continue
        new_val = normalize_published_at(pub)
        if not pub:
            null_filled += 1
        if new_val != pub:
            conn.execute(
                "UPDATE news_events SET published_at = ? WHERE id = ?",
                (new_val, rid),
            )
            converted += 1
    conn.commit()

    # Verifikation: zähle wie viele jetzt im 7d-Fenster filterbar sind
    sevenday = conn.execute(
        "SELECT COUNT(*) FROM news_events "
        "WHERE published_at >= datetime('now', '-7 days')"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM news_events").fetchone()[0]
    conn.close()

    print(f'  Bereits ISO:    {already_iso}')
    print(f'  Konvertiert:    {converted}')
    print(f'  NULL-Fallback:  {null_filled}')
    print(f'  7d-filterbar:   {sevenday}/{total}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
