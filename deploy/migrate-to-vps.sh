#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# TradeMind — Daten-Migration von Windows zu Hetzner VPS
# ═══════════════════════════════════════════════════════════════════
#
# Ausfuehren auf dem WINDOWS-PC (Git Bash):
#
#   VPS_IP="<DEINE-HETZNER-IP>"
#   bash deploy/migrate-to-vps.sh $VPS_IP
#
# Voraussetzung:
#   - SSH-Zugang zum VPS als root
#   - setup-vps.sh wurde bereits auf dem VPS ausgefuehrt
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "Verwendung: bash deploy/migrate-to-vps.sh <VPS-IP>"
    echo "Beispiel:   bash deploy/migrate-to-vps.sh 168.119.42.123"
    exit 1
fi

VPS_IP="$1"
VPS_USER="root"
VPS_PATH="/opt/trademind"
LOCAL_PATH="$(cd "$(dirname "$0")/.." && pwd)"

echo "=================================================="
echo "  TradeMind Migration: Windows -> VPS"
echo "=================================================="
echo "  Lokal:  $LOCAL_PATH"
echo "  Remote: $VPS_USER@$VPS_IP:$VPS_PATH"
echo "=================================================="
echo ""

# ─── 1. Code synchronisieren ────────────────────────────────────────

echo "[1/6] Code synchronisieren (git push + pull)..."
cd "$LOCAL_PATH"

# Sicherstellen, dass alle Aenderungen committed sind
if [ -n "$(git status --porcelain)" ]; then
    echo "  WARNUNG: Uncommitted changes gefunden!"
    echo "  Bitte erst committen: git add -A && git commit -m 'pre-deploy'"
    echo "  Dann nochmal ausfuehren."
    exit 1
fi

git push origin master 2>/dev/null && echo "  [OK] Git push erfolgreich" || echo "  [SKIP] Push nicht moeglich (kein remote?)"

ssh "$VPS_USER@$VPS_IP" "cd $VPS_PATH && git pull origin master" 2>/dev/null && echo "  [OK] Git pull auf VPS" || echo "  [SKIP] Git pull fehlgeschlagen"

# ─── 2. SQLite Datenbanken ──────────────────────────────────────────

echo ""
echo "[2/6] SQLite Datenbanken uebertragen..."
for db_file in "data/trading.db" "newswire.db" "memory/newswire.db"; do
    if [ -f "$LOCAL_PATH/$db_file" ]; then
        scp "$LOCAL_PATH/$db_file" "$VPS_USER@$VPS_IP:$VPS_PATH/$db_file"
        echo "  [OK] $db_file"
    else
        echo "  [SKIP] $db_file nicht gefunden"
    fi
done

# ─── 3. JSON State-Dateien (data/) ──────────────────────────────────

echo ""
echo "[3/6] JSON-Daten uebertragen (data/)..."
# Alle JSON-Dateien in data/ (ohne Unterverzeichnisse)
rsync -av --include='*.json' --exclude='*' \
    "$LOCAL_PATH/data/" "$VPS_USER@$VPS_IP:$VPS_PATH/data/" \
    2>/dev/null && echo "  [OK] data/*.json" || {
    # Fallback ohne rsync
    echo "  rsync nicht verfuegbar, nutze scp..."
    scp "$LOCAL_PATH"/data/*.json "$VPS_USER@$VPS_IP:$VPS_PATH/data/"
    echo "  [OK] data/*.json (via scp)"
}

# ─── 4. RL Checkpoints + Price Cache ────────────────────────────────

echo ""
echo "[4/6] RL Checkpoints + Price Cache..."
rsync -av "$LOCAL_PATH/data/rl_checkpoints/" "$VPS_USER@$VPS_IP:$VPS_PATH/data/rl_checkpoints/" \
    2>/dev/null && echo "  [OK] rl_checkpoints/" || {
    scp -r "$LOCAL_PATH/data/rl_checkpoints" "$VPS_USER@$VPS_IP:$VPS_PATH/data/"
    echo "  [OK] rl_checkpoints/ (via scp)"
}

rsync -av "$LOCAL_PATH/data/price_cache/" "$VPS_USER@$VPS_IP:$VPS_PATH/data/price_cache/" \
    2>/dev/null && echo "  [OK] price_cache/" || {
    scp -r "$LOCAL_PATH/data/price_cache" "$VPS_USER@$VPS_IP:$VPS_PATH/data/"
    echo "  [OK] price_cache/ (via scp)"
}

# ─── 5. Memory + Config ─────────────────────────────────────────────

echo ""
echo "[5/6] Memory + Config..."
rsync -av "$LOCAL_PATH/memory/" "$VPS_USER@$VPS_IP:$VPS_PATH/memory/" \
    2>/dev/null && echo "  [OK] memory/" || {
    scp -r "$LOCAL_PATH/memory" "$VPS_USER@$VPS_IP:$VPS_PATH/"
    echo "  [OK] memory/ (via scp)"
}

scp "$LOCAL_PATH/trading_config.json" "$VPS_USER@$VPS_IP:$VPS_PATH/trading_config.json" \
    && echo "  [OK] trading_config.json"

# .env (Secrets)
scp "$LOCAL_PATH/deploy/.env" "$VPS_USER@$VPS_IP:$VPS_PATH/deploy/.env" \
    && echo "  [OK] deploy/.env (Secrets)"

# Discord Chat Log
if [ -f "$LOCAL_PATH/data/discord_chat_log.jsonl" ]; then
    scp "$LOCAL_PATH/data/discord_chat_log.jsonl" "$VPS_USER@$VPS_IP:$VPS_PATH/data/discord_chat_log.jsonl"
    echo "  [OK] discord_chat_log.jsonl"
fi

# ─── 6. Ownership + Services starten ────────────────────────────────

echo ""
echo "[6/6] VPS konfigurieren + Services starten..."
ssh "$VPS_USER@$VPS_IP" bash <<'REMOTE'
    # Ownership fuer trademind User setzen
    chown -R trademind:trademind /opt/trademind/data
    chown -R trademind:trademind /opt/trademind/memory
    chown trademind:trademind /opt/trademind/trading_config.json
    chown trademind:trademind /opt/trademind/deploy/.env
    chmod 600 /opt/trademind/deploy/.env

    # .env in systemd-kompatibles Format
    grep -v '^#' /opt/trademind/deploy/.env | grep -v '^$' > /etc/trademind.env 2>/dev/null || true
    chmod 600 /etc/trademind.env

    # Services neustarten
    systemctl restart trademind-scheduler
    systemctl restart trademind-api

    sleep 3

    echo ""
    echo "=================================================="
    echo "  VPS Status"
    echo "=================================================="
    systemctl is-active trademind-scheduler && echo "  [RUNNING] Scheduler" || echo "  [ERROR] Scheduler"
    systemctl is-active trademind-api && echo "  [RUNNING] API" || echo "  [ERROR] API"

    # Quick Health-Check
    TRADES=$(sqlite3 /opt/trademind/data/trading.db "SELECT COUNT(*) FROM paper_portfolio" 2>/dev/null || echo "?")
    OPEN=$(sqlite3 /opt/trademind/data/trading.db "SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'" 2>/dev/null || echo "?")
    echo "  DB: $TRADES Trades total, $OPEN offen"
    echo ""
REMOTE

echo ""
echo "=================================================="
echo "  Migration abgeschlossen!"
echo "=================================================="
echo ""
echo "Naechste Schritte:"
echo "  1. Pruefe Logs:   ssh $VPS_USER@$VPS_IP 'journalctl -u trademind-scheduler -f'"
echo "  2. Pruefe API:    ssh $VPS_USER@$VPS_IP 'curl -s http://localhost:8765/api/portfolio | head -20'"
echo "  3. Discord-Test:  Schreibe Albert eine Nachricht im Discord"
echo ""
echo "  Windows-Bot stoppen:"
echo "    taskkill /F /IM python3.14.exe  (auf Windows)"
echo ""
