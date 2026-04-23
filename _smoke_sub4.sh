#!/bin/bash
# Sub-4 Smoke-Test
cd /opt/trademind
mkdir -p /tmp/sub4
> /tmp/sub4/SUMMARY.txt
> /tmp/sub4/FAILS.txt

# Module die NICHT autonom Trades öffnen sollen — nur Imports + dry run
SCRIPTS=(
  "scripts/execution/paper_trade_engine.py||30"
  "scripts/execution/position_review.py||60"
  "scripts/execution/position_sizing.py||30"
  "scripts/execution/risk_manager.py||30"
  "scripts/execution/tax_tracker.py||30"
  "scripts/execution/transaction_costs.py||30"
  "scripts/execution/trade_proposal.py||30"
  "scripts/proposal_executor.py||60"
  "scripts/proposal_expirer.py||30"
  "scripts/position_update.py||60"
  "scripts/position_watchdog.py||60"
  "scripts/portfolio_risk.py||60"
  "scripts/risk_dashboard.py||30"
)

PASS=0
FAIL=0
ARGS=0

for entry in "${SCRIPTS[@]}"; do
  IFS='|' read -r script args tmout <<< "$entry"
  name=$(basename "$script" .py)
  if [ ! -f "$script" ]; then
    echo "SKIP $name (file missing)" >> /tmp/sub4/SUMMARY.txt
    continue
  fi

  errfile="/tmp/sub4/${name}.err"
  outfile="/tmp/sub4/${name}.out"

  if [ -z "$args" ]; then
    timeout "${tmout}" venv/bin/python3 "$script" >"$outfile" 2>"$errfile"
  else
    timeout "${tmout}" venv/bin/python3 "$script" $args >"$outfile" 2>"$errfile"
  fi
  rc=$?

  if [ $rc -eq 0 ]; then
    echo "PASS $name" >> /tmp/sub4/SUMMARY.txt
    PASS=$((PASS+1))
  elif [ $rc -eq 124 ]; then
    echo "TIMEOUT($tmout) $name" >> /tmp/sub4/SUMMARY.txt
    echo "=== $name (TIMEOUT) ===" >> /tmp/sub4/FAILS.txt
    tail -20 "$errfile" "$outfile" >> /tmp/sub4/FAILS.txt
    echo "" >> /tmp/sub4/FAILS.txt
    FAIL=$((FAIL+1))
  elif [ $rc -eq 2 ]; then
    echo "ARGS_NEEDED $name" >> /tmp/sub4/SUMMARY.txt
    ARGS=$((ARGS+1))
  else
    echo "FAIL($rc) $name" >> /tmp/sub4/SUMMARY.txt
    echo "=== $name (rc=$rc) ===" >> /tmp/sub4/FAILS.txt
    tail -30 "$errfile" >> /tmp/sub4/FAILS.txt
    echo "" >> /tmp/sub4/FAILS.txt
    FAIL=$((FAIL+1))
  fi
done

echo ""
echo "=========================="
echo "RESULT: PASS=$PASS  FAIL=$FAIL  ARGS=$ARGS"
cat /tmp/sub4/SUMMARY.txt
