#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# TradeMind VPS Setup — Hetzner CX22 (Ubuntu 24.04)
# ═══════════════════════════════════════════════════════════════════
# Verwendung:
#   1. Hetzner CX22 bestellen (Ubuntu 24.04, Falkenstein/Nürnberg)
#   2. ssh root@<IP>
#   3. git clone https://github.com/Vic3d/Trade-Bot.git /opt/trademind
#   4. cp /opt/trademind/deploy/.env.example /opt/trademind/deploy/.env
#   5. nano /opt/trademind/deploy/.env  ← Secrets eintragen
#   6. bash /opt/trademind/deploy/setup-vps.sh
#   7. Fertig — Bot läuft autonom
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

TRADEMIND_HOME="/opt/trademind"
DEPLOY_DIR="$TRADEMIND_HOME/deploy"

echo "═══════════════════════════════════════════════════"
echo "  TradeMind VPS Setup"
echo "═══════════════════════════════════════════════════"

# ─── Prüfungen ──────────────────────────────────────────────────────

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte als root ausfuehren: sudo bash $0"
    exit 1
fi

if [ ! -f "$DEPLOY_DIR/.env" ]; then
    echo "deploy/.env fehlt!"
    echo "   cp $DEPLOY_DIR/.env.example $DEPLOY_DIR/.env"
    echo "   nano $DEPLOY_DIR/.env"
    exit 1
fi

echo "[OK] Pruefungen bestanden"

# ─── 1. System aktualisieren ────────────────────────────────────────

echo ""
echo "[1/8] System aktualisieren..."
apt update -qq && apt upgrade -y -qq
apt install -y -qq software-properties-common curl git ufw

# ─── 2. Python 3.12 (Ubuntu 24.04 default) + venv/dev ──────────────

echo ""
echo "[2/8] Python 3.12 + venv installieren..."
apt install -y -qq python3 python3-venv python3-dev python3-pip

python3 --version
echo "[OK] Python installiert"

# ─── 3. Trademind User erstellen ─────────────────────────────────────

echo ""
echo "[3/8] User 'trademind' erstellen..."
if ! id -u trademind &>/dev/null; then
    useradd -r -m -s /bin/bash -d /home/trademind trademind
    echo "[OK] User erstellt"
else
    echo "[INFO] User existiert bereits"
fi

# Ownership setzen
chown -R trademind:trademind "$TRADEMIND_HOME"

# ─── 4. Python venv + Dependencies ──────────────────────────────────

echo ""
echo "[4/8] Python venv + Dependencies installieren..."
sudo -u trademind python3 -m venv "$TRADEMIND_HOME/venv"

# Torch CPU-only separat (wegen --index-url)
sudo -u trademind "$TRADEMIND_HOME/venv/bin/pip" install --quiet --upgrade pip
sudo -u trademind "$TRADEMIND_HOME/venv/bin/pip" install --quiet \
    torch --index-url https://download.pytorch.org/whl/cpu

# Rest der Dependencies
sudo -u trademind "$TRADEMIND_HOME/venv/bin/pip" install --quiet \
    numpy scipy hmmlearn river pandas yfinance \
    exchange_calendars pydantic anthropic

echo "[OK] Dependencies installiert"

# ─── 5. Verzeichnisse + Symlink ──────────────────────────────────────

echo ""
echo "[5/8] Verzeichnisse + Symlink..."

# Daten-Verzeichnisse
sudo -u trademind mkdir -p "$TRADEMIND_HOME/data/price_cache"
sudo -u trademind mkdir -p "$TRADEMIND_HOME/data/rl_checkpoints"
sudo -u trademind mkdir -p "$TRADEMIND_HOME/data/research"
sudo -u trademind mkdir -p "$TRADEMIND_HOME/memory"
sudo -u trademind mkdir -p "$TRADEMIND_HOME/transcripts"

# Backward-compatible Symlink (Scripts referenzieren /data/.openclaw/workspace/)
mkdir -p /data/.openclaw
ln -sfn "$TRADEMIND_HOME" /data/.openclaw/workspace
echo "[OK] Symlink: /data/.openclaw/workspace -> $TRADEMIND_HOME"

# OpenClaw Config fuer Discord (backward-compatible)
if [ ! -f /data/.openclaw/openclaw.json ]; then
    source "$DEPLOY_DIR/.env"
    cat > /data/.openclaw/openclaw.json <<EOCFG
{
  "channels": {
    "discord": {
      "token": "${DISCORD_BOT_TOKEN:-BITTE_EINTRAGEN}"
    }
  }
}
EOCFG
    chown trademind:trademind /data/.openclaw/openclaw.json
    echo "[OK] openclaw.json erstellt"
fi

# ─── 6. Environment-Datei fuer systemd ──────────────────────────────

echo ""
echo "[6/8] Environment konfigurieren..."

# .env in systemd-kompatibles Format kopieren (nur KEY=VALUE Zeilen)
grep -v '^#' "$DEPLOY_DIR/.env" | grep -v '^$' > /etc/trademind.env 2>/dev/null || true
chmod 600 /etc/trademind.env
echo "[OK] /etc/trademind.env erstellt"

# ─── 7. systemd Services ────────────────────────────────────────────

echo ""
echo "[7/8] systemd Services einrichten..."

cp "$DEPLOY_DIR/trademind-scheduler.service" /etc/systemd/system/
cp "$DEPLOY_DIR/trademind-api.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable trademind-scheduler
systemctl enable trademind-api

# Crons einrichten
chmod +x "$DEPLOY_DIR/sync-dashboard.sh"
chmod +x "$DEPLOY_DIR/watchdog-cron.sh"

# Dashboard-Sync alle 30 Min + Watchdog alle 5 Min
SYNC_CRON="*/30 * * * * /opt/trademind/deploy/sync-dashboard.sh >> /opt/trademind/data/sync.log 2>&1"
WATCHDOG_CRON="*/5 * * * * /opt/trademind/deploy/watchdog-cron.sh >> /opt/trademind/data/watchdog.log 2>&1"
(crontab -u root -l 2>/dev/null | grep -v sync-dashboard | grep -v watchdog-cron; echo "$SYNC_CRON"; echo "$WATCHDOG_CRON") | crontab -u root -

echo "[OK] Services registriert"

# ─── 8. Firewall ────────────────────────────────────────────────────

echo ""
echo "[8/8] Firewall konfigurieren..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 8765/tcp comment 'TradeMind API'
echo "y" | ufw enable
echo "[OK] Firewall aktiv (SSH + Port 8765)"

# ─── Services starten ───────────────────────────────────────────────

echo ""
echo "Services starten..."
systemctl start trademind-scheduler
systemctl start trademind-api

sleep 3

# ─── Status prüfen ──────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════"
echo "  TradeMind Setup abgeschlossen!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Status:"
systemctl is-active trademind-scheduler && echo "  [RUNNING] Scheduler" || echo "  [ERROR] Scheduler!"
systemctl is-active trademind-api && echo "  [RUNNING] API" || echo "  [ERROR] API!"
echo ""
echo "Nuetzliche Befehle:"
echo "  journalctl -u trademind-scheduler -f    # Scheduler-Log live"
echo "  journalctl -u trademind-api -f          # API-Log live"
echo "  tail -f /opt/trademind/data/scheduler.log"
echo "  curl http://localhost:8765/api/portfolio # Portfolio abfragen"
echo "  systemctl restart trademind-scheduler    # Scheduler neustarten"
echo ""
echo "Dashboard-Sync: laeuft alle 30 Min via Cron"
echo "  Log: /opt/trademind/data/sync.log"
echo ""
