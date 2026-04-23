#!/bin/bash
# Smoke-Test alle Scheduler-Scripts. Triggert jedes mit timeout, sammelt Exit-Code + stderr.
# Lauf als: sudo -u trademind bash /tmp/_smoke_test.sh

cd /opt/trademind
mkdir -p /tmp/smoke_results
> /tmp/smoke_results/SUMMARY.txt
> /tmp/smoke_results/FAILURES.txt

# Format: script_path | optional args | timeout_sec
SCRIPTS=(
  "scripts/core/live_data.py|--refresh|120"
  "scripts/core/thesis_engine.py||60"
  "scripts/advisory_layer.py||60"
  "scripts/alpha_decay.py||60"
  "scripts/asia_lead_signal.py||60"
  "scripts/catalyst_calendar.py||60"
  "scripts/ceo.py|--live|60"
  "scripts/commodity_refresh.py||60"
  "scripts/daily_learning_cycle.py||90"
  "scripts/daily_review.py||60"
  "scripts/daily_summary.py||60"
  "scripts/discovery/discovery_pipeline.py||120"
  "scripts/discovery/earnings_calendar.py||60"
  "scripts/discovery/market_scanner.py||60"
  "scripts/discovery/news_ticker_extractor.py||60"
  "scripts/discovery/price_backfill.py||60"
  "scripts/discovery/smart_money_tracker.py||60"
  "scripts/earnings_calendar.py||60"
  "scripts/evening_report.py||60"
  "scripts/execution/autonomous_scanner.py||120"
  "scripts/feature_analyzer.py||60"
  "scripts/feature_importance.py||60"
  "scripts/intelligence/catalyst_reeval.py||60"
  "scripts/intelligence/catalyst_to_profiteer.py||60"
  "scripts/intelligence/insider_refresh.py||60"
  "scripts/intelligence/political_risk_detector.py||60"
  "scripts/intelligence/thesis_discovery.py||90"
  "scripts/midterm_election_bias.py||60"
  "scripts/morning_brief_generator.py||90"
  "scripts/news_ceo_radar.py||60"
  "scripts/news_gate_updater.py||60"
  "scripts/newswire_analyst.py||60"
  "scripts/overnight_collector.py||90"
  "scripts/pain_trade_scanner.py||60"
  "scripts/performance_tracker.py||60"
  "scripts/portfolio_circuit_breaker.py||60"
  "scripts/regime_cache_refresh.py||60"
  "scripts/regime_detector.py|--integrate --quick|60"
  "scripts/scenario_mapper.py||60"
  "scripts/strategy_discovery.py||90"
  "scripts/thesis_generator.py||60"
  "scripts/thesis_graveyard.py||60"
  "scripts/thesis_news_hunter.py||90"
  "scripts/thesis_trigger_poll.py||60"
  "scripts/thesis_watchlist.py||60"
  "scripts/us_opening_report.py||60"
  "scripts/watchlist_tracker.py||60"
  "scripts/weekly_summary.py||60"
  "scripts/trading_monitor.py||90"
  "scripts/intelligence/market_guards.py||60"
)

PASS=0
FAIL=0
SKIP=0

for entry in "${SCRIPTS[@]}"; do
  IFS='|' read -r script args tmout <<< "$entry"
  name=$(basename "$script" .py)

  if [ ! -f "$script" ]; then
    echo "SKIP $name (file missing)" >> /tmp/smoke_results/SUMMARY.txt
    SKIP=$((SKIP+1))
    continue
  fi

  errfile="/tmp/smoke_results/${name}.err"
  outfile="/tmp/smoke_results/${name}.out"

  if [ -z "$args" ]; then
    timeout "${tmout}" venv/bin/python3 "$script" >"$outfile" 2>"$errfile"
  else
    timeout "${tmout}" venv/bin/python3 "$script" $args >"$outfile" 2>"$errfile"
  fi
  rc=$?

  if [ $rc -eq 0 ]; then
    echo "PASS $name" >> /tmp/smoke_results/SUMMARY.txt
    PASS=$((PASS+1))
  elif [ $rc -eq 124 ]; then
    echo "TIMEOUT($tmout) $name" >> /tmp/smoke_results/SUMMARY.txt
    echo "=== $name (TIMEOUT) ===" >> /tmp/smoke_results/FAILURES.txt
    tail -25 "$errfile" >> /tmp/smoke_results/FAILURES.txt
    echo "" >> /tmp/smoke_results/FAILURES.txt
    FAIL=$((FAIL+1))
  elif [ $rc -eq 2 ]; then
    # exit-code 2 = argparse missing arg → wahrscheinlich legitim
    echo "ARGS_NEEDED $name" >> /tmp/smoke_results/SUMMARY.txt
    SKIP=$((SKIP+1))
  else
    echo "FAIL($rc) $name" >> /tmp/smoke_results/SUMMARY.txt
    echo "=== $name (rc=$rc) ===" >> /tmp/smoke_results/FAILURES.txt
    tail -30 "$errfile" >> /tmp/smoke_results/FAILURES.txt
    echo "" >> /tmp/smoke_results/FAILURES.txt
    FAIL=$((FAIL+1))
  fi
done

echo ""
echo "=========================="
echo "RESULT: PASS=$PASS  FAIL=$FAIL  SKIP=$SKIP"
echo "=========================="
echo "Details: /tmp/smoke_results/SUMMARY.txt"
echo "Errors:  /tmp/smoke_results/FAILURES.txt"
