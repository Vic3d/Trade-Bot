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
import traceback
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
    # Earnings-Blackout-Cache (entry_gate.is_earnings_blackout) — wöchentlich Mo 06:35
    ('Earnings Cache',      'earnings_calendar.py',               [],             6,  35, [0],         False),
    # Asia Lead Signal — täglich vor Morgen-Briefing (Frühindikator US/EU-Open)
    ('Asia Lead Signal',    'asia_lead_signal.py',                [],             7,  0,  None,        False),
    # Phase 21 — Korrelations-Matrix (Ledoit-Wolf + EWMA + Conditional)
    # Vor Handelsstart, nach Asia-Lead. Schreibt data/correlations.json
    ('Correlation Matrix',  'correlation_refresh.py',             [],             7,  15, [0,1,2,3,4]),
    # Price-Backfill: laedt Historie fuer neu discovered Tickers (Auto-DD braucht >=60d)
    ('Discovery Price BF',  'discovery/price_backfill.py',        [],             6,  45, [0,1,2,3,4], False),
    # Pipeline: nach Auto-DD (07:30) — promoted/rejected auf Basis der neuen Verdikts
    # LOW-Tier: Pipeline-Status nur ins Log, nicht nach Discord (nicht actionable)
    ('Discovery Pipeline',  'discovery/discovery_pipeline.py',    [],             12, 0,  [0,1,2,3,4], False),
    # ── Overnight Events sammeln — 24/7, auch Asien-Session ────────────────
    ('Overnight Collector', 'overnight_collector.py',  [],                        1,  0,  None),   # Asien Morgen (10:00 JST)
    ('Overnight Collector', 'overnight_collector.py',  [],                        4,  0,  None),   # Asien Close (13:00 JST)
    ('Overnight Collector', 'overnight_collector.py',  [],                        7,  10, None),   # EU Pre-Market
    ('Overnight Collector', 'overnight_collector.py',  [],                        8,  25, [0,1,2,3,4]),  # vor Briefing
    ('Overnight Collector', 'overnight_collector.py',  [],                        14, 0,  [0,1,2,3,4]),  # US Opening
    ('Overnight Collector', 'overnight_collector.py',  [],                        20, 30, [0,1,2,3,4]),  # US Close
    # ── Phase 42b — High-Frequency News-Pipeline (alle 30min in Marktstunden) ─
    # Keine Event-Pipeline (das macht overnight_collector), nur reines News-Fetching.
    # Marktstunden Mo-Fr 09-22 CET → alle 30min, Off-hours alle 2h.
    ('News Pipeline Fast',  'news_pipeline.py',        [],            '9-22', '*/30', [0,1,2,3,4]),
    ('News Pipeline Slow',  'news_pipeline.py',        [],            '*/2',   0,     None),
    # ── Phase 42b — Macro-Event-Detector (alle 15min, sucht Breaking-Macro) ──
    ('Macro Event Detector','macro_event_detector.py', [],            '*',    '*/15', None),
    # ── Phase 43d — Bodenbildung-Detector (1x täglich nach Marktschluss) ────
    ('Bodenbildung Scan',   'bodenbildung_detector.py', ['--all-watchlist'], 22, 30, [0,1,2,3,4]),
    # ── Phase 43k — A/B-Strategy-Test Live-Update (alle 30min Marktstunden) ──
    ('AB Strategy Update',  'ab_strategy_runner.py',  ['--update'],         '9-22', '*/30', [0,1,2,3,4]),
    # ── Phase 44A2 — Strategy-Auditor (Sonntags 20:00 CET, Discord-Report) ──
    ('Strategy Auditor',    'strategy_auditor.py',    ['--discord'],        20, 0,  [6]),
    # Phase 45x (D1): Cross-Source Price-Consistency-Audit (vor Auto-Deprecate)
    ('Price Consistency Audit', 'price_consistency_audit.py', [],            22, 30, None),
    # Phase 45z (J1+J2): Edge-Detection — News-Free-Move + Cross-Asset-Divergence
    ('News-Free Move Detector', 'news_free_move_detector.py',  [],          '*',  '*/15', None),
    ('Cross-Asset Divergence',  'cross_asset_divergence.py',   [],          '*',  '*/15', None),
    # Phase 45aa: Silence-Detector + External-Heartbeat + API-Heartbeat
    ('Silence Detector',        'silence_detector.py',         [],          '*',  '*/30', None),
    ('External Heartbeat',      'external_heartbeat.py',       [],          '*',  '*/5',  None),
    ('API Heartbeat',           'api_heartbeat.py',            [],          '*',  '*/15', None),
    # ── Phase 44A2b — Strategy Auto-Deprecate (täglich 23:00, Regel #1) ────
    ('Strategy Auto-Deprecate','strategy_auto_deprecate.py', [],            23, 0,  None),
    # ── Phase 45ag — Lifecycle-Audit + Dead-Sweeper + Data-Janitor ─────────
    ('Strategy Lifecycle Audit','strategy_lifecycle_audit.py', [],           23, 30, None),
    ('Strategy Dead Sweeper',  'strategy_dead_sweeper.py',     [],           23, 45, None),
    ('Data Janitor',           'data_janitor.py',              [],           2,  0,  [6]),  # nur Sonntag
    # ── Phase 45ai — CEO Self-Audit (reflexiv, Sonntag vor Week-Ahead) ────
    ('CEO Self-Audit',         'ceo_self_audit.py',            [],           19, 0,  [6]),  # nur Sonntag
    # ── Phase 45aj/al — Albert-Bewusstsein 24/7/365 (Victor 2026-05-09) ────
    # Albert hat keine Arbeitszeiten — er denkt, beobachtet, plant durchgehend.
    # Wochenenden: weniger Markt-Events, aber News/Geo/Strategie-Reflexion läuft.
    # Stufe 1: Brain-Tick alle 15min RUND UM DIE UHR (~96 Ticks/Tag)
    ('Albert Brain-Tick',      'albert_brain_tick.py',         [],            '*', '*/15', None),
    # ── Phase 45al — Decision-Review (Albert lernt aus eigenen Decisions) ──
    # Täglich 22:00, prüft fällige Strategist-Proposals (evaluate_after_days)
    ('Albert Decision-Review', 'albert_decision_review.py',    [],           22,  0, None),
    # ── Phase 45aq Layer B3 + D3 — Tranche-Exits + Stress-Test ───────────
    ('Tranche Exit Manager',   'tranche_exit_manager.py',      [],           22, 15, None),
    ('Stress Scenario Tester', 'stress_scenario_tester.py',    [],           22, 30, None),
    # Stufe 2: Goal-Tracker täglich 23:00
    ('Albert Goal-Tracker',    'albert_goal_tracker.py',       [],           23,  0, None),
    # Stufe 3: Self-Review täglich 23:30 (nach goal_tracker)
    ('Albert Self-Review',     'albert_self_review.py',        [],           23, 30, None),
    # ── Phase 45ao — Markt-Pulse + Genesis + Setup-Patterns + Live-Trigger ──
    # Layer 1+2: Markt-Puls 06:00 (Sektor-ETFs, Drilldown, RS-vs-SPY)
    ('Market Pulse Scanner',   'market_pulse_scanner.py',      [],            6,  0, None),
    # ── Phase 45aq — Macro-Regime + Sentiment + Stress + Story ───────────
    ('Macro Regime Detector',  'macro_regime_detector.py',     [],            6,  5, None),
    ('Sentiment Contrarian',   'sentiment_contrarian.py',      [],            6, 10, None),
    # Layer 3: News-Cross 06:15
    ('Sector News Correlator', 'sector_news_correlator.py',    [],            6, 15, None),
    # Layer 4: Genesis 06:20 (OPUS — generiert neue Strategy-Proposals)
    ('Strategy Genesis Engine','strategy_genesis_engine.py',   [],            6, 20, None),
    # Phase 45aq Layer E: Story-Tagger 06:25 vor Strategist
    ('Position Story Tagger',  'position_story_tagger.py',     [],            6, 25, None),
    # Phase 45at — Cohort-System: monatlich neue Tranche 1. um 00:01
    ('Cohort Manager',         'cohort_manager.py',            [],            0,  1, None),
    # Tägliches Lifecycle-Management (1-Jahr-Anniversary etc.)
    ('Cohort Lifecycle',       'cohort_lifecycle.py',          [],           23, 15, None),
    # Tägliches Performance-Tracking pro Kohorte
    ('Cohort Performance',     'cohort_performance_tracker.py', [],          22, 45, None),
    # Phase 45av — Re-Entry-Watchlist täglicher Check (Tradermacher-Reclaim)
    ('Re-Entry Watchlist',     're_entry_watchlist.py',        ['--check'],   22, 50, None),
    # Layer 5: Setup-Patterns alle 30min waehrend US-Markt (15-22 CET)
    ('Setup Pattern Detector', 'setup_pattern_detector.py',    [],     '15-22', '*/30', [0,1,2,3,4]),
    # Layer 6: Live-Trigger alle 15min waehrend US-Markt
    ('Live Trigger Watcher',   'live_trigger_watcher.py',      [],     '15-22', '*/15', [0,1,2,3,4]),
    # ── Phase 45ak/al — Albert-Strategist täglich 06:30, liest die Layer 1-4 ──
    ('Albert Strategist',      'albert_strategist.py',         [],            6, 30, None),
    # ── Phase 44d — Multi-Strategy-Shadow (alle 41 Strategien parallel testen) ──
    # Sprint 0 cleanup: multi_strategy_shadow archiviert (wird durch Sprint-1 Backtest-Framework ersetzt)
    # ('Shadow Strategy Hunt',   'multi_strategy_shadow.py', ['--hunt'],      '9-22', '*/30', [0,1,2,3,4]),
    # ('Shadow Strategy Update', 'multi_strategy_shadow.py', ['--update'],    '9-22', '*/15', [0,1,2,3,4]),
    # ── Reports (discord=True → Output direkt an Victor) ─────────────────────
    # Format: (name, script, args, hour, min, weekdays, discord)
    # ── Phase 45ah (Victor 2026-05-09): NUR 3 DAILY DISCORD-BRIEFINGS ──
    #   Morgen-Briefing (08:00) + US Opening (16:30) + Abend-Digest (20:00)
    #   Alles andere stumm (CEO-Inbox). Wöchentlich: Friday + Week-Ahead.
    # 1/3 — Morgen-Briefing (Marktdaten + Ausblick)
    ('Morgen-Briefing',     'morning_brief_generator.py', [],                    8,   0, [0,1,2,3,4], True),
    # DEAKTIVIERT (Victor 2026-05-09): Inhalt überlappt mit Morgen-Briefing
    # ('Morgen-Digest',       'daily_digest.py',            ['morning'],           8,   5, [0,1,2,3,4]),
    # DEAKTIVIERT (Victor 2026-05-09): Xetra-Push redundant — US-Open ist der wichtige Pivot
    # ('Xetra Opening',       'us_opening_report.py',       ['--mode', 'xetra'],   9,  30, [0,1,2,3,4]),
    # Phase 45as (Victor 2026-05-12): EU/Mid-Day-Briefing 13:00 CEST.
    # Volles Briefing wie Morgen-Briefing — eigenes Script midday_briefing.py.
    ('Mid-Day Briefing',    'midday_briefing.py',         [],                    13,  0, [0,1,2,3,4], True),
    # Phase 45az: Detector→Action-Bridge 09:45 — eskaliert ignorierte Detector-Findings (vor dem Digest 10:00)
    ('Detector Action Bridge', 'detector_action_bridge.py', [],                  9, 45, None, False),
    # Phase 45ay: Albert-Verbesserungs-Digest 10:00 — kurze Vorschlags-Zusammenfassung
    ('Albert Improvement Digest', 'albert_improvement_digest.py', [],           10,  0, None, True),
    # 2/3 — US Opening (Übersee-Eröffnung) — Phase 45an: discord=True für Narrative-Push
    ('US Opening',          'us_opening_report.py',       ['--mode', 'us'],      16, 30, [0,1,2,3,4], True),
    # 3/3 — Abend-Digest (Trades + Learnings + Universe-Review) — sendet selbst via _send()
    ('Abend-Digest',        'daily_digest.py',            ['evening'],           20, 0,  [0,1,2,3,4]),
    # Sonntags-Wochen-Digest: enthält _signal_alpha_block (Sub-7 #1)
    ('Sonntags-Digest',     'daily_digest.py',            ['evening'],           20, 0,  [6]),
    # DEAKTIVIERT (Victor 2026-05-09): Abend-Digest ersetzt das schon
    # ('Abend-Report',        'evening_report.py',          [],                    22, 0,  [0,1,2,3,4]),
    ('Tagesabschluss',      'daily_summary.py',           [],                    23, 0,  None),
    # Phase 7.11 — Ritual-Ebene (reflektiv, nicht metriklastig)
    ('Daily Review',        'daily_review.py',            [],                    22, 15, [0,1,2,3,4], True),  # Mo-Fr 22:15
    ('Weekly Summary',      'weekly_summary.py',          [],                    21, 0,  [6],         True),  # So 21:00
    # ── Phase 22 — Opportunity Engine (laeuft VOR Auto-Deep-Dive) ────────────
    # LOW-Tier (Log-only): Scanner ohne direkte Action — Output landet im Morgen-Briefing
    ('Smart Money Tracker', 'discovery/smart_money_tracker.py', [],                6,  10, [0,1,2,3,4], False),
    ('Catalyst Calendar',   'catalyst_calendar.py',             [],                6,  20, None,        False),
    # ── Phase 22 Core Jobs ───────────────────────────────────────────────────
    ('Commodity Refresh',   'commodity_refresh.py',             [],                7,  0,  None,        False),  # tgl. 07:00 vor Handel
    # Phase 44k: Commodity-Cache-JSON fuer LLM-Konsumenten (Hunter, Discord-Bot)
    # 4x taeglich an Markt-Pivots — Brent/VIX/Gold/Copper als Korrelations-Driver
    ('Commodity Cache',     'commodity_price_refresh.py',       [],                7,  5,  None,        False),  # vor EU-Open
    ('Commodity Cache',     'commodity_price_refresh.py',       [],                12, 0,  None,        False),  # Mittag
    ('Commodity Cache',     'commodity_price_refresh.py',       [],                15, 30, None,        False),  # US-Open
    ('Commodity Cache',     'commodity_price_refresh.py',       [],                21, 0,  None,        False),  # US-Close
    # Phase 44n: Professional Stop-Management (Daily-Cycle nach Close)
    # Phase 44z: Background-Jobs auf 7 Tage erweitert (idempotent — kein neuer Tape = keine Aktion)
    ('Catalyst Widener',    'catalyst_stop_widener.py',         [],                6,  30, None,        False),  # tgl. 06:30
    ('Stop Manager Daily',  'stop_manager_daily.py',            [],                22, 30, None,        False),  # tgl. 22:30
    ('Macro Stop Review',   'macro_stop_review.py',             ['--auto'],        9,  30, None,        False),  # tgl. 09:30
    ('Macro Stop Review',   'macro_stop_review.py',             ['--auto'],        16, 0,  None,        False),  # tgl. 16:00
    # Phase 44o: Self-Awareness-Stack
    ('Calibration Tracker', 'ceo_calibration_tracker.py',       [],                23, 0,  None,        False),  # tgl. 23:00: Brier-Score
    ('Lesson Extractor',    'ceo_lesson_extractor.py',          [],                23, 15, None,        False),  # tgl. 23:15: Trade → Lessons
    ('Hypothesis Tracker',  'ceo_hypothesis_tracker.py',        [],                23, 30, None,        False),  # tgl. 23:30: Insights → Status
    ('Conviction Recalib',  'conviction_calibration.py',        [],                22, 45, None,        False),  # tgl. 22:45: Logistic-Fit conviction → P(win)
    # Phase 44r: Bayer-Catalyst-Monitor (bis SCOTUS-Decision 08.07.2026)
    ('Bayer Catalyst Watch','bayer_catalyst_monitor.py',        [],                22, 5,  None,        False),  # tgl. 22:05 nach EU-Close
    # Phase 44s: Active CEO Self-Research + YouTube-Auto-Intake
    ('CEO Self-Research',   'ceo_self_research.py',             [],                6,  0,  None,        False),  # tgl. 06:00 vor erstem Hunt
    ('YouTube Intake',      'youtube_transcript_monitor.py',    [],                7,  0,  None,        False),  # tgl. 07:00
    # Phase 44u: Discord-Digest-Flush — bündelt MEDIUM/LOW Queue statt Spam
    ('Discord Digest MED',  'discord_dispatcher.py',            ['--flush-medium'], 12, 0, None,        False),  # Mittag
    ('Discord Digest LOW',  'discord_dispatcher.py',            ['--flush-low'],    22, 30, None,       False),  # Abend
    # Phase 44t: News-Reactor — alle 15min position-aware News-Bewertung (Trading-Window)
    ('News Reactor',        'news_reactor.py',                  [],                9,  15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                10, 15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                11, 15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                12, 15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                13, 15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                14, 15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                15, 15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                16, 15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                17, 15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                18, 15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                19, 15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                20, 15, [0,1,2,3,4], False),
    ('News Reactor',        'news_reactor.py',                  [],                21, 15, [0,1,2,3,4], False),
    # Phase 44v: News-Reactor auch am Wochenende (4x/Tag, News schlafen nicht)
    ('News Reactor',        'news_reactor.py',                  [],                10, 0,  [5,6],       False),
    ('News Reactor',        'news_reactor.py',                  [],                14, 0,  [5,6],       False),
    ('News Reactor',        'news_reactor.py',                  [],                18, 0,  [5,6],       False),
    ('News Reactor',        'news_reactor.py',                  [],                21, 0,  [5,6],       False),
    # Phase 44v: Sonntag-Week-Ahead-Briefing — Vorbereitung auf Mo
    ('Week Ahead Briefing', 'ceo_week_ahead_briefing.py',       [],                18, 0,  [6],         False),  # Sonntag 18:00
    # Phase 44w: Mission-bezogene Capability-Audit (taeglich)
    ('Capability Audit',    'ceo_capability_audit.py',          [],                23, 45, None,        False),  # tgl. 23:45 nach allen anderen Reflektionen
    # Phase 44ab: Albert ENTSCHEIDET autonom + meldet post-fact (kein Frage-System mehr)
    # Phase 45t (Victor 2026-05-06): Albert mehrmals pro Tag aktiv —
    # Autonomie darf nicht durch 1x/Tag-Schicht gebremst werden.
    ('CEO Action Log',      'ceo_action_log.py',                [],                7,  0,  None,        False),  # tgl. 07:00 — Morgen-Decision
    ('CEO Action Log',      'ceo_action_log.py',                [],                13, 0,  None,        False),  # tgl. 13:00 — Mittag-Decision
    ('CEO Action Log',      'ceo_action_log.py',                [],                19, 0,  None,        False),  # tgl. 19:00 — Abend-Decision
    # Phase 44ad: CEO arbeitet kontinuierlich — alle 10min Mini-Cycle, alle 30min Halluzinations-Sweep
    ('CEO Active Loop',     'ceo_active_loop.py',               [],                '*',  '*/10', None,  False),  # alle 10min 24/7
    ('Halluz Sweeper',      'halluzination_sweeper.py',         [],                '*',  '*/30', None,  False),  # alle 30min 24/7
    # Phase 45a (Sprint 0): Mission-KPIs taeglich (Sharpe, Drawdown, Calmar)
    ('Quant Metrics',       'quant_metrics.py',                 [],                23, 50, None,        False),  # tgl. 23:50
    # Phase 45m (Victor 2026-05-05): Tool-Inventur ueber 30 Tage
    ('Tool Usage Tracker',  'tool_usage_tracker.py',            [],                23, 55, None,        False),  # tgl. 23:55 (nach allen anderen Jobs)
    # Phase 45n (Victor 2026-05-05): Wochenend-Verbesserungs-Briefing
    ('Friday Briefing',     'friday_improvement_briefing.py',   [],                18, 0,  [4],         False),  # Freitag 18:00 CET

    # Phase 45c (Sprint 2): Feature-Engineering taeglich nach Markt-Close
    ('Feature Engineering', 'feature_engineering.py',           ['--all'],         22, 15, None,        False),  # tgl. 22:15
    # Phase 45d (Sprint 3): ML-Win-Prob retraining woechentlich (Sa)
    ('ML WinProb Train',    'ml_winprob_model.py',              [],                3,  0,  [5],         False),  # Sa 03:00
    # Phase 45e (Sprint 4): Markt-Regime alle 2h
    ('Regime Detect',       'regime_detector.py',               [],                '*',  '0',  None,    False),  # stuendlich (Min 0)
    # Phase 45g (Sprint 6): Multi-Asset Universe-Refresh
    ('Multi-Asset Refresh', 'multi_asset_universe.py',          [],                7,  10, None,        False),  # tgl. 07:10
    # Phase 45h (Sprint 7): Short-Engine Schema-Migration
    ('Short Engine Schema', 'short_engine.py',                  [],                3,  30, [6],         False),  # So 03:30 weekly
    # Phase 45i (Sprint 8): Real-Money-Bridge Status-Check
    ('Real-Money Status',   'real_money_bridge.py',             [],                7,  20, None,        False),  # tgl. 07:20
    # Phase 44y: Hunter im Research-Mode auch am Wochenende (Thesen suchen + verifizieren)
    # Mo-Fr macht der CEO Brain das schon im Trading-Window. Sa/So extra:
    ('Hunter Research',     'hunter_research_mode.py',          [],                10, 30, [5,6],       False),
    ('Hunter Research',     'hunter_research_mode.py',          [],                15, 30, [5,6],       False),
    ('Hunter Research',     'hunter_research_mode.py',          [],                20, 30, [5,6],       False),
    ('Insider Refresh',     'intelligence/insider_refresh.py',  [],                7,  30, None,        False),  # tgl. 07:30 vor Handel
    ('Catalyst Re-Eval',    'intelligence/catalyst_reeval.py',  [],                8,  0,  None,        False),  # tgl. 08:00
    ('Political Risk Scan', 'intelligence/political_risk_detector.py', [],         8,  30, None,        False),  # tgl. 08:30
    # Universe Decay: deaktiviert — Modul erwartet flat-ticker-Schema, universe.json
    # ist sector-grouped. Reaktivierung erst nach Schema-Migration.
    # Phase 23 — Catalyst-to-Profiteer Engine: News → Sektor → Profiteer-Tickers
    # Läuft 5x/Tag (alle ~3h zwischen 06-22) — News-Pipeline läuft 4x/Tag, ein Tick versetzt
    ('Catalyst Engine',     'intelligence/catalyst_to_profiteer.py',  [],          6,  50, None,        False),
    ('Catalyst Engine',     'intelligence/catalyst_to_profiteer.py',  [],          10, 50, None,        False),
    ('Catalyst Engine',     'intelligence/catalyst_to_profiteer.py',  [],          14, 50, None,        False),
    ('Catalyst Engine',     'intelligence/catalyst_to_profiteer.py',  [],          18, 50, None,        False),
    ('Catalyst Engine',     'intelligence/catalyst_to_profiteer.py',  [],          22, 30, None,        False),
    # Thesis News Hunter — gezielte per-These KI-Bewertung (priced-in?, kill-trigger nah?), 4x/Tag
    ('Thesis News Hunter',  'thesis_news_hunter.py',            [],                9,  0,  None,        False),
    ('Thesis News Hunter',  'thesis_news_hunter.py',            [],                13, 0,  None,        False),
    ('Thesis News Hunter',  'thesis_news_hunter.py',            [],                17, 0,  None,        False),
    ('Thesis News Hunter',  'thesis_news_hunter.py',            [],                21, 0,  None,        False),
    ('Watchlist Rebuild',   'thesis_watchlist.py',              ['--tick'],        8,  45, None,        False),  # tgl. 08:45
    ('Scenario Mapper',     'scenario_mapper.py',               [],                6,  30, [0,1,2,3,4], False),
    ('Pain Trade Scanner',  'pain_trade_scanner.py',            [],                7,  0,  None,        False),
    # HIGH-Tier (Discord direkt): Neue Thesen sind action-relevant
    ('Thesis Generator',    'thesis_generator.py',              [],                7,  15, [0,1,2,3,4], True),
    # Backfill NACH Thesis-Generator (neue Kandidaten brauchen Preisdaten fuer Auto-DD 07:30)
    ('Discovery Price BF',  'discovery/price_backfill.py',      [],                7,  22, [0,1,2,3,4], False),
    ('Thesis Generator',    'thesis_generator.py',              [],                19, 15, [0,1,2,3,4], True),
    ('Discovery Price BF',  'discovery/price_backfill.py',      [],                19, 22, [0,1,2,3,4], False),
    # LOW-Tier: Graveyard-Cleanup ist internes Housekeeping
    ('Thesis Graveyard',    'thesis_graveyard.py',              [],                23, 30, None,        False),
    # ── Phase 22.1: Portfolio Circuit Breaker — Tages-Snapshot vor Schluss ────
    ('Equity Snapshot',     'portfolio_circuit_breaker.py',     ['--record-close'], 21, 45, None,      False),
    # Phase 7.14 — Auto-Deep-Dive via Claude API (sonnet)
    # LOW-Tier: Deep-Dive-Verdicts werden in deep_dive_verdicts.json gespeichert
    # und von Guard 0c2 genutzt. Volltext-Reports gehoeren ins Log, nicht Discord
    # (zu lang, taeglich 4x = massiver Noise). Victor sieht Verdikte im Daily Review.
    ('Auto Deep Dive',      'auto_deep_dive_runner.py',   ['full'],              7,  30, [0,1,2,3,4], False),
    ('Auto Deep Dive',      'auto_deep_dive_runner.py',   ['open-only'],         13, 30, [0,1,2,3,4], False),
    ('Auto Deep Dive',      'auto_deep_dive_runner.py',   ['open-only'],         19, 30, [0,1,2,3,4], False),
    ('Auto Deep Dive',      'auto_deep_dive_runner.py',   ['full'],              20, 0,  [6],         False),
    # ─────────────────────────────────────────────────────────────────────────
    ('Performance Tracker', 'performance_tracker.py',  [],                        21, 30, None),  # täglich
    # ── Memory-Vorschlag (Albert proposed Daily-Learnings für memory/*.md) ──
    ('Memory Proposal',     'daily_memory_proposal.py', [],                       21, 45, None),
    # ── Phase 25: Weekly Skipped-Trades Review (Mo 08:00) ──
    ('Skipped Review',      'weekly_skipped_review.py', [],                        8,  0,  [0]),
    # ── Phase 23b: Sizing A/B-Test Review (Mo 08:15) ──
    ('Sizing AB Review',    'sizing_ab_review.py',     [],                         8, 15,  [0]),
    # ── Phase 28: Shadow-Trades Counterfactual Tracking ──
    ('Shadow Evaluator',    'shadow_evaluator.py',     [],                         23, 30, None),  # täglich
    ('Shadow Thesis Review','shadow_thesis_review.py', [],                         8, 30,  [0]),    # Mo
    # ── Phase 31: Goal-Function Score (täglich 22:30) ──
    # Berechnet Utility = pnl + sharpe×1000 - drawdown×200 - concentration.
    ('Goal Score', 'goal_function.py', [], 22, 30, None),
    # ── Phase 31b: Goal-Auto-Adjust (täglich 22:45 nach goal_function) ──
    # RL-light: Bei Trend-Decline (>5%) verschärft min_crv/pos%/sektor%.
    # Bei Trend-Improve + alle Targets met → lockern. Bounded.
    ('Goal Auto Adjust', 'goal_auto_adjust.py', [], 22, 45, None),
    # ── Phase 32c: CEO-Reflection (täglich 23:15) ──
    # Vergleicht heutige Decisions mit Outcomes, extrahiert Lessons via LLM.
    # Lessons werden vom CEO-Brain in jedem nächsten Run als Kontext geladen.
    ('CEO Reflection', 'ceo_reflection.py', [], 23, 15, None),
    # ── Phase 40z: CEO-Capabilities-Doc Refresh (täglich 23:55) ──
    # Aktualisiert memory/ceo-capabilities.md → CEO weiß was er kann.
    ('CEO Capabilities Refresh', 'generate_ceo_capabilities.py', [], 23, 55, None),
    # ── Phase 39: Strategy-Lifecycle (täglich 23:00 nach Anti-Pattern-Refresh) ──
    # Managed: ACTIVE → PROBATION → SUSPENDED → RETIRED Lifecycle.
    # Reaktiviert via Shadow-Test wenn Cooldown vorbei.
    ('Strategy Lifecycle', 'strategy_lifecycle.py', [], 23, 5, None),
    # ── Phase 38: Anti-Pattern Detection (täglich 22:55) ──
    # Scannt closed Trades nach Patterns mit hoher Loss-Rate.
    # CEO-Brain liest die Liste in jedem nächsten Run als Pre-Fetch.
    ('Anti-Pattern Detect', 'ceo_pattern_learning.py', ['patterns'], 22, 55, None),
    # ── Phase 33: CEO-Consciousness (täglich 23:30) ──
    # Update Calibration, Mood, Hypotheses, World-Events.
    # Output wird vom CEO-Brain im nächsten Run gelesen.
    ('CEO Consciousness', 'ceo_consciousness.py', [], 23, 30, None),
    # ── CEO-Self-Reflection (täglich 23:45) ──
    # Speichert tägliche Selbsteinschätzung in ceo_self_reflections.jsonl
    # → enables historische Vergleiche ("wie war ich vor 7d?")
    ('CEO Self Reflection', 'ceo_self_assessment.py', [], 23, 45, None),
    # ── Phase 34a: Narrative Self / Identity-Document (täglich 23:50) ──
    # Aktualisiert memory/ceo-identity.md inkrementell → kontinuierliche
    # Selbst-Story über Tage und Wochen.
    ('CEO Narrative Self', 'ceo_narrative_self.py', [], 23, 50, None),
    # ── Phase 34d: Dream-Phase (täglich 02:00) ──
    # Strategische Konsolidierung wie REM-Schlaf. Sucht latente Patterns,
    # Inkonsistenzen, generiert Strategic Insights die länger leben als
    # normale Lessons. Output → memory/ceo-dream-log.md
    ('CEO Dream', 'ceo_dream.py', [], 2, 0, None),
    # ── Phase 35: Self-Improvement (Sa 23:00 wöchentlich) ──
    # CEO introspektiert + generiert Verbesserungs-Vorschläge für sich
    # selbst. Discord-Push mit Liste, Victor approved via "implement N",
    # spawnt code_task_worker → Claude Code baut + deployt.
    ('CEO Self Improvement', 'ceo_self_improvement.py', [], 23, 0, [5]),
    # ── Phase 30b: Parameter-Auto-Tuning (Mo 06:00 wöchentlich) ──
    # Berechnet aus letzten 60d closed Trades optimale Stop/CRV/Hold-Werte
    # pro Strategie-Typ. Schreibt nach data/strategy_params_tuned.json,
    # Discord-Push mit Empfehlungen.
    ('Param Auto Tuner', 'parameter_auto_tuner.py', [], 6, 0, [0]),
    # ── Daily Position-Audit: 2x täglich Live-Check aller OPEN-Positionen ──
    # 08:30 CEST (vor Markt-Öffnung) + 22:00 (nach Close).
    # Verifiziert entry/stop/target gegen Live-Preis, postet Discord-Report.
    ('Daily Position Audit', 'daily_position_audit.py', [], 8, 30, None),
    ('Daily Position Audit', 'daily_position_audit.py', [], 22, 0, None),
    # ── Phase 29: System-Health-Monitor (alle 30min, 24/7) ──
    # 9 Health-Checks, Auto-Repair wo möglich. Discord-Alert nur bei WARN/FAIL.
    ('Health Monitor', 'system_health_monitor.py', [],  0, 15, None),
    ('Health Monitor', 'system_health_monitor.py', [],  3, 15, None),
    ('Health Monitor', 'system_health_monitor.py', [],  6, 15, None),
    ('Health Monitor', 'system_health_monitor.py', [],  9, 45, None),
    ('Health Monitor', 'system_health_monitor.py', [], 12, 45, None),
    ('Health Monitor', 'system_health_monitor.py', [], 15, 45, None),
    ('Health Monitor', 'system_health_monitor.py', [], 18, 45, None),
    ('Health Monitor', 'system_health_monitor.py', [], 21, 45, None),
    # ── Phase 28a: CEO-Brain — zentrale Trade-Entscheidung alle 30min ──
    # Statt 10 unabhängige Guards: EINE Stimme die alles sieht und entscheidet.
    # Läuft nur im Trading-Fenster (10:00-22:00 CEST), Mo-Fr.
    ('CEO Brain', 'ceo_brain.py', [], 10,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 10, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 11,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 11, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 12,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 12, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 13,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 13, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 14,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 14, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 15,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 15, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 16,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 16, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 17,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 17, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 18,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 18, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 19,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 19, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 20,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 20, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 21,  0, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 21, 30, [0,1,2,3,4]),
    ('CEO Brain', 'ceo_brain.py', [], 22,  0, [0,1,2,3,4]),
    # ── Phase 27: Differenzierungs-Audit (1. So jedes Monats 06:00) ──
    ('Differentiation Audit','intelligence/differentiation_audit.py', [],          6,  0,  [6]),
    ('Advisory Backfill',   'advisory_layer.py',       ['--backfill'],            22, 0,  [0,1,2,3,4]),  # Mo-Fr
    ('Alpha Decay',         'alpha_decay.py',          [],                        21, 0,  None),
    ('Daily Learning',      'daily_learning_cycle.py', [],                        22, 45, None),
    # ── Phase 3: State Sync (JSONs → SQL, nach Daily Learning) ──
    ('State Sync',          'state_sync.py',           [],                        23, 5,  None),
    # P2.13 — Memory-Index regenerieren (queryable history)
    ('Memory Index',        'memory_index.py',         [],                        23, 30, None),
    # K1 — Victor-Feedback Trust-Score (täglich aus Reactions berechnen)
    ('Victor Trust',        'victor_feedback.py',      [],                        23, 20, None),
    # ── Phase 4/5/6.7/6.9: Integrity + Truth Jobs ──
    ('Fund Reconciliation', 'fund_reconciliation.py',  ['--fix'],                 23, 15, None),   # tgl. 23:15 nach State Sync (Sub-8 V2: --fix aktiv)
    ('Proposal Expirer',    'proposal_expirer.py',     [],                         6, 30, None),   # tgl. früh
    ('Proposal Expirer',    'proposal_expirer.py',     [],                        14, 30, None),   # mittags nochmal
    ('Stale Data Watchdog', 'stale_data_watchdog.py',  [],                         6, 45, None),   # tgl. früh
    # ── Sub-8: Monitoring/Watchdogs (2026-04-23) ──
    ('Macro Refresh',       'macro_indicator_refresh.py', [],                      6, 5,  None),   # tgl. 06:05 — SPY/VIX/EURUSD/GOLD/WTI vor allen Health-Checks
    # ── Sub-10: Heartbeat Monitor alle 15 Min (war vorher externer Cron, jetzt scheduler-intern) ──
    ('Heartbeat Monitor',   'heartbeat_monitor.py',   [],                          '*', '*/15', None),
    # ── Sub-9: Concentration Trim Advisor — 2x taeglich (Morgens vor Open + Abends nach Close) ──
    ('Trim Advisor',        'concentration_trim_advisor.py', [],                   8,  10, [0,1,2,3,4]),
    ('Trim Advisor',        'concentration_trim_advisor.py', [],                   22, 30, [0,1,2,3,4]),
    # ── Sub-11: Watchdog Backtest — wöchentlich (Sa Mittag), Discord bei Failure ──
    ('Watchdog Backtest',   'watchdog_backtest.py',   [],                          12,  0, [5], True),
    ('DB Integrity',        'db_integrity_watchdog.py', [],                        6, 30, None),   # tgl. vor Stale-Data
    ('Meta Health',         'meta_health_watchdog.py',  [],                        8, 45, None),   # tgl. nach Morning Brief
    ('Meta Health',         'meta_health_watchdog.py',  [],                       20, 45, None),   # abends nochmal
    ('Anomaly Brake',       'anomaly_brake.py',         [],                        9, 45, [0,1,2,3,4]),  # Marktzeiten
    ('Anomaly Brake',       'anomaly_brake.py',         [],                       11, 45, [0,1,2,3,4]),
    ('Anomaly Brake',       'anomaly_brake.py',         [],                       13, 45, [0,1,2,3,4]),
    ('Anomaly Brake',       'anomaly_brake.py',         [],                       15, 45, [0,1,2,3,4]),
    ('Anomaly Brake',       'anomaly_brake.py',         [],                       17, 45, [0,1,2,3,4]),
    ('Anomaly Brake',       'anomaly_brake.py',         [],                       19, 45, [0,1,2,3,4]),
    ('Anomaly Brake',       'anomaly_brake.py',         [],                       21, 45, [0,1,2,3,4]),
    ('Health Digest',       'health_digest.py',         [],                       22, 30, None),   # tgl. nach Daily Learning
    ('Archive Stale Trades','archive_stale_trades.py', [],                         3,  0, [6]),    # So nur
    # Phase 24 aggressive: stündlich 08-22h (vorher alle 2h) + max 8/Run
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                     8, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                     9, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    10, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    11, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    12, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    13, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    14, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    15, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    16, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    17, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    18, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    19, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    20, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    21, 10, None),
    ('Deepdive Queue Proc', 'deepdive_queue_processor.py', [],                    22, 10, None),
    # ── Phase 7: Validierungs-Jobs (vor Honesty Report) ──
    ('Verdict Accuracy',    'verdict_accuracy_tracker.py', [],                    21, 50, None),
    ('Conviction Backtest', 'conviction_backtest.py',  [],                        21, 52, None),
    ('Edge Attribution',    'edge_attribution.py',     ['--apply'],               21, 54, None),
    ('Readiness Tracker',   'readiness_tracker.py',    [],                        21, 56, None),
    ('Honesty Report',      'honesty_report.py',       [],                        22,  5, None),
    ('Equity Snapshot',     'equity_snapshot.py',      [],                        22, 40, [0,1,2,3,4,5,6]),  # Phase 9 — MUSS vor Daily Learning (22:45) laufen, sonst nutzt Learning Stale-Equity
    ('Insider Refresh',     'intelligence/insider_refresh.py', [],                7,  30, [0,1,2,3,4]),  # Phase 10 — SEC Form 4 Mo-Fr
    ('Macro Brain',         'intelligence/macro_brain.py',     [],                7,  45, [0,1,2,3,4,5,6]),  # Phase 11 — FRED Regime tgl.
    ('Macro Brain',         'intelligence/macro_brain.py',     [],                15, 30, [0,1,2,3,4]),  # Phase 11 — US Pre-Open Update
    # ── Phase 20: Universe Maintenance (vor Auto Deep Dive) ──
    ('Universe Expander',   'intelligence/universe_expander.py', [],              1,  0,  None),  # tgl. 01:00 — News→Discovery
    ('Universe Decay',      'intelligence/universe_decay.py',    [],              2,  0,  None),  # tgl. 02:00 — Auto-dormant
    # ── Phase 21 Pro: Correlation Matrix + Risk Dashboard ──
    ('Correlation Matrix',  'correlation_refresh.py',            [],              7,  15, [0,1,2,3,4]),
    # ── Phase 25: Sector Strength + Asia Lead + Earnings Calendar ──
    ('Sector Strength',     'sector_strength.py',                [],              7,  20, [0,1,2,3,4]),  # vor Morning Brief
    ('Asia Lead Signal',    'asia_lead_signal.py',               [],              7,   0, [0,1,2,3,4]),  # Asia-Close → vor 7:30 fertig
    ('Earnings Refresh',    'earnings_calendar.py',              [],              6,  30, [0]),         # Mo wöchentlich
    ('Risk Dashboard AM',   'risk_dashboard.py',                 ['--morning'],   7,  30, [0,1,2,3,4], True),
    ('Risk Dashboard PM',   'risk_dashboard.py',                 ['--evening'],  21,  0,  [0,1,2,3,4]),
    # ── Phase 12: Auto Deep Dive (nightly verdict refresh, rule-based, no LLM) ──
    ('Auto Deep Dive',      'intelligence/auto_deepdive.py',   [],                2,  30, None),  # tgl. 02:30
    # ── Phase 14: Position Watchdog (alle 2h während Marktzeiten) ──
    # Watchdog läuft xx:05, Proposal Executor xx:25 — entzerrt Race vs Portfolio-State
    ('Position Watchdog',   'position_watchdog.py',            [],                10, 5,  [0,1,2,3,4]),
    ('Position Watchdog',   'position_watchdog.py',            [],                12, 5,  [0,1,2,3,4]),
    ('Position Watchdog',   'position_watchdog.py',            [],                14, 5,  [0,1,2,3,4]),
    ('Position Watchdog',   'position_watchdog.py',            [],                16, 5,  [0,1,2,3,4]),
    ('Position Watchdog',   'position_watchdog.py',            [],                18, 5,  [0,1,2,3,4]),
    ('Position Watchdog',   'position_watchdog.py',            [],                20, 5,  [0,1,2,3,4]),
    # ── Phase 18: Proposal Executor (globale Börsenzeiten, alle 2h, NACH Watchdog) ──
    ('Proposal Executor',   'proposal_executor.py',            [],                 8, 25, [0,1,2,3,4]),
    ('Proposal Executor',   'proposal_executor.py',            [],                10, 25, [0,1,2,3,4]),
    ('Proposal Executor',   'proposal_executor.py',            [],                12, 25, [0,1,2,3,4]),
    ('Proposal Executor',   'proposal_executor.py',            [],                14, 25, [0,1,2,3,4]),
    ('Proposal Executor',   'proposal_executor.py',            [],                16, 25, [0,1,2,3,4]),
    ('Proposal Executor',   'proposal_executor.py',            [],                18, 25, [0,1,2,3,4]),
    ('Proposal Executor',   'proposal_executor.py',            [],                20, 25, [0,1,2,3,4]),
    ('Proposal Executor',   'proposal_executor.py',            [],                22, 25, [0,1,2,3,4]),
    # ── Phase 18: Autonomous Pipeline (alle 2h, K8: xx:10 NACH Watchdog xx:05) ──
    ('Autonomous Pipeline', 'autonomous_pipeline.py',          [],                 9, 10, [0,1,2,3,4]),
    ('Autonomous Pipeline', 'autonomous_pipeline.py',          [],                11,10, [0,1,2,3,4]),
    ('Autonomous Pipeline', 'autonomous_pipeline.py',          [],                13,10, [0,1,2,3,4]),
    ('Autonomous Pipeline', 'autonomous_pipeline.py',          [],                15,10, [0,1,2,3,4]),
    ('Autonomous Pipeline', 'autonomous_pipeline.py',          [],                17,10, [0,1,2,3,4]),
    ('Autonomous Pipeline', 'autonomous_pipeline.py',          [],                19,10, [0,1,2,3,4]),
    ('Autonomous Pipeline', 'autonomous_pipeline.py',          [],                21,10, [0,1,2,3,4]),
    # ── Phase 16: Signal-Level Learning (Sonntag Vormittag) ──
    ('Signal Learning',     'intelligence/signal_learning.py', [],                9,  30, [6]),
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
    # ALLE Zeiten in CEST / deutscher Zeit (Server-TZ: Europe/Berlin)
    # Asien-Session (00:00-06:00 CEST) — alle 2h
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             0,  0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             2,  0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             4,  0,  None),
    ('Thesis Monitor',       'core/thesis_engine.py',  ['--monitor'],             6,  0,  None),
    # EU+US-Session (07:00-21:00 CEST) — alle 30 Min, taeglich
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
    # ── Phase 22: Entry-Trigger-Poll (T1/T2/T3) — alle 2h waehrend Marktzeit ──
    ('Thesis Trigger Poll',  'thesis_trigger_poll.py', [],                        9,  15, None),
    ('Thesis Trigger Poll',  'thesis_trigger_poll.py', [],                        11, 15, None),
    ('Thesis Trigger Poll',  'thesis_trigger_poll.py', [],                        13, 15, None),
    ('Thesis Trigger Poll',  'thesis_trigger_poll.py', [],                        15, 15, None),
    ('Thesis Trigger Poll',  'thesis_trigger_poll.py', [],                        17, 15, None),
    ('Thesis Trigger Poll',  'thesis_trigger_poll.py', [],                        19, 15, None),
    ('Thesis Trigger Poll',  'thesis_trigger_poll.py', [],                        21, 15, None),
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
    ('Thesis Discovery',   'intelligence/thesis_discovery.py', [],              5,  0,  None),   # Taeglich 05:00 CEST (vor EU-Open)
    # ── Fast Discovery: Trigger thesis_discovery sofort bei Geo-Alert HIGH ──
    # Läuft alle 30min, prüft ceo_directive.json. Bei LOW/MEDIUM→HIGH Transition
    # spawnt es thesis_discovery.py (statt 12h auf nächste 05:00 zu warten).
    # Debounce 4h, max 3 Trigger/Tag.
    ('Fast Discovery 09', 'fast_discovery_trigger.py', [],   9,  15, None),
    ('Fast Discovery 10', 'fast_discovery_trigger.py', [],   10, 15, None),
    ('Fast Discovery 11', 'fast_discovery_trigger.py', [],   11, 15, None),
    ('Fast Discovery 12', 'fast_discovery_trigger.py', [],   12, 15, None),
    ('Fast Discovery 13', 'fast_discovery_trigger.py', [],   13, 15, None),
    ('Fast Discovery 14', 'fast_discovery_trigger.py', [],   14, 15, None),
    ('Fast Discovery 15', 'fast_discovery_trigger.py', [],   15, 15, None),
    ('Fast Discovery 16', 'fast_discovery_trigger.py', [],   16, 15, None),
    ('Fast Discovery 17', 'fast_discovery_trigger.py', [],   17, 15, None),
    ('Fast Discovery 18', 'fast_discovery_trigger.py', [],   18, 15, None),
    ('Fast Discovery 19', 'fast_discovery_trigger.py', [],   19, 15, None),
    ('Fast Discovery 20', 'fast_discovery_trigger.py', [],   20, 15, None),
    ('Fast Discovery 21', 'fast_discovery_trigger.py', [],   21, 15, None),
    ('Fast Discovery 22', 'fast_discovery_trigger.py', [],   22, 15, None),
    # ═══════════════════════════════════════════════════════════════════════════
    # ── Autonomous Scanner — GLOBAL (ALLE Zeiten in CEST / deutscher Zeit) ────
    # ═══════════════════════════════════════════════════════════════════════════
    # Server TZ: Europe/Berlin → scheduler liest datetime.now() als Lokalzeit.
    # Abdeckung der 3 globalen Sessions die wir handeln (Asien, Europa, US):
    #
    #   Asien (Tokyo/HK/Shanghai):   01:00–10:00 CEST
    #   Europa (Xetra/LSE/Euronext): 09:00–17:30 CEST
    #   US (NYSE/Nasdaq Regular):    15:30–22:00 CEST
    #   US Post-Market (limitiert):  22:00–00:00 CEST
    # ═══════════════════════════════════════════════════════════════════════════
    # --- ASIEN-FENSTER 03:00-07:00 CEST (stuendlich, 5 Runs) ------------------
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   3,  0,  [0,1,2,3,4]),   # Tokyo early session
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   4,  0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   5,  0,  [0,1,2,3,4]),   # HK/Shanghai open
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   6,  0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   7,  0,  [0,1,2,3,4]),   # Tokyo close approach
    # --- EUROPA-FENSTER 09:00-17:30 CEST (alle 30min, 17 Runs) ---------------
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   9,  0,  [0,1,2,3,4]),   # Xetra open
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
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   15, 30, [0,1,2,3,4]),   # US Pre-Market
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   16, 0,  [0,1,2,3,4]),   # NYSE open (15:30 CEST)
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   16, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   17, 0,  [0,1,2,3,4]),   # US Opening Range
    # --- US-HAUPTFENSTER 17:30-22:00 CEST (alle 30min, 10 Runs — 51% WR) -----
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   17, 30, [0,1,2,3,4]),   # Xetra close, US active
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   18, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   18, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   19, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   19, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   20, 0,  [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   20, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   21, 0,  [0,1,2,3,4]),   # US letzte Stunde
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   21, 30, [0,1,2,3,4]),
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   22, 0,  [0,1,2,3,4]),   # NYSE Close (22:00 CEST)
    # --- US-POST-MARKET 22:30-23:00 CEST (2 Runs) ----------------------------
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   22, 30, [0,1,2,3,4]),   # Post-Market Earnings
    ('Auto Scanner',  'execution/autonomous_scanner.py', [],   23, 0,  [0,1,2,3,4]),
    # --- WOCHENENDE Geo/News-Scan --------------------------------------------
    ('Weekend Geo Scan',  'execution/autonomous_scanner.py', [], 10, 0, [5,6]),   # Sa+So 10:00 CEST
    ('Weekend Geo Scan',  'execution/autonomous_scanner.py', [], 18, 0, [5,6]),   # Sa+So 18:00 CEST
    # ── Lab Scanner: DEAKTIVIERT 18.04.2026 ──────────────────────────────────
    # Lab-Mode erzeugte _LAB-Positionen mit 30k€ Exposure (> Fund-Budget).
    # Cash-Berechnung zaehlte LAB-Trades mit → Portfolio zeigte -33955€ Cash,
    # -235% Performance. Bis LAB-Positionen in Reporting separiert sind, OFF.
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  8,  45, [0,1,2,3,4]),
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  9,  45, [0,1,2,3,4]),
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  10, 45, [0,1,2,3,4]),
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  11, 45, [0,1,2,3,4]),
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  12, 45, [0,1,2,3,4]),
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  13, 45, [0,1,2,3,4]),
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  14, 45, [0,1,2,3,4]),
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  15, 45, [0,1,2,3,4]),
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  16, 45, [0,1,2,3,4]),
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  17, 45, [0,1,2,3,4]),
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  18, 45, [0,1,2,3,4]),
    # ('Lab Scanner',   'execution/autonomous_scanner.py', ['--lab'],  19, 45, [0,1,2,3,4]),
    # ── Backtest v2: So+Mi 08:00 CEST (nach Thesis Discovery 07:00 CEST) ────────
    ('Backtest v2',   'backtest_engine_v2.py',           [],         8,  0,  [6]),   # So 08:00 CEST
    ('Backtest v2',   'backtest_engine_v2.py',           [],         8,  0,  [2]),   # Mi 08:00 CEST (Mid-Week Refresh)
    # ── Phase 23: Macro-Liquidity Tracker — 2x taeglich (07:00 vor EU-Open + 14:00 vor US-Open) ──
    # FRED-Daten werden taeglich aktualisiert. Repo-Stress-Alarm via Discord bei SOFR-IORB > 10bps.
    ('Macro Liquidity', 'macro/net_liquidity_tracker.py', [],         7,  0,  None),
    ('Macro Liquidity', 'macro/net_liquidity_tracker.py', [],         14, 0,  None),
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

def notify(msg: str, *, tier: str = 'HIGH', category: str = 'scheduler',
           dedupe_key: str | None = None):
    """Sendet Discord-Nachricht via Dispatcher (mit Tier + Dedupe).

    Default TIER_HIGH für Rückwärtskompatibilität (Startup-Notifications etc.).
    Job-Fehler sollten TIER_MEDIUM + Dedupe-Key (Job-Name) übergeben, damit
    wiederholte Crashes nicht alle 30 min spammen."""
    try:
        sys.path.insert(0, str(SCRIPTS))
        from discord_dispatcher import send_alert, TIER_HIGH, TIER_MEDIUM, TIER_LOW
        tier_map = {'HIGH': TIER_HIGH, 'MEDIUM': TIER_MEDIUM, 'LOW': TIER_LOW}
        send_alert(
            msg,
            tier=tier_map.get(tier, TIER_HIGH),
            category=category,
            dedupe_key=dedupe_key,
        )
    except Exception as e:
        log(f'Discord-Fehler: {e}')
        # Legacy-Fallback wenn Dispatcher kaputt
        try:
            from discord_sender import send
            send(msg)
        except Exception:
            pass


# ── Job Runner ────────────────────────────────────────────────────────────────

def _filter_discord_output(output: str) -> str:
    """Filtert Job-stdout für Discord — behält nur echte Alerts, nicht Debug-Logs.

    Behalten:
      - Zeilen die mit Emoji/Symbol starten (🔴🟢📡📊🌙📅🚨⚠️🔍🤖📈📉🧭💼🔄)
      - Zeilen die mit ** (Markdown-Bold) starten
      - Zeilen die 'ERROR', 'FEHLER', 'WARNUNG' enthalten (echte Probleme)
      - Leerzeilen innerhalb eines Alerts (Struktur erhalten)

    Verwerfen:
      - Zeilen die mit '[xxx]' starten (Prozess-Log Präfixe)
      - 'Discord-Briefing gesendet', 'Daily Review sent', 'Report saved'
      - '...generiert', 'Total:', 'Analysiere...' Debug-Noise
      - Stats-Zeilen wenn kein Alert drum herum ist
    """
    import re
    lines = output.split('\n')
    kept = []
    has_real_content = False

    # Wenn die erste Zeile ein echter Alert-Header ist (mit Emoji oder **Bold**),
    # dann behalten wir den ganzen Block — das ist ein formatierter Report.
    first_nonempty = next((l for l in lines if l.strip()), '')
    starts_with_alert = bool(re.match(
        r'^[🔴🟢📡📊🌙📅🚨⚠️🔍🤖📈📉🧭💼🔄📧💡🛑⚡🎯🌅🌇🌑🎆📅🌙]|^\*\*',
        first_nonempty
    ))

    if starts_with_alert:
        # Formatierter Report → komplett durchlassen, aber Meta-Zeilen am Ende droppen
        for line in lines:
            l = line.strip()
            # Typische Tail-Noise nach einem Report:
            if re.match(r'^\[[\w\-]+\]\s', l):
                continue  # [evening_report] Briefing gesendet…
            if re.match(r'^(Daily Review sent|Report saved|Discord-Briefing gesendet)', l, re.I):
                continue
            kept.append(line)
            if l and not l.startswith('['):
                has_real_content = True
    else:
        # Kein Alert-Header → es ist ein reines Debug-Log. Nur Error-Zeilen durchlassen.
        for line in lines:
            l = line.strip()
            if not l:
                continue
            if re.search(r'\b(ERROR|FEHLER|EXCEPTION|TRACEBACK|CRITICAL)\b', l):
                kept.append(line)
                has_real_content = True

    return '\n'.join(kept).strip() if has_real_content else ''


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
                _day = datetime.now().strftime('%Y%m%d')
                _slug = name.lower().replace(' ', '_')
                # Phase 45p: 3 Briefings + Friday-Briefing bekommen
                # eigene Categories damit sie die strikte Whitelist passieren.
                _briefing_map = {
                    'morgen-briefing': 'morning_brief',
                    'mid-day briefing': 'midday_brief',
                    'albert improvement digest': 'improvement_digest',
                    'us opening':      'us_open_brief',
                    'us-opening':      'us_open_brief',
                    'abend-report':    'evening_brief',
                    'friday briefing': 'friday_briefing',
                    'week ahead briefing': 'week_ahead_briefing',
                }
                _cat = _briefing_map.get(name.lower(), 'job')
                _is_briefing = _cat != 'job'

                # Phase 45q (Victor 2026-05-06): Briefings duerfen NICHT
                # gefiltert werden — sie sind selbst der Inhalt.
                # Phase 45an (Victor 2026-05-11): Briefings auf Narrative
                # reduzieren — Victor will NUR Text-Form auf Discord, keine
                # Bullet-Tabellen. Wenn Narrativ-Marker gefunden → nur den
                # Block ab Marker pushen. Volltext bleibt im scheduler.log.
                if _is_briefing:
                    # Phase 45an: Narrativ-Marker — alle bekannten Briefing-Heads
                    _markers = ['📖 **MORGEN-NARRATIV:**', '📖 **US-OPEN-NARRATIV:**',
                                '📖 **ABEND-NARRATIV:**', '📖 **NARRATIV:**',
                                '📖 ÜBERNACHT', '📖 TAGESPLAN', '📖 **', '📖 ']
                    payload = output
                    for _mk in _markers:
                        if _mk in output:
                            _idx = output.find(_mk)
                            payload = output[_idx:]
                            break
                else:
                    payload = _filter_discord_output(output)

                if payload and len(payload) > 20:
                    _tier = 'HIGH' if _is_briefing else 'MEDIUM'
                    notify(payload[:1900], tier=_tier, category=_cat,
                           dedupe_key=f'job_{_slug}_{_day}')
                    log(f'✅ {name}: OK + Discord gesendet ({len(payload)} chars, orig {len(output)})')
                else:
                    log(f'✅ {name}: OK (stdout war nur Debug-Log, kein Discord)')
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
        # Phase 45az (Victor 2026-05-14): voller Stack-Trace statt nur Message.
        # Audit-Befund: ~17 stille Crashes/Tag — ohne Trace nicht debugbar.
        log(f'💥 {name}: Exception — {e}')
        log(f'   TRACEBACK:\n{traceback.format_exc()}')
        return False


# ── Scheduler Loop ────────────────────────────────────────────────────────────

def should_run(hour, minute, weekdays, now=None) -> bool:
    """Prüft ob ein Job jetzt laufen soll (innerhalb ±30s Fenster).

    Sub-10 Erweiterung: hour/minute unterstuetzen jetzt auch:
      - int  (klassisch, exakt: hour=9, minute=30)
      - '*'  (jede Stunde bzw. jede Minute)
      - '*/N' (alle N Stunden/Minuten, z.B. minute='*/15')
      - list[int] (mehrere erlaubte Werte, z.B. minute=[0,15,30,45])
    Backward-compatible: bestehende int-Eintraege funktionieren unveraendert.

    Phase 45am (Victor 2026-05-11): now-Param injizierbar — Loop friert
    Zeit am Anfang ein, damit langsame Jobs die spätere Job-Slots nicht
    überspringen (Bug: Morgen-Briefing 08:00 verpasst weil vorherige Jobs
    bis 08:01 brauchten).
    """
    if now is None:
        now = datetime.now()

    def _match(val, current: int, mod: int) -> bool:
        if isinstance(val, int):
            return current == val
        if isinstance(val, (list, tuple, set)):
            return current in val
        if isinstance(val, str):
            if val == '*':
                return True
            if val.startswith('*/'):
                try:
                    n = int(val[2:])
                    return n > 0 and current % n == 0
                except ValueError:
                    return False
        return False

    if not _match(hour, now.hour, 24):
        return False
    if not _match(minute, now.minute, 60):
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
    # PID sofort persistieren, damit Watchdog-Aufrufe die Instanz erkennen
    try:
        monitor_pid_file.write_text(str(proc.pid), encoding="utf-8")
    except Exception as _e:
        log(f'⚠️  PID-File konnte nicht geschrieben werden: {_e}')
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

    # Heartbeat-File für externen Watchdog (heartbeat_monitor.py).
    # Wird jede Minute geschrieben — wenn älter als 600s, restartet Cron-Watchdog
    # den Scheduler. Bug K (2026-04-22): vorher fehlte das komplett → Restart-Loop.
    HEARTBEAT_FILE = WS / 'data' / 'scheduler_heartbeat.txt'

    def _write_heartbeat():
        try:
            HEARTBEAT_FILE.write_text(
                datetime.now(timezone.utc).isoformat(),
                encoding='utf-8',
            )
        except Exception as _e:
            log(f'⚠️  Heartbeat-Write-Fehler: {_e}')

    while True:
        now = datetime.now()
        current_key = f'{now.strftime("%Y-%m-%d %H:%M")}'

        # Heartbeat — JEDE Minute, vor allen Jobs
        _write_heartbeat()

        # Subthread-Watchdog (vor Job-Dispatch)
        try:
            _subthread_healthcheck()
        except Exception as _hc_err:
            log(f'⚠️  Healthcheck-Fehler: {_hc_err}')

        # Phase 45am: Loop-Snapshot — alle Jobs in diesem Pass sehen die
        # SELBE Zeit, auch wenn vorherige Jobs lang gelaufen sind.
        # Verhindert dass Briefing-Slot 08:00 verpasst wird wenn vorherige
        # 08:00-Jobs sequentiell bis 08:01 dauern.
        loop_now = now
        for entry in SCHEDULE:
            # Phase 45az (Victor 2026-05-14): Per-Job-Guard im Dispatch.
            # Audit-Befund: ~17 stille Daemon-Crashes/Tag → systemd-Restart-Loop,
            # kein Stack-Trace. Jetzt: Dispatch-Fehler werden mit vollem Trace
            # geloggt UND der Daemon läuft weiter (keine Maskierung, keine Crash-Loop).
            try:
                name, script, args, hour, minute, weekdays = entry[:6]
                discord_send = entry[6] if len(entry) > 6 else False

                job_key = f'{name}_{current_key}'
                if job_key in last_run:
                    continue

                if should_run(hour, minute, weekdays, now=loop_now):
                    last_run[job_key] = True
                    # Cleanup alter Einträge
                    if len(last_run) > 1000:
                        old_keys = list(last_run.keys())[:-500]
                        for k in old_keys:
                            del last_run[k]

                    success = run_job(name, script, args, discord=discord_send)

                    # Bestimmte Jobs senden Discord-Notification bei Fehler
                    if not success:
                        # TIER_MEDIUM + Dedupe pro Job-Name → max. 1 Alert pro Tag
                        # (24h-Window im Dispatcher), rest geht in den Digest.
                        _slug = name.lower().replace(' ', '_')
                        notify(
                            f'⚠️ **Scheduler:** {name} fehlgeschlagen — Logs: data/scheduler.log',
                            tier='MEDIUM',
                            category='scheduler',
                            dedupe_key=f'sched_fail_{_slug}',
                        )
            except Exception as _dispatch_err:
                _ename = entry[0] if entry else '?'
                log(f'💥 Dispatch-Crash bei Job "{_ename}": {_dispatch_err}')
                log(f'   TRACEBACK:\n{traceback.format_exc()}')
                notify(
                    f'🚨 **Scheduler Dispatch-Crash:** {_ename} — {_dispatch_err}\n'
                    f'Daemon läuft weiter. Trace in data/scheduler.log',
                    tier='HIGH', category='scheduler_crash',
                    dedupe_key=f'dispatch_crash_{type(_dispatch_err).__name__.lower()}',
                )

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
            log(f'   TRACEBACK:\n{traceback.format_exc()}')
            # Crash-Notify mit Dedupe: pro Error-Typ max 1× pro Stunde
            # (verhindert Flut wenn systemd in Crash-Restart-Loop steht)
            _err_slug = type(e).__name__.lower()
            from datetime import datetime as _dt
            _hour_bucket = _dt.now().strftime('%Y%m%d%H')
            notify(f'🚨 **TradeMind Scheduler CRASH:** {e}\nNeustart nötig!',
                   tier='HIGH', category='scheduler_crash',
                   dedupe_key=f'crash_{_err_slug}_{_hour_bucket}')
            PID_FILE.unlink(missing_ok=True)
            raise
