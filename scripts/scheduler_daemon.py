#!/usr/bin/env python3
"""
TradeMind Scheduler Daemon — Phase 8 / Kostenoptimierung
=========================================================
Läuft 24/7 als Hintergrundprozess.
Ersetzt alle OpenClaw agentTurn-Crons durch direkte Python-Aufrufe.
Kein LLM, keine Token-Kosten, kein Overhead.

Starten:  python3 scheduler_daemon.py &
Status:   python3 scheduler_daemon.py --status
Stoppen:  python3 scheduler_daemon.py --stop
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

_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(os.getenv('TRADEMIND_HOME', _default_ws))
SCRIPTS = WS / 'scripts'
PID_FILE = WS / 'data/scheduler.pid'
LOG_FILE = WS / 'data/scheduler.log'
PYTHON = sys.executable  # Use the same Python that's running this script

# ── Zeitplan ──────────────────────────────────────────────────────────────────
# Format: (name, script, args, stunde, minute, wochentage)
# wochentage: None = täglich, [0,1,2,3,4] = Mo-Fr, [5] = Sa, [6] = So

SCHEDULE = [
    # Täglich
    # ── Live Data Refresh: 8x taeglich — Asien + EU + US Coverage ────────────
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             1,  0,  None),   # Asien Morgen
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             4,  0,  None),   # Asien Close
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             7,  0,  None),   # EU Pre-Market
    ('CEO Direktive',       'ceo.py',                 ['--live'],                7,  5,  [0,1,2,3,4]),  # Mo-Fr 07:05: schreibt ceo_directive.json
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             9,  0,  None),   # EU Open
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             13, 0,  None),   # Mittags
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             14, 0,  None),   # US Pre-Market
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             17, 0,  None),   # US Nachmittag
    ('Live Data Refresh',   'core/live_data.py',      ['--refresh'],             21, 0,  None),   # US Close / Abend
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
    # Phase 7.15 Fix — Cache befuellen BEVOR Regime-Detector laeuft
    ('Regime Cache Refresh','regime_cache_refresh.py', [],                        6,  55, None),
    ('Regime Detector',     'regime_detector.py',     ['--integrate', '--quick'], 7,  5,  None),
    # Phase 7.15 — Discovery (Ticker-Findung)
    # News Extractor laeuft 4x/Tag, 7d/Woche (Nachrichten schlafen nicht — intraday-Coverage)
    ('Discovery News',      'discovery/news_ticker_extractor.py', [],             6,  0,  None,        False),
    ('Discovery News',      'discovery/news_ticker_extractor.py', [],             12, 0,  None,        False),
    ('Discovery News',      'discovery/news_ticker_extractor.py', [],             17, 0,  None,        False),
    ('Discovery News',      'discovery/news_ticker_extractor.py', [],             22, 0,  None,        False),
    # Market Scanner + Earnings nur Mo-Fr (Maerkte geschlossen am WE)
    ('Discovery Market',    'discovery/market_scanner.py',        [],             6,  15, [0,1,2,3,4], False),
    ('Discovery Earnings',  'discovery/earnings_calendar.py',     [],             6,  30, [0,1,2,3,4], False),
    # Price-Backfill: laedt Historie fuer neu discovered Tickers (Auto-DD braucht >=60d)
    ('Discovery Price BF',  'discovery/price_backfill.py',        [],             6,  45, [0,1,2,3,4], False),
    # Pipeline: nach Auto-DD (07:30) — promoted/rejected auf Basis der neuen Verdikts
    ('Discovery Pipeline',  'discovery/discovery_pipeline.py',    [],             12, 0,  [0,1,2,3,4], True),
    # ── Overnight Events sammeln — 24/7, auch Asien-Session ────────────────
    ('Overnight Collector', 'overnight_collector.py',  [],                        1,  0,  None),   # Asien Morgen (10:00 JST)
    ('Overnight Collector', 'overnight_collector.py',  [],                        4,  0,  None),   # Asien Close (13:00 JST)
    ('Overnight Collector', 'overnight_collector.py',  [],                        7,  10, None),   # EU Pre-Market
    ('Overnight Collector', 'overnight_collector.py',  [],                        8,  25, [0,1,2,3,4]),  # vor Briefing
    ('Overnight Collector', 'overnight_collector.py',  [],                        14, 0,  [0,1,2,3,4]),  # US Opening
    ('Overnight Collector', 'overnight_collector.py',  [],                        20, 30, [0,1,2,3,4]),  # US Close
    # ── Reports (discord=True → Output direkt an Victor) ─────────────────────
    # Format: (name, script, args, hour, min, weekdays, discord)
    ('Morgen-Briefing',     'morning_brief_generator.py', [],                    8,  30, [0,1,2,3,4], True),
    ('Xetra Opening',       'us_opening_report.py',       [],                    9,  30, [0,1,2,3,4], True),
    ('US Opening',          'us_opening_report.py',       [],                    16, 30, [0,1,2,3,4], True),
    ('Abend-Report',        'evening_report.py',          [],                    22, 0,  [0,1,2,3,4], True),
    ('Tagesabschluss',      'daily_summary.py',           [],                    23, 0,  None,        True),
    # Phase 7.11 — Ritual-Ebene (reflektiv, nicht metriklastig)
    ('Daily Review',        'daily_review.py',            [],                    22, 15, [0,1,2,3,4], True),  # Mo-Fr 22:15
    ('Weekly Summary',      'weekly_summary.py',          [],                    21, 0,  [6],         True),  # So 21:00
    # ── Phase 22 — Opportunity Engine (laeuft VOR Auto-Deep-Dive) ────────────
    ('Smart Money Tracker', 'discovery/smart_money_tracker.py', [],                6,  10, [0,1,2,3,4], True),
    ('Catalyst Calendar',   'catalyst_calendar.py',             [],                6,  20, None,        True),
    ('Scenario Mapper',     'scenario_mapper.py',               [],                6,  30, [0,1,2,3,4], True),
    ('Pain Trade Scanner',  'pain_trade_scanner.py',            [],                7,  0,  None,        True),
    ('Thesis Generator',    'thesis_generator.py',              [],                7,  15, [0,1,2,3,4], True),
    # Backfill NACH Thesis-Generator (neue Kandidaten brauchen Preisdaten fuer Auto-DD 07:30)
    ('Discovery Price BF',  'discovery/price_backfill.py',      [],                7,  22, [0,1,2,3,4], False),
    ('Thesis Generator',    'thesis_generator.py',              [],                19, 15, [0,1,2,3,4], True),
    ('Discovery Price BF',  'discovery/price_backfill.py',      [],                19, 22, [0,1,2,3,4], False),
    ('Thesis Graveyard',    'thesis_graveyard.py',              [],                23, 30, None,        True),
    # ── Phase 22.1: Portfolio Circuit Breaker — Tages-Snapshot vor Schluss ────
    ('Equity Snapshot',     'portfolio_circuit_breaker.py',     ['--record-close'], 21, 45, None,      False),
    # Phase 7.14 — Auto-Deep-Dive via Claude API (sonnet)
    # Mo-Fr 07:30: full run (offene Positionen + Entry-Kandidaten)
    ('Auto Deep Dive',      'auto_deep_dive_runner.py',   ['full'],              7,  30, [0,1,2,3,4], True),
    # Mo-Fr 13:30: nur offene Positionen (force refresh — Leichen im Keller intraday)
    ('Auto Deep Dive',      'auto_deep_dive_runner.py',   ['open-only'],         13, 30, [0,1,2,3,4], True),
    # Mo-Fr 19:30: nur offene Positionen (vor Entry-Window)
    ('Auto Deep Dive',      'auto_deep_dive_runner.py',   ['open-only'],         19, 30, [0,1,2,3,4], True),
    # So 20:00: full run (Asien-Vorschau fuer Montag)
    ('Auto Deep Dive',      'auto_deep_dive_runner.py',   ['full'],              20, 0,  [6],         True),
    # ─────────────────────────────────────────────────────────────────────────
    ('Performance Tracker', 'performance_tracker.py',  [],                        21, 30, None),  # täglich
    ('Advisory Backfill',   'advisory_layer.py',       ['--backfill'],            22, 0,  [0,1,2,3,4]),  # Mo-Fr
    ('Alpha Decay',         'alpha_decay.py',          [],                        21, 0,  None),
    ('Daily Learning',      'daily_learning_cycle.py', [],                        22, 45, None),
    ('RL Training',         'rl_trainer.py',           ['--train', '200000'],     2,  0,  None),
    # ── Geo-Watcher: stuetzen PS1 (Iran-Oel) + PS17/18 (Trade-War) ────────────
    # Beide lightweight RSS-Scraper, stuendlich aktive Stunden (07-23) 7d/Woche
    # Sofort-Alert via Discord bei Peace-Signal / Trump-Post mit Iran-Keywords
]
_GEO_HOURS = list(range(7, 24))  # 07-23 CET
SCHEDULE += [('Iran Peace Watch', 'iran_peace_watch.py', [], h, 5, None) for h in _GEO_HOURS]
SCHEDULE += [('Trump Watch',      'trump_watch.py',      [], h, 15, None) for h in _GEO_HOURS]
# Phase 22.1 — Event-Auto-Exit: laeuft 5 Min nach jedem Watch-Job (x:20),
# prueft auf neue Signale und triggert force_close bei betroffenen Thesen.
SCHEDULE += [('Event Auto-Exit', 'event_auto_exit.py', [], h, 20, None) for h in _GEO_HOURS]
SCHEDULE += [
    # ── Thesis Monitoring: 24/7 — Kill-Trigger kennen keine Marktzeiten ────────
    # Asien-Session (00:00-06:00 UTC) — alle 2h
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             0,  0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             2,  0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             4,  0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             6,  0,  None),
    # EU+US-Session (07:00-21:00 UTC) — alle 30 Min, taeglich
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             7,  30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             8,  0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             8,  30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             9,  0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             9,  30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             10, 0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             10, 30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             11, 0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             11, 30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             12, 0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             12, 30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             13, 0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             13, 30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             14, 0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             14, 30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             15, 0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             15, 30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             16, 0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             16, 30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             17, 0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             17, 30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             18, 0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             18, 30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             19, 0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             19, 30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             20, 0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             20, 30, None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             21, 0,  None),
    # ─────────────────────────────────────────────────────────────────────────
    # ── News Pipeline: 8x taeglich — Asien + EU + US Coverage ─────────────────
    # Asien-Session
    ('CEO Radar Nacht',     'news_ceo_radar.py',       [],                        1,  0,  None),   # Asien Morgen
    ('Newswire Analyst',    'newswire_analyst.py',     [],                        1,  0,  None),
    ('CEO Radar Asien',     'news_ceo_radar.py',       [],                        4,  0,  None),   # Asien Close
    ('Newswire Analyst',    'newswire_analyst.py',     [],                        4,  0,  None),
    # EU Pre-Market
    ('CEO Radar Morgen',    'news_ceo_radar.py',       [],                        7,  0,  None),
    ('Newswire Analyst',    'newswire_analyst.py',     [],                        7,  0,  None),
    # EU Session
    ('Newswire Analyst',    'newswire_analyst.py',     [],                        9,  0,  None),
    ('News Gate Update',    'news_gate_updater.py',    [],                        9,  5,  None),
    ('CEO Radar',           'news_ceo_radar.py',       [],                        9,  10, None),
    ('Newswire Analyst',    'newswire_analyst.py',     [],                        13, 0,  None),
    ('News Gate Update',    'news_gate_updater.py',    [],                        13, 5,  None),
    ('CEO Radar',           'news_ceo_radar.py',       [],                        13, 10, None),
    # US Session
    ('Newswire Analyst',    'newswire_analyst.py',     [],                        17, 0,  None),
    ('News Gate Update',    'news_gate_updater.py',    [],                        17, 5,  None),
    ('CEO Radar',           'news_ceo_radar.py',       [],                        17, 10, None),
    # Abend / US Close
    ('Newswire Analyst',    'newswire_analyst.py',     [],                        21, 0,  None),
    ('News Gate Update',    'news_gate_updater.py',    [],                        21, 5,  None),
    ('CEO Radar',           'news_ceo_radar.py',       [],                        21, 10, None),
    # Mo-Fr
    ('Feature Analyzer',    'feature_analyzer.py',     ['--quick'],               11, 30, [5]),   # Sa
    ('Backtest Engine',     'backtest_engine.py',      ['--quick'],               9,  0,  [6]),   # So
    ('Strategy DNA',        'strategy_dna.py',         [],                        12, 0,  [5]),   # Sa
    ('Strategy Discovery',  'strategy_discovery.py',   [],                        14, 0,  [5]),   # Sa
    ('Feature Importance',  'feature_importance.py',   [],                        22, 30, [4]),   # Fr
    # ── Phase 6: Autonome Thesen-Entdeckung — taeglich ─────────────────────
    ('Thesis Discovery',   'intelligence/thesis_discovery.py', [],              5,  0,  None),   # Taeglich 05:00 UTC (vor EU-Open)
    # ── Autonomous Scanner: Mo-Fr 08:00–19:30 UTC (Xetra 08-16 + US 13:30-20) ──
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   8,  0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   8,  30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   9,  0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   9,  30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   10, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   10, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   11, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   11, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   12, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   12, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   13, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   13, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   14, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   14, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   15, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   15, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   16, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   16, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   17, 0,  [0,1,2,3,4]),   # US Nachmittag
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   17, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   18, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   18, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   19, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   19, 30, [0,1,2,3,4]),   # US letzte Stunde
    # ── Lab Scanner: stuendlich Mo-Fr 08:45–19:45 UTC ────────────────────────
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  8,  45, [0,1,2,3,4]),
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  9,  45, [0,1,2,3,4]),
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  10, 45, [0,1,2,3,4]),
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  11, 45, [0,1,2,3,4]),
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  12, 45, [0,1,2,3,4]),
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  13, 45, [0,1,2,3,4]),
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  14, 45, [0,1,2,3,4]),
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  15, 45, [0,1,2,3,4]),
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  16, 45, [0,1,2,3,4]),
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  17, 45, [0,1,2,3,4]),
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  18, 45, [0,1,2,3,4]),
    ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  19, 45, [0,1,2,3,4]),
    # ── Backtest v2: jeden Sonntag 08:00 UTC (nach Thesis Discovery 07:00) ──────
    ('Backtest v2',   'backtest_engine_v2.py',           [],         8,  0,  [6]),   # So 08:00 UTC
    ('Backtest v2',   'backtest_engine_v2.py',           [],         8,  0,  [2]),   # Mi 08:00 UTC (Mid-Week Refresh)
]


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode('ascii', errors='replace').decode('ascii'), flush=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    # Log auf 5000 Zeilen begrenzen
    try:
        lines = LOG_FILE.read_text(encoding='utf-8').splitlines()
        if len(lines) > 5000:
            LOG_FILE.write_text('\n'.join(lines[-4000:]) + '\n', encoding='utf-8')
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

def run_job(name: str, script: str, args: list[str], discord: bool = False) -> bool:
    """Führt ein Script aus. Bei discord=True wird stdout an Victor gesendet."""
    script_path = SCRIPTS / script
    if not script_path.exists():
        log(f'⚠️  {name}: Script nicht gefunden — {script}')
        return False

    log(f'▶️  {name}: Start')
    try:
        result = subprocess.run(
            [PYTHON, str(script_path)] + args,
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
            log(f'   STDERR: {result.stderr[-300:]}')
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
            pid = int(monitor_pid_file.read_text(encoding="utf-8").strip())
            if is_running(pid):
                return  # Läuft schon
        except (ValueError, Exception):
            pass  # PID tot → neu starten

    proc = _sp.Popen(
        [PYTHON, str(WS / 'scripts/price_monitor.py')],
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
    if not startup_flag.exists() or startup_flag.read_text(encoding="utf-8").strip() != today_str:
        notify('🤖 **TradeMind** online')
        startup_flag.write_text(today_str, encoding="utf-8")

    # Price Monitor sofort starten
    start_price_monitor()

    # Albert Discord-Chat-Thread starten
    chat_thread_ref = {'t': None}

    def _start_chat_thread():
        try:
            sys.path.insert(0, str(SCRIPTS))
            import discord_chat
            import importlib
            importlib.reload(discord_chat)
            t = threading.Thread(target=discord_chat.run_forever, daemon=True, name='AlbertChat')
            t.start()
            chat_thread_ref['t'] = t
            log('💬 Albert Discord-Chat-Thread gestartet')
        except Exception as e:
            log(f'⚠️  Albert Discord-Chat konnte nicht gestartet werden: {e}')

    _start_chat_thread()

    # Subthread-Watchdog: prueft jede Minute Price-Monitor-Prozess + Chat-Thread
    last_hc_log = [0.0]

    def _subthread_healthcheck():
        # Price Monitor: PID muss leben
        try:
            start_price_monitor()  # ist idempotent: startet nur wenn PID tot
        except Exception as _e:
            log(f'⚠️  Price-Monitor-Watchdog: {_e}')
        # Discord Chat Thread: muss is_alive() sein
        t = chat_thread_ref.get('t')
        if t is None or not t.is_alive():
            log('⚠️  Albert-Chat-Thread tot → Restart')
            _start_chat_thread()
        # Heartbeat-Log max 1x/h
        import time as _tm
        if _tm.time() - last_hc_log[0] > 3600:
            log('💓 Subthread-Healthcheck: Price-Monitor + Chat-Thread OK')
            last_hc_log[0] = _tm.time()

    last_run = {}  # Verhindert Doppel-Ausführungen

    while True:
        now = datetime.now()
        current_key = f'{now.strftime("%Y-%m-%d %H:%M")}'

        # Subthread-Watchdog (vor Job-Dispatch)
        try:
            _subthread_healthcheck()
        except Exception as _hc_err:
            log(f'⚠️  Healthcheck-Fehler: {_hc_err}')

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

                # Bestimmte Jobs senden Discord-Notification bei Fehler
                if not success:
                    notify(f'⚠️ **Scheduler:** {name} fehlgeschlagen — Logs: data/scheduler.log')

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
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None

def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        # Windows: os.kill(pid, 0) raises OSError — use subprocess instead
        import subprocess as _sp
        try:
            r = _sp.run(['tasklist', '/FI', f'PID eq {pid}'], capture_output=True, text=True)
            return str(pid) in r.stdout
        except Exception:
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
                lines = LOG_FILE.read_text(encoding='utf-8').splitlines()
                print('\nLetzte 10 Einträge:')
                for l in lines[-10:]:
                    print(f'  {l}')
        else:
            print('❌ Scheduler läuft NICHT')
            print('   Starte mit: python3 scheduler_daemon.py &')

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
