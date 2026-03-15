# RESTORE.md — Albert Wiederherstellung

Dieses Dokument erklärt wie ein frischer Albert aus dem GitHub-Backup vollständig wiederhergestellt wird.

## Für Victor: So gibst du mir Zugriff

1. Geh zu: https://github.com/Vic3d/Trade-Bot/settings/keys
2. Füge Alberts SSH Public Key hinzu (steht in TOOLS.md)
3. Sage mir: "Albert, restore from GitHub"

## Für Albert: Wiederherstellungs-Prozedur

### Schritt 1 — SSH-Key generieren + bei GitHub hinterlegen

```bash
# Neuen Key generieren
ssh-keygen -t ed25519 -C "albert-vic3d@openclaw" -f ~/.ssh/id_ed25519_vic3d -N ""

# Public Key ausgeben → bei GitHub hinterlegen:
# https://github.com/settings/ssh/new (Account: Vic3d)
cat ~/.ssh/id_ed25519_vic3d.pub

# SSH-Config eintragen
cat >> ~/.ssh/config << 'EOF'
Host github-vic3d
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_vic3d
EOF

# Verbindung testen
ssh -T git@github-vic3d
# Erwartet: "Hi Vic3d! You've successfully authenticated..."
```

### Schritt 2 — Repo klonen

```bash
git clone git@github-vic3d:Vic3d/Trade-Bot.git /data/.openclaw/workspace
```

### Schritt 2b — Separate Repos klonen

```bash
# LearnFlow (Lernplattform) — eigenes Repo
git clone git@github-vic3d:Vic3d/Lern-Bot.git /data/.openclaw/workspace/lernbot/
```

### Secrets-Checkliste (Victor muss bereitstellen)

Nach dem Klonen fehlen diese Dateien (bewusst nicht in Git):

- [ ] `secrets/josh-credentials.env` — B&O Portal + Hero Software Login (von Victor)
- [ ] `.env` mit:
  - `ANTHROPIC_API_KEY` — für LearnFlow KI-Features (Anthropic Console)
  - `POLYGON_KEY` — für NewsWire Analyst (polygon.io)
  - `FINNHUB_KEY` — für NewsWire Analyst (finnhub.io)
  - `OPENAI_API_KEY` — optional, für Premium TTS in LearnFlow
- [ ] SSH-Keys:
  - `/data/.ssh/id_ed25519_vic3d` — GitHub Zugang (Vic3d Account)
  - `/home/node/openclaw/.ssh-keys/id_ed25519` — GitHub dobro-de + Hetzner
  - `/home/node/openclaw/.ssh-keys/id_ed25519_bbde` — GitHub bb-de (Josh Dashboard)
- [ ] `memory/email-accounts.md` — OWA Zugangsdaten (manuell wiederherstellen)

### Schritt 2 — Pflichtlektüre (in dieser Reihenfolge)

1. `SOUL.md` — wer ich bin
2. `USER.md` — wen ich helfe (Victor Dobrowolny)
3. `AGENTS.md` — Regeln für jede Session
4. `MEMORY.md` — destilliertes Langzeitwissen
5. `memory/state-snapshot.md` — letzter Stand: Positionen, Todos, VIX
6. `memory/YYYY-MM-DD.md` (heute + gestern) — was zuletzt passiert ist

### Schritt 3 — Trading-Kontext laden

7. `memory/strategien.md` — aktive Trade-Thesen + Status
8. `memory/projekt-trading.md` — aktives Portfolio, Entries, Stops
9. `memory/trade-decisions.md` — Entscheidungslog mit Begründungen
10. `memory/albert-accuracy.md` — wie gut meine Empfehlungen waren
11. `memory/tradingtool-lernplan.md` — wo wir im Lernplan stehen

### Schritt 4 — Infrastruktur prüfen

```bash
# Cron-Jobs prüfen (sind NICHT im Repo — müssen neu eingerichtet werden!)
# Victor fragen: "Welche Crons soll ich reaktivieren?"
```

⚠️ **Wichtig:** Cron-Jobs leben im OpenClaw-System, nicht im Git-Repo.
Nach einem vollständigen Reset müssen diese neu eingerichtet werden.
Die Konfiguration dafür steht in `memory/state-snapshot.md`.

### Schritt 4b — Cron-Jobs wiederherstellen

Cron-Jobs leben im OpenClaw-System, nicht im Git. Nach Reset:
1. Öffne `memory/cron-export.json`
2. Für jeden Job: `cron(action=add, job={...})` im Chat aufrufen
3. Oder sage: "Albert, stelle alle Crons aus cron-export.json wieder her"

Verifiziere: `cron(action=list)` — sollte ~21 Jobs zeigen.

### Schritt 5 — Bestätigung

Nach dem Lesen kurz zusammenfassen:
- Aktuelle Portfoliopositionen
- Offene Todos
- Letzte wichtige Entscheidung

Victor bestätigt ob alles stimmt → Normal weiterarbeiten.

---

## Was ist im Backup enthalten

| Inhalt | Gesichert | Pfad |
|--------|-----------|------|
| Langzeitgedächtnis | ✅ | MEMORY.md |
| Tagesnotizen | ✅ | memory/YYYY-MM-DD.md |
| Projektfiles | ✅ | memory/projekt-*.md |
| Trading-Strategien | ✅ | memory/strategien.md |
| Entscheidungslog | ✅ | memory/trade-decisions.md |
| Lernfortschritt | ✅ | memory/tradingtool-lernplan.md |
| Genauigkeitstracking | ✅ | memory/albert-accuracy.md |
| Scripts/Module | ✅ | scripts/, modules/ |
| Persönlichkeit | ✅ | SOUL.md, IDENTITY.md |
| Credentials/Secrets | ❌ | secrets/ (bewusst ausgeschlossen!) |
| Cron-Jobs | ❌ | Im OpenClaw-System (neu einrichten) |

## Was NICHT im Backup ist (und warum)

- **secrets/** — Passwörter, API-Keys → niemals in Git!
- **Cron-Jobs** — leben im OpenClaw-Daemon, nicht im Filesystem
- **`.env` Dateien** — API-Keys

Diese müssen nach einem Reset von Victor neu bereitgestellt werden.

---

*Backup-Repo: https://github.com/Vic3d/Trade-Bot*
*Auto-Backup: täglich 23:00 Uhr Berlin*
*Letztes manuelles Backup: 2026-03-14*
