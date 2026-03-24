#!/bin/bash
# Wrapper für Options Flow Scanner
# Gibt nur die Alert-Nachricht aus, oder nichts wenn kein Alert
cd /data/.openclaw/workspace
python3 scripts/options_flow_scanner.py 2>/dev/null | grep -A1000 "^🚨" | grep -v "^DISCORD_ALERT:" || true
