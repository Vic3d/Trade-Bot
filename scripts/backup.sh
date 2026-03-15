#!/bin/bash
cd /data/.openclaw/workspace

# Git Backup
git add -A
if git diff --cached --quiet; then
    echo "BACKUP: Keine Änderungen"
    exit 0
fi

# Delta für Commit-Message
CHANGED=$(git diff --cached --stat | tail -1)
SNAPSHOT_AGE="unknown"
if [ -f memory/state-snapshot.md ]; then
    SNAPSHOT_AGE=$(head -2 memory/state-snapshot.md | grep -o '20[0-9]\{2\}-[0-9-]* [0-9:]*' | head -1)
fi

git commit -m "Backup $(date '+%Y-%m-%d %H:%M') — ${CHANGED} — Snapshot: ${SNAPSHOT_AGE}"

# Push (mit Fehler-Erkennung)
GIT_SSH_COMMAND="ssh -i /data/.ssh/id_ed25519_vic3d -o StrictHostKeyChecking=no" git push origin HEAD 2>&1
PUSH_EXIT=$?

if [ $PUSH_EXIT -ne 0 ]; then
    echo "BACKUP_ERROR: Git push fehlgeschlagen (exit $PUSH_EXIT)"
    exit 1
else
    echo "BACKUP_OK: Gepusht — ${CHANGED}"
    exit 0
fi
