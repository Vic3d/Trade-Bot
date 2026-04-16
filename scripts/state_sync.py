#!/usr/bin/env python3
"""
State Sync — Phase 3 (Single Source of Truth, Read-Through)
============================================================

Spiegelt die drei kritischen JSON-Dateien in strukturierte SQLite-Tabellen.

Warum parallel und nicht ersetzen?
----------------------------------
26 Scripts lesen aktuell direkt aus den JSONs. Eine Big-Bang-Migration wäre
fragil. Stattdessen:
  - JSONs bleiben die Quelle für Read-Access aller bestehenden Scripts.
  - SQL ist die Quelle für Queries (Historie, Analytics, Discord-Reports).
  - state_sync läuft als Step nach daily_learning und nach jedem CEO-Run.

Tabellen
--------
verdicts_current    — aktueller Snapshot aller Deep-Dive-Verdicts
verdicts_history    — jede Verdict-Änderung, append-only (für Flip-Analyse)
directive_history   — jede ceo_directive.json Änderung (max/allowed/blocked)
strategy_scores_hist— strategy_scores aus trading_learnings.json pro Tag

CLI
---
  python3 scripts/state_sync.py          # vollständiger Sync
  python3 scripts/state_sync.py --verify # nur verifizieren
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
DB = DATA / 'trading.db'

VERDICTS_FILE = DATA / 'deep_dive_verdicts.json'
DIRECTIVE_FILE = DATA / 'ceo_directive.json'
LEARNINGS_FILE = DATA / 'trading_learnings.json'


SCHEMA = """
CREATE TABLE IF NOT EXISTS verdicts_current (
    ticker         TEXT PRIMARY KEY,
    verdict        TEXT NOT NULL,
    source         TEXT,
    analyst        TEXT,
    verdict_date   TEXT,
    timestamp      TEXT,
    age_days       INTEGER,
    has_key_findings INTEGER,
    entry          TEXT,
    stop           TEXT,
    ziel_1         TEXT,
    trigger        TEXT,
    warum_nicht_jetzt TEXT,
    raw_json       TEXT,
    synced_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verdicts_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT NOT NULL,
    verdict       TEXT NOT NULL,
    source        TEXT,
    verdict_date  TEXT,
    synced_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verdicts_hist_ticker ON verdicts_history(ticker);
CREATE INDEX IF NOT EXISTS idx_verdicts_hist_ts     ON verdicts_history(synced_at);

CREATE TABLE IF NOT EXISTS directive_history (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    synced_at                 TEXT NOT NULL,
    mode                      TEXT,
    mode_reason               TEXT,
    phase                     TEXT,
    vix                       REAL,
    regime                    TEXT,
    geo_alert_level           TEXT,
    max_new_positions_today   INTEGER,
    max_position_size_eur     REAL,
    allowed_strategies_count  INTEGER,
    blocked_strategies_count  INTEGER,
    allowed_strategies_json   TEXT,
    blocked_strategies_json   TEXT,
    raw_json                  TEXT
);
CREATE INDEX IF NOT EXISTS idx_directive_ts ON directive_history(synced_at);

CREATE TABLE IF NOT EXISTS strategy_scores_hist (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    synced_at         TEXT NOT NULL,
    strategy_id       TEXT NOT NULL,
    win_rate          REAL,
    avg_pnl_pct       REAL,
    total_pnl_eur     REAL,
    trades            INTEGER,
    risk_adj_return   REAL,
    recommendation    TEXT,
    source            TEXT
);
CREATE INDEX IF NOT EXISTS idx_scores_hist_sid ON strategy_scores_hist(strategy_id);
CREATE INDEX IF NOT EXISTS idx_scores_hist_ts  ON strategy_scores_hist(synced_at);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _now_iso() -> str:
    return datetime.now(_BERLIN).isoformat()


def _age_days(ts_str: str) -> int:
    try:
        if 'T' in ts_str:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_BERLIN)
        else:
            ts = datetime.strptime(ts_str, '%Y-%m-%d').replace(tzinfo=_BERLIN)
        return (datetime.now(_BERLIN) - ts).days
    except Exception:
        return 999


def _load(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f'[state_sync] load {path.name} failed: {e}', file=sys.stderr)
    return default


# ── Sync-Funktionen ──────────────────────────────────────────────────────────

def sync_verdicts(conn: sqlite3.Connection) -> int:
    """Spiegelt deep_dive_verdicts.json → verdicts_current + history."""
    data = _load(VERDICTS_FILE, {})
    if not isinstance(data, dict):
        return 0

    now = _now_iso()
    conn.execute('DELETE FROM verdicts_current')  # full snapshot replace

    rows_current = []
    rows_history = []
    for ticker, v in data.items():
        if not isinstance(v, dict):
            continue
        ts = v.get('timestamp') or v.get('date', '')
        source = v.get('source') or v.get('analyst', '')
        rows_current.append((
            ticker.upper(),
            v.get('verdict', '?'),
            source,
            v.get('analyst', ''),
            v.get('date', ''),
            ts,
            _age_days(ts),
            1 if 'key_findings' in v else 0,
            str(v.get('entry', '') or ''),
            str(v.get('stop', '') or ''),
            str(v.get('ziel_1', '') or ''),
            str(v.get('trigger', '') or ''),
            str(v.get('warum_nicht_jetzt', '') or '')[:500],
            json.dumps(v, ensure_ascii=False),
            now,
        ))
        # Nur als History-Eintrag schreiben wenn neu ODER Verdict anders als letzter Eintrag
        last = conn.execute(
            'SELECT verdict FROM verdicts_history WHERE ticker=? ORDER BY id DESC LIMIT 1',
            (ticker.upper(),),
        ).fetchone()
        if last is None or last[0] != v.get('verdict'):
            rows_history.append((
                ticker.upper(),
                v.get('verdict', '?'),
                source,
                v.get('date', ''),
                now,
            ))

    conn.executemany(
        """INSERT INTO verdicts_current
           (ticker, verdict, source, analyst, verdict_date, timestamp, age_days,
            has_key_findings, entry, stop, ziel_1, trigger, warum_nicht_jetzt,
            raw_json, synced_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows_current,
    )
    if rows_history:
        conn.executemany(
            """INSERT INTO verdicts_history
               (ticker, verdict, source, verdict_date, synced_at)
               VALUES (?,?,?,?,?)""",
            rows_history,
        )
    conn.commit()
    return len(rows_current)


def sync_directive(conn: sqlite3.Connection) -> int:
    """Schreibt aktuellen ceo_directive.json Zustand als History-Row."""
    data = _load(DIRECTIVE_FILE, {})
    if not isinstance(data, dict) or not data:
        return 0
    rules = data.get('trading_rules', {}) or {}
    allowed = rules.get('allowed_strategies', []) or []
    blocked = rules.get('blocked_strategies', []) or []
    conn.execute(
        """INSERT INTO directive_history
           (synced_at, mode, mode_reason, phase, vix, regime, geo_alert_level,
            max_new_positions_today, max_position_size_eur,
            allowed_strategies_count, blocked_strategies_count,
            allowed_strategies_json, blocked_strategies_json, raw_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            _now_iso(),
            data.get('mode', ''),
            (data.get('mode_reason', '') or '')[:500],
            str(data.get('phase', '')),
            float(data.get('vix') or 0.0),
            data.get('regime', ''),
            data.get('geo_alert_level', ''),
            int(rules.get('max_new_positions_today') or 0),
            float(rules.get('max_position_size_eur') or 0.0),
            len(allowed),
            len(blocked),
            json.dumps(allowed),
            json.dumps(blocked),
            json.dumps(data, ensure_ascii=False)[:32000],
        ),
    )
    conn.commit()
    return 1


def sync_learnings(conn: sqlite3.Connection) -> int:
    """Schreibt strategy_scores als History-Row (1 Row pro Strategie pro Sync)."""
    data = _load(LEARNINGS_FILE, {})
    scores = data.get('strategy_scores', {}) if isinstance(data, dict) else {}
    if not scores:
        return 0
    now = _now_iso()
    rows = []
    for sid, s in scores.items():
        if not isinstance(s, dict):
            continue
        rows.append((
            now,
            sid,
            float(s.get('win_rate') or 0.0),
            float(s.get('avg_pnl_pct') or 0.0),
            float(s.get('total_pnl_eur') or 0.0),
            int(s.get('trades') or 0),
            float(s.get('risk_adj_return') or 0.0),
            s.get('recommendation', ''),
            s.get('source', ''),
        ))
    conn.executemany(
        """INSERT INTO strategy_scores_hist
           (synced_at, strategy_id, win_rate, avg_pnl_pct, total_pnl_eur,
            trades, risk_adj_return, recommendation, source)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


# ── Orchestrierung ───────────────────────────────────────────────────────────

def run_sync() -> dict:
    conn = sqlite3.connect(str(DB))
    try:
        _ensure_schema(conn)
        n_v = sync_verdicts(conn)
        n_d = sync_directive(conn)
        n_s = sync_learnings(conn)
    finally:
        conn.close()
    return {'verdicts': n_v, 'directive': n_d, 'strategy_scores': n_s}


def verify() -> dict:
    conn = sqlite3.connect(str(DB))
    try:
        _ensure_schema(conn)
        counts = {}
        for table in (
            'verdicts_current', 'verdicts_history',
            'directive_history', 'strategy_scores_hist',
        ):
            counts[table] = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        latest_verdicts = conn.execute(
            'SELECT ticker, verdict, source, age_days FROM verdicts_current ORDER BY ticker'
        ).fetchall()
    finally:
        conn.close()
    return {'counts': counts, 'verdicts': latest_verdicts}


if __name__ == '__main__':
    if '--verify' in sys.argv:
        res = verify()
        print('Row counts:')
        for t, n in res['counts'].items():
            print(f'  {t:25s} {n}')
        print('\nCurrent verdicts:')
        for ticker, verdict, source, age in res['verdicts']:
            print(f'  {ticker:10s} {verdict:14s} {source:40s} age={age}d')
    else:
        res = run_sync()
        print(f'[state_sync] OK — verdicts={res["verdicts"]}, '
              f'directive={res["directive"]}, strategy_scores={res["strategy_scores"]}')
