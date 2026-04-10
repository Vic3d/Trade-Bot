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
    echo "❌ Bitte als root ausführen: sudo bash $0"
    exit 1
fi

if [ ! -f "$DEPLOY_DIR/.env" ]; then
    echo "❌ deploy/.env fehlt!"
    echo "   cp $DEPLOY_DIR/.env.example $DEPLOY_DIR/.env"
    echo "   nano $DEPLOY_DIR/.env"
    exit 1
fi

echo "✅ Prüfungen bestanden"

# ─── 1. System aktualisieren ────────────────────────────────────────

echo ""
echo "📦 [1/7] System aktualisieren..."
apt update -qq && apt upgrade -y -qq
apt install -y -qq software-properties-common curl git ufw

# ─── 2. Python 3.13 installieren ────────────────────────────────────

echo ""
echo "🐍 [2/7] Python 3.13 installieren..."
add-apt-repository -y ppa:deadsnakes/ppa
apt update -qq
apt install -y -qq python3.13 python3.13-venv python3.13-dev

python3.13 --version
echo "✅ Python 3.13 installiert"

# ─── 3. Trademind User erstellen ─────────────────────────────────────

echo ""
echo "👤 [3/7] User 'trademind' erstellen..."
if ! id -u trademind &>/dev/null; then
    useradd -r -m -s /bin/bash -d /home/trademind trademind
    echo "✅ User erstellt"
else
    echo "ℹ️  User existiert bereits"
fi

# Ownership setzen
chown -R trademind:trademind "$TRADEMIND_HOME"

# ─── 4. Python venv + Dependencies ──────────────────────────────────

echo ""
echo "📚 [4/7] Python venv + Dependencies installieren..."
sudo -u trademind python3.13 -m venv "$TRADEMIND_HOME/venv"

# Torch CPU-only separat (wegen --index-url)
sudo -u trademind "$TRADEMIND_HOME/venv/bin/pip" install --quiet \
    torch --index-url https://download.pytorch.org/whl/cpu

# Rest der Dependencies
sudo -u trademind "$TRADEMIND_HOME/venv/bin/pip" install --quiet \
    numpy scipy hmmlearn river pandas yfinance \
    exchange_calendars pydantic anthropic

echo "✅ Dependencies installiert"

# ─── 5. Verzeichnisse + Symlink ──────────────────────────────────────

echo ""
echo "📁 [5/7] Verzeichnisse + Symlink..."

# Daten-Verzeichnisse
sudo -u trademind mkdir -p "$TRADEMIND_HOME/data/price_cache"
sudo -u trademind mkdir -p "$TRADEMIND_HOME/data/rl_checkpoints"
sudo -u trademind mkdir -p "$TRADEMIND_HOME/data/research"
sudo -u trademind mkdir -p "$TRADEMIND_HOME/memory"
sudo -u trademind mkdir -p "$TRADEMIND_HOME/transcripts"

# Backward-compatible Symlink (Scripts referenzieren /data/.openclaw/workspace/)
mkdir -p /data/.openclaw
ln -sfn "$TRADEMIND_HOME" /data/.openclaw/workspace
echo "✅ Symlink: /data/.openclaw/workspace → $TRADEMIND_HOME"

# OpenClaw Config für Discord (backward-compatible)
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
    echo "✅ openclaw.json erstellt"
fi

# ─── 6. systemd Services ────────────────────────────────────────────

echo ""
echo "⚙️  [6/7] systemd Services einrichten..."

cp "$DEPLOY_DIR/trademind-scheduler.service" /etc/systemd/system/
cp "$DEPLOY_DIR/trademind-api.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable trademind-scheduler
systemctl enable trademind-api

# Cron für Dashboard-Sync
chmod +x "$DEPLOY_DIR/sync-dashboard.sh"
CRON_LINE="*/30 * * * * /opt/trademind/deploy/sync-dashboard.sh >> /opt/trademind/data/sync.log 2>&1"
(crontab -u trademind -l 2>/dev/null | grep -v sync-dashboard; echo "$CRON_LINE") | crontab -u trademind -

echo "✅ Services registriert"

# ─── 7. Firewall ────────────────────────────────────────────────────

echo ""
echo "🔒 [7/7] Firewall konfigurieren..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 8765/tcp comment 'TradeMind API'
echo "y" | ufw enable
echo "✅ Firewall aktiv (SSH + Port 8765)"

# ─── Services starten ───────────────────────────────────────────────

echo ""
echo "🚀 Services starten..."
systemctl start trademind-scheduler
systemctl start trademind-api

sleep 3

# ─── Status prüfen ──────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ TradeMind Setup abgeschlossen!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Status:"
systemctl is-active trademind-scheduler && echo "  🟢 Scheduler läuft" || echo "  🔴 Scheduler Fehler!"
systemctl is-active trademind-api && echo "  🟢 API läuft" || echo "  🔴 API Fehler!"
echo ""
echo "Nützliche Befehle:"
echo "  journalctl -u trademind-scheduler -f    # Scheduler-Log live"
echo "  journalctl -u trademind-api -f          # API-Log live"
echo "  tail -f /opt/trademind/data/scheduler.log"
echo "  curl http://localhost:8765/api/portfolio # Portfolio abfragen"
echo "  systemctl restart trademind-scheduler    # Scheduler neustarten"
echo ""
echo "Dashboard-Sync: läuft alle 30 Min via Cron"
echo "  Log: /opt/trademind/data/sync.log"
echo ""
