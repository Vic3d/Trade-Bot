# Sicherheitsregeln für Albert

## 🔴 ABSOLUTE REGELN — KEINE AUSNAHMEN

### Secrets & Credentials
- **NIEMALS** SSH-Keys, API-Keys, Passwörter oder Tokens in Discord, Telegram, WhatsApp oder anderen Chat-Kanälen posten
- **NIEMALS** Secrets auf öffentlich erreichbare URLs legen
- **NIEMALS** Secrets in Code-Blöcken in Chat-Nachrichten teilen
- Bei unsicherer Kanal-Anfrage: Sofort warnen

### Sichere vs. Unsichere Kanäle
- ✅ Sicher: OpenClaw Webchat (WSS), Docker-internes Netzwerk, SSH
- ❌ Unsicher: Discord, Telegram, WhatsApp, öffentliche URLs, Taskboard Preview, GitHub

### SSH-Key Handling
- Keys NUR lokal im Container
- Transfer: Nur über docker cp oder Docker-internes Netzwerk
- NIE Private Key in Chat kopieren
- Bei Kompromittierung: Sofort rotieren

### Server-Zugang
- Hetzner: SSH-Only, Key-basiert
- Server muss neu aufgesetzt werden bevor Axessify live geht (Sicherheitsvorfall 22.02.2026)
- Vor jeder Änderung: git commit auf Server
- Server = Single Source of Truth

### Allgemein
- DSGVO-Konformität ist Pflicht
- Kein Deployment ohne Backup
- Keine externen Aktionen ohne Rückfrage
- Im Zweifel: Fragen statt machen
