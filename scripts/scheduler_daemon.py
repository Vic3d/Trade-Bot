#!/usr/bin/env python3.13
"""
TradeMind Scheduler Daemon — Phase 8 / Kostenoptimierung
=========================================================
Läuft 24/7 als Hintergrundprozess.
Ersetzt alle OpenClaw agentTurn-Crons durch direkte Python-Aufrufe.
Kein LLM, keine Token-Kosten, kein Overhead.

Starten:  python3.13 scheduler_daemon.py &
Status:   python3.13 scheduler_daemon.py --status
Stoppen:  python3.13 scheduler_daemon.py --stop
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
SCRIPTS = WS / 'scripts'
PID_FILE = WS / 'data/scheduler.pid'
LOG_FILE = WS / 'data/scheduler.log'

# ── Zeitplan ──────────────────────────────────────────────────────────────────
# Format: (name, script, args, stunde, minute, wochentage)
# wochentage: None = täglich, [0,1,2,3,4] = Mo-Fr, [5] = Sa, [6] = So

SCHEDULE = [
    # Täglich
    # ── Live Data Refresh: 5x täglich (vor jedem wichtigen Job) ──────────────
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             7,  0,  None),   # Morgens
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             9,  0,  None),   # Vor Scanner
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             13, 0,  None),   # Mittags
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             17, 0,  None),   # Nachmittags
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             21, 0,  None),   # Abends
    # ── Watchlist Tracker: alle 30 Min während Marktzeiten ────────────────────
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        9,  0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        9,  30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        10, 0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        10, 30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        11, 0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        11, 30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        12, 0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        12, 30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        13, 0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        13, 30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        14, 0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        14, 30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        15, 0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        15, 30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        16, 0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        16, 30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        17, 0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        17, 30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        18, 0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        18, 30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        19, 0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        19, 30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        20, 0,  [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        20, 30, [0,1,2,3,4]),
    ('Watchlist Tracker',   'watchlist_tracker.py',   [],                        21, 0,  [0,1,2,3,4]),
    ('Strategy Sync',       'core/thesis_engine.py',  ['--sync'],                 7,  3,  None),   # VOR Regime Detector
    ('Regime Detector',     'regime_detector.py',     ['--integrate', '--quick'], 7,  5,  None),
    # ── Reports (discord=True → Output direkt an Victor) ─────────────────────
    # Format: (name, script, args, hour, min, weekdays, discord)
    # Morgen-Briefing: Marktdaten + Ausblick (bleibt, liefert Kontext)
    ('Morgen-Briefing',     'morning_brief_generator.py', [],                    8,  30, [0,1,2,3,4], True),
    # Morgen-Digest: Portfolio-Status + gequeute Alerts aus der Nacht
    ('Morgen-Digest',       'daily_digest.py',            ['morning'],           8,  35, [0,1,2,3,4]),
    # Xetra/US Opening: nur noch ohne discord=True (kein extra Ping)
    ('Xetra Opening',       'us_opening_report.py',       [],                    9,  30, [0,1,2,3,4]),
    ('US Opening',          'us_opening_report.py',       [],                    16, 30, [0,1,2,3,4]),
    # Abend-Digest: Tages-Events + Trades + Lernloop-Summary (ersetzt rohen Abend-Report)
    ('Abend-Digest',        'daily_digest.py',            ['evening'],           20, 0,  [0,1,2,3,4]),
    # Abend-Report: Details (kein extra Discord-Ping mehr, nur als Log)
    ('Abend-Report',        'evening_report.py',          [],                    22, 0,  [0,1,2,3,4]),
    ('Tagesabschluss',      'daily_summary.py',           [],                    23, 0,  None),
    # ─────────────────────────────────────────────────────────────────────────
    ('Performance Tracker', 'performance_tracker.py',  [],                        21, 30, None),  # täglich
    ('Advisory Backfill',   'advisory_layer.py',       ['--backfill'],            22, 0,  [0,1,2,3,4]),  # Mo-Fr
    ('Alpha Decay',         'alpha_decay.py',          [],                        21, 0,  None),
    ('Alt-Data Scrape',     'intelligence/alternative_data.py', [],               6,  0,  None),   # Morgens vor allem anderen
    ('Alt-Data Scrape',     'intelligence/alternative_data.py', ['--source', 'shipping'], 12, 0, None),  # Mittags Shipping-Update
    ('Daily Learning',      'daily_learning_cycle.py', [],                        22, 45, None),
    ('Equity Snapshot',     'equity_snapshot.py',      [],                        22, 50, [0,1,2,3,4,5,6]),  # Phase 9 — Drawdown Circuit Input
    ('Insider Refresh',     'intelligence/insider_refresh.py', [],                7,  30, [0,1,2,3,4]),  # Phase 10 — SEC Form 4 Mo-Fr
    ('Macro Brain',         'intelligence/macro_brain.py',     [],                7,  45, [0,1,2,3,4,5,6]),  # Phase 11 — FRED Regime tgl.
    ('Macro Brain',         'intelligence/macro_brain.py',     [],                15, 30, [0,1,2,3,4]),  # Phase 11 — US Pre-Open Update
    # ── Phase 12: Auto Deep Dive (nightly verdict refresh, rule-based, no LLM) ──
    ('Auto Deep Dive',      'intelligence/auto_deepdive.py',   [],                2,  30, None),  # tgl. 02:30
    # ── Phase 14: Position Watchdog (alle 2h während Marktzeiten) ──
    ('Position Watchdog',   'position_watchdog.py',            [],                10, 0,  [0,1,2,3,4]),
    ('Position Watchdog',   'position_watchdog.py',            [],                12, 0,  [0,1,2,3,4]),
    ('Position Watchdog',   'position_watchdog.py',            [],                14, 0,  [0,1,2,3,4]),
    ('Position Watchdog',   'position_watchdog.py',            [],                16, 0,  [0,1,2,3,4]),
    ('Position Watchdog',   'position_watchdog.py',            [],                18, 0,  [0,1,2,3,4]),
    ('Position Watchdog',   'position_watchdog.py',            [],                20, 0,  [0,1,2,3,4]),
    # ── Phase 15: Proposal Executor (Entry-Fenster 17-22h CET) ──
    ('Proposal Executor',   'proposal_executor.py',            [],                17, 15, [0,1,2,3,4]),
    ('Proposal Executor',   'proposal_executor.py',            [],                18, 15, [0,1,2,3,4]),
    ('Proposal Executor',   'proposal_executor.py',            [],                19, 15, [0,1,2,3,4]),
    ('Proposal Executor',   'proposal_executor.py',            [],                20, 15, [0,1,2,3,4]),
    ('Proposal Executor',   'proposal_executor.py',            [],                21, 15, [0,1,2,3,4]),
    # ── Phase 13: Autonomous Pipeline Orchestrator (3x tgl Mo-Fr) ──
    ('Autonomous Pipeline', 'autonomous_pipeline.py',          [],                11, 0,  [0,1,2,3,4]),
    ('Autonomous Pipeline', 'autonomous_pipeline.py',          [],                15, 0,  [0,1,2,3,4]),
    ('Autonomous Pipeline', 'autonomous_pipeline.py',          [],                19, 0,  [0,1,2,3,4]),
    # ── Phase 16: Signal-Level Learning (Sonntag Vormittag) ──
    ('Signal Learning',     'intelligence/signal_learning.py', [],                9,  30, [6]),
    ('RL Training',         'rl_trainer.py',           ['--train', '200000'],     2,  0,  None),
    # ── Thesis Monitoring: alle 30 Min — prüft Kill-Trigger gegen News ──────────
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             9,  0,  [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             9,  30, [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             10, 0,  [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             10, 30, [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             11, 0,  [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             11, 30, [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             12, 0,  [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             12, 30, [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             13, 0,  [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             13, 30, [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             14, 0,  [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             14, 30, [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             15, 0,  [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             15, 30, [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             16, 0,  [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             16, 30, [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             17, 0,  [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             17, 30, [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             18, 0,  [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             18, 30, [0,1,2,3,4]),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             21, 0,  [0,1,2,3,4]),
    # ─────────────────────────────────────────────────────────────────────────
    ('CEO Radar Nacht',     'news_ceo_radar.py',       [],                        2,  0,  None),
    ('CEO Radar Morgen',    'news_ceo_radar.py',       [],                        7,  0,  None),
    ('Newswire Analyst',    'newswire_analyst.py',     [],                        9,  0,  None),
    ('News Gate Update',    'news_gate_updater.py',    [],                        9,  5,  None),
    ('CEO Radar',           'news_ceo_radar.py',       [],                        9,  10, None),
    ('Newswire Analyst',    'newswire_analyst.py',     [],                        13, 0,  None),
    ('News Gate Update',    'news_gate_updater.py',    [],                        13, 5,  None),
    ('CEO Radar',           'news_ceo_radar.py',       [],                        13, 10, None),
    ('Newswire Analyst',    'newswire_analyst.py',     [],                        17, 0,  None),
    ('News Gate Update',    'news_gate_updater.py',    [],                        17, 5,  None),
    ('CEO Radar',           'news_ceo_radar.py',       [],                        17, 10, None),
    ('Newswire Analyst',    'newswire_analyst.py',     [],                        21, 0,  None),
    ('News Gate Update',    'news_gate_updater.py',    [],                        21, 5,  None),
    ('CEO Radar',           'news_ceo_radar.py',       [],                        21, 10, None),
    # Mo-Fr
    ('Feature Analyzer',    'feature_analyzer.py',     ['--quick'],               11, 30, [5]),   # Sa
    ('Backtest Engine',     'backtest_engine.py',      ['--quick'],               9,  0,  [6]),   # So
    ('Backtest v2',         'backtest_engine_v2.py',   [],                        8,  0,  [2]),   # Mi — Mid-Week Validierung
    ('Strategy DNA',        'strategy_dna.py',         [],                        12, 0,  [5]),   # Sa
    ('Strategy Discovery',  'strategy_discovery.py',   [],                        14, 0,  [5]),   # Sa
    ('Feature Importance',  'feature_importance.py',   [],                        22, 30, [4]),   # Fr
    # ── Phase 6: Autonome Thesen-Entdeckung ──────────────────────────────────
    ('Thesis Discovery',   'intelligence/thesis_discovery.py', [],              7,  0,  [0,1,2,3,4,5,6]),  # täglich 07:00
    # ── Event Calendar: täglich 07:30 ────────────────────────────────────────
    ('Event Calendar',     'event_calendar.py',                [],              7,  30, None),   # täglich 07:30
    # ── Thesis News Hunter: Stündlich 09-22h — max 1h Reaktionszeit ─────────
    # --hours 2: schaut nur 2h zurück → kein Duplikat-Spam, schnelle Reaktion
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  9,  0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  10, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  11, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  12, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  13, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  14, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  15, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  16, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  17, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  18, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  19, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  20, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  21, 0,  [0,1,2,3,4]),
    ('Thesis Hunter',      'thesis_news_hunter.py', ['--hours', '2'],  22, 0,  [0,1,2,3,4]),
    # ── Broad News Scanner: Breaking News alle 30min — zero API-Kosten ───────
    ('Broad Scanner',      'broad_news_scanner.py',            [],              9,  0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              9,  30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              10, 0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              10, 30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              11, 0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              11, 30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              12, 0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              12, 30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              13, 0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              13, 30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              14, 0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              14, 30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              15, 0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              15, 30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              16, 0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              16, 30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              17, 0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              17, 30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              18, 0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              18, 30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              19, 0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              19, 30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              20, 0,  [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              20, 30, [0,1,2,3,4]),
    ('Broad Scanner',      'broad_news_scanner.py',            [],              21, 0,  [0,1,2,3,4]),
    # ── Autonomous CEO: KI-Gehirn läuft alle 2h während Marktzeiten ──────────
    ('Autonomous CEO',     'autonomous_ceo.py',               [],               9,  30, [0,1,2,3,4]),  # 09:30 CET
    ('Autonomous CEO',     'autonomous_ceo.py',               [],               11, 30, [0,1,2,3,4]),  # 11:30 CET
    ('Autonomous CEO',     'autonomous_ceo.py',               [],               13, 30, [0,1,2,3,4]),  # 13:30 CET
    ('Autonomous CEO',     'autonomous_ceo.py',               [],               15, 30, [0,1,2,3,4]),  # 15:30 CET (US Pre-Market)
    ('Autonomous CEO',     'autonomous_ceo.py',               [],               17, 30, [0,1,2,3,4]),  # 17:30 CET (US Open)
    ('Autonomous CEO',     'autonomous_ceo.py',               [],               20, 0,  [0,1,2,3,4]),  # 20:00 CET (US Session)
]


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')
    # Log auf 5000 Zeilen begrenzen
    try:
        lines = LOG_FILE.read_text().splitlines()
        if len(lines) > 5000:
            LOG_FILE.write_text('\n'.join(lines[-4000:]) + '\n')
    except Exception:
        pass


# ── Discord ───────────────────────────────────────────────────────────────────

def notify(msg: str):
    """Sendet Discord-Nachricht direkt (kein LLM)."""
    try:
        sys.path.insert(0, str(SCRIPTS))
        from discord_sender import send
        send(msg)
    except Exception as e:
        log(f'Discord-Fehler: {e}')


# ── Job Runner ────────────────────────────────────────────────────────────────

HEARTBEAT_FILE = WS / 'data/scheduler_heartbeat.txt'


def write_heartbeat():
    """Schreibt aktuellen Timestamp als Heartbeat-Signal."""
    try:
        HEARTBEAT_FILE.write_text(datetime.now(timezone.utc).isoformat())
    except Exception:
        pass


def check_heartbeat_age() -> tuple[bool, str]:
    """Prüft ob Heartbeat frisch ist. Gibt (ok, reason) zurück."""
    try:
        if not HEARTBEAT_FILE.exists():
            return False, 'Kein Heartbeat-File'
        last = datetime.fromisoformat(HEARTBEAT_FILE.read_text().strip())
        # timezone-aware vergleich
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_sec = (datetime.now(timezone.utc) - last).total_seconds()
        if age_sec > 300:  # > 5 Minuten
            return False, f'Heartbeat veraltet: {age_sec:.0f}s'
        return True, f'OK ({age_sec:.0f}s)'
    except Exception as e:
        return False, f'Heartbeat-Fehler: {e}'


def run_job(name: str, script: str, args: list[str], discord: bool = False) -> bool:
    """Führt ein Script aus. Bei discord=True wird stdout an Victor gesendet."""
    script_path = SCRIPTS / script
    if not script_path.exists():
        log(f'⚠️  {name}: Script nicht gefunden — {script}')
        return False

    log(f'▶️  {name}: Start')
    try:
        result = subprocess.run(
            ['python3.13', str(script_path)] + args,
            capture_output=True, text=True, timeout=3600,
            cwd=str(WS)
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            if discord and output and len(output) > 20 and 'KEIN_SIGNAL' not in output:
                notify(output[:1900])
                log(f'✅ {name}: OK + Discord gesendet')
            else:
                log(f'✅ {name}: OK')
            return True
        else:
            log(f'❌ {name}: Fehler (code {result.returncode})')
            # Vollständiges STDERR in Error-Log speichern (nicht nur 300 Zeichen)
            try:
                error_dir = LOG_FILE.parent / 'errors'
                error_dir.mkdir(exist_ok=True)
                err_file = error_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}__{name.replace(' ', '_')}.log"
                err_file.write_text(result.stderr)
                log(f'   STDERR gespeichert: {err_file.name}')
            except Exception:
                log(f'   STDERR: {result.stderr[-500:]}')
            return False
    except subprocess.TimeoutExpired:
        log(f'⏱️  {name}: Timeout')
        return False
    except Exception as e:
        log(f'💥 {name}: Exception — {e}')
        return False


# ── Scheduler Loop ────────────────────────────────────────────────────────────

def should_run(hour: int, minute: int, weekdays) -> bool:
    """Prüft ob ein Job jetzt laufen soll (innerhalb ±30s Fenster)."""
    now = datetime.now()
    if now.hour != hour or abs(now.minute - minute) > 0:
        return False
    if weekdays is not None and now.weekday() not in weekdays:
        return False
    return True


def start_price_monitor():
    """Startet den Price Monitor als Hintergrund-Prozess."""
    import subprocess as _sp
    monitor_pid_file = WS / 'data/price_monitor.pid'

    # Prüfen ob bereits läuft
    if monitor_pid_file.exists():
        try:
            pid = int(monitor_pid_file.read_text().strip())
            os.kill(pid, 0)  # 0 = nur prüfen ob läuft
            return  # Läuft schon
        except (ProcessLookupError, ValueError):
            pass  # PID tot → neu starten

    proc = _sp.Popen(
        ['python3.13', str(WS / 'scripts/price_monitor.py')],
        start_new_session=True,
        stdout=open(str(WS / 'data/price_monitor.log'), 'a'),
        stderr=_sp.STDOUT,
    )
    log(f'📡 Price Monitor gestartet (PID {proc.pid})')


def scheduler_loop():
    """Haupt-Schleife — prüft jede Minute ob Jobs laufen sollen."""
    log('🚀 TradeMind Scheduler Daemon gestartet')

    # Startup-Nachricht nur einmal pro Tag — nicht bei jedem Watchdog-Neustart
    startup_flag = WS / 'data/scheduler_started_today.txt'
    today_str = datetime.now().strftime('%Y-%m-%d')
    if not startup_flag.exists() or startup_flag.read_text().strip() != today_str:
        notify('🤖 **TradeMind** online')
        startup_flag.write_text(today_str)

    # Price Monitor sofort starten
    start_price_monitor()

    # Albert Discord-Chat-Thread starten
    try:
        sys.path.insert(0, str(SCRIPTS))
        import discord_chat
        chat_thread = threading.Thread(target=discord_chat.run_forever, daemon=True, name='AlbertChat')
        chat_thread.start()
        log('💬 Albert Discord-Chat-Thread gestartet')
    except Exception as e:
        log(f'⚠️  Albert Discord-Chat konnte nicht gestartet werden: {e}')

    last_run = {}  # Verhindert Doppel-Ausführungen

    while True:
        now = datetime.now()
        current_key = f'{now.strftime("%Y-%m-%d %H:%M")}'

        for entry in SCHEDULE:
            name, script, args, hour, minute, weekdays = entry[:6]
            discord_send = entry[6] if len(entry) > 6 else False

            job_key = f'{name}_{current_key}'
            if job_key in last_run:
                continue

            if should_run(hour, minute, weekdays):
                last_run[job_key] = True
                # Cleanup alter Einträge
                if len(last_run) > 1000:
                    old_keys = list(last_run.keys())[:-500]
                    for k in old_keys:
                        del last_run[k]

                success = run_job(name, script, args, discord=discord_send)

                # Discord-Notification bei Fehler
                if not success:
                    notify(f'⚠️ **Scheduler:** {name} fehlgeschlagen — Logs: data/scheduler.log')

        # Heartbeat nach jeder Minute schreiben
        write_heartbeat()

        # Genau auf nächste Minute warten
        sleep_secs = 60 - datetime.now().second
        time.sleep(max(1, sleep_secs))


# ── PID Management ────────────────────────────────────────────────────────────

def write_pid():
    PID_FILE.write_text(str(os.getpid()))

def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None

def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    args = sys.argv[1:]

    if '--status' in args:
        pid = read_pid()
        if pid and is_running(pid):
            print(f'✅ Scheduler läuft (PID {pid})')
            # Letzte Log-Zeilen
            if LOG_FILE.exists():
                lines = LOG_FILE.read_text().splitlines()
                print('\nLetzte 10 Einträge:')
                for l in lines[-10:]:
                    print(f'  {l}')
        else:
            print('❌ Scheduler läuft NICHT')
            print('   Starte mit: python3.13 scheduler_daemon.py &')

    elif '--stop' in args:
        pid = read_pid()
        if pid and is_running(pid):
            os.kill(pid, signal.SIGTERM)
            PID_FILE.unlink(missing_ok=True)
            print(f'✅ Scheduler (PID {pid}) gestoppt')
        else:
            print('Scheduler läuft nicht')

    elif '--run-now' in args:
        # Manuell einen Job ausführen
        job_name = args[args.index('--run-now') + 1] if len(args) > args.index('--run-now') + 1 else None
        for name, script, job_args, *_ in SCHEDULE:
            if job_name is None or job_name.lower() in name.lower():
                print(f'▶️  Manuell: {name}')
                run_job(name, script, job_args)

    elif '--start' in args or len(args) == 0:
        # Prüfen ob bereits läuft
        pid = read_pid()
        if pid and is_running(pid):
            print(f'⚠️  Scheduler läuft bereits (PID {pid})')
            sys.exit(0)

        write_pid()
        try:
            scheduler_loop()
        except KeyboardInterrupt:
            log('Scheduler gestoppt (KeyboardInterrupt)')
            PID_FILE.unlink(missing_ok=True)
        except Exception as e:
            log(f'💥 Daemon Crash: {e}')
            notify(f'🚨 **TradeMind Scheduler CRASH:** {e}\nNeustart nötig!')
            PID_FILE.unlink(missing_ok=True)
            raise
