#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# TradeMind Deploy — alle Änderungen auf den Server
# ═══════════════════════════════════════════════════════════════════
# Verwendung:
#   bash deploy/deploy.sh                  # normales Deploy
#   bash deploy/deploy.sh --no-restart     # ohne Scheduler-Neustart
#   bash deploy/deploy.sh --dry-run        # nur anzeigen was passiert

set -euo pipefail

VPS="root@178.104.152.135"
REMOTE_DIR="/opt/trademind"
DRY_RUN=false
NO_RESTART=false

for arg in "$@"; do
    case $arg in
        --dry-run)   DRY_RUN=true ;;
        --no-restart) NO_RESTART=true ;;
    esac
done

echo "═══════════════════════════════════════════════════"
echo "  TradeMind Deploy"
echo "═══════════════════════════════════════════════════"

# ─── 0. Pre-Deploy Compile-Hook (Sub-8 V3 #5) ──────────────────────
# Verhindert Deploy von Syntax-kaputten Python-Dateien. SyntaxError
# auf VPS killt Scheduler-Job stumm; lokaler py_compile bricht hier ab.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "[0/4] Pre-Deploy Compile-Check..."
if [ "$DRY_RUN" = false ]; then
    COMPILE_FAIL=0
    while IFS= read -r -d '' f; do
        if ! python -m py_compile "$f" 2>/tmp/compile_err.$$; then
            echo "  ❌ SyntaxError: $f"
            cat /tmp/compile_err.$$
            COMPILE_FAIL=1
        fi
    done < <(find "$REPO_ROOT/scripts" -name '*.py' -not -path '*/_archive/*' -print0)
    rm -f /tmp/compile_err.$$
    if [ "$COMPILE_FAIL" -ne 0 ]; then
        echo "  Deploy ABGEBROCHEN — SyntaxError(s) oben fixen."
        exit 1
    fi
    echo "  Compile OK"
else
    echo "  [DRY-RUN] würde compile-checken"
fi

# ─── 1. Lokale Änderungen commiten (falls nötig) ────────────────────

UNCOMMITTED=$(git -C "$(dirname "$0")/.." status --porcelain -- scripts/ data/strategies.json 2>/dev/null | { grep -v '^??' || true; } | wc -l)
if [ "$UNCOMMITTED" -gt 0 ]; then
    echo "[1/4] Uncommitted Änderungen gefunden — commite automatisch..."
    if [ "$DRY_RUN" = false ]; then
        git -C "$(dirname "$0")/.." add scripts/ data/strategies.json
        git -C "$(dirname "$0")/.." commit -m "deploy: auto-commit $(date '+%Y-%m-%d %H:%M')" || true
    else
        echo "  [DRY-RUN] würde commiten"
    fi
else
    echo "[1/4] Alles committed — OK"
fi

# ─── 2. Auf GitHub pushen ───────────────────────────────────────────

echo "[2/4] Push zu GitHub..."
if [ "$DRY_RUN" = false ]; then
    git -C "$(dirname "$0")/.." push origin master 2>&1 || {
        echo "  Push fehlgeschlagen — versuche aktuellen Branch..."
        BRANCH=$(git -C "$(dirname "$0")/.." branch --show-current)
        git -C "$(dirname "$0")/.." push origin "$BRANCH" 2>&1
    }
else
    echo "  [DRY-RUN] würde pushen"
fi

# ─── 3. Server: Pull + Merge ────────────────────────────────────────

echo "[3/4] Server aktualisieren..."
if [ "$DRY_RUN" = false ]; then
    ssh -o StrictHostKeyChecking=no "$VPS" bash << 'REMOTE'
set -e
cd /opt/trademind

# Lokale Daten-Änderungen sichern (Bot-State)
git stash push --quiet -m "deploy-autostash-$(date +%Y%m%d-%H%M)" -- \
    data/trading.db data/strategies.json data/vix_history.json \
    data/ceo_directive.json data/trading_learnings.json data/strategy_dna.json \
    memory/ 2>/dev/null || true

# Neueste Version holen
git fetch origin --quiet
git merge origin/master --no-edit -X theirs 2>&1 | grep -v "^Already" || true

# Bot-State wiederherstellen (Daten überschreiben frische Defaults)
git checkout stash@{0} -- \
    data/trading.db data/vix_history.json data/ceo_directive.json \
    data/trading_learnings.json data/strategy_dna.json memory/ 2>/dev/null || true

# strategies.json: neue Thesen aus master hinzufügen, Live-State behalten
python3 - << 'PYEOF'
import json, os
stash_file = None
# Finde neueste stash strategies.json
import subprocess
r = subprocess.run(['git', 'show', 'stash@{0}:data/strategies.json'],
                  capture_output=True, text=True)
if r.returncode == 0:
    live = json.loads(r.stdout)
    with open('data/strategies.json') as f:
        new = json.load(f)
    # Füge neue Keys hinzu die im live nicht existieren
    added = []
    for k, v in new.items():
        if k not in live:
            live[k] = v
            added.append(k)
    with open('data/strategies.json', 'w') as f:
        json.dump(live, f, indent=2, ensure_ascii=False)
    if added:
        print(f"  Neue Strategien hinzugefügt: {added}")
    else:
        print("  Strategien: keine neuen")
else:
    print("  Strategien: kein Stash gefunden, nutze master-Version")
PYEOF

# Permissions sicherstellen
chown -R trademind:trademind /opt/trademind/data/ /opt/trademind/memory/ 2>/dev/null || true

echo "Server-Update OK"
REMOTE
else
    echo "  [DRY-RUN] würde Server aktualisieren"
fi

# ─── 4. Scheduler neu starten ───────────────────────────────────────

if [ "$NO_RESTART" = false ]; then
    echo "[4/4] Scheduler neu starten..."
    if [ "$DRY_RUN" = false ]; then
        ssh -o StrictHostKeyChecking=no "$VPS" "systemctl restart trademind-scheduler && sleep 3 && systemctl is-active trademind-scheduler"
    else
        echo "  [DRY-RUN] würde Scheduler neu starten"
    fi
else
    echo "[4/4] Scheduler-Neustart übersprungen (--no-restart)"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Deploy abgeschlossen"
echo "═══════════════════════════════════════════════════"
