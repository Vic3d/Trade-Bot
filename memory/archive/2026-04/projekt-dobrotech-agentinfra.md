# DobroTech Agent-Infrastruktur — Konzept

**Erstellt:** 2026-02-25, 03:00 Uhr
**Initiator:** Vincent
**Status:** Konzeptphase, noch nicht umgesetzt

---

## Zusammenfassung

Vincent und ich (Albert) haben in einer Nachtsession das komplette Agent-Infrastruktur-Konzept für DobroTech erarbeitet. Ziel: Eine Firma die mit einem Team aus 8 KI-Agents operiert, DSGVO/GoBD-konform, sicher, kosteneffizient.

## Beteiligte informieren
- [ ] Schmobro: Vincent will ihn am 25.02. darüber in Kenntnis setzen
- [ ] Victor: Sobald er aufgestanden ist, über die Thematik informieren

---

## 8 Agents

### 1. 🎩 Albert (Victors Assistent)
- Modell: Sonnet (default), Opus (komplex)
- Rolle: Coding, Server, Projekte, Victors rechte Hand
- Kosten: ~€40-80/Monat

### 2. 🤖 Schmobro (Vincents Assistent)
- Modell: Sonnet (default), Opus bei Bedarf
- Rolle: Strategie, Recherche, Texte, Vincents rechte Hand
- Kosten: ~€40-80/Monat

### 3. 👔 COO-Agent "Chief"
- Modell: Sonnet (default), Opus (Entscheidungen)
- Rolle: Orchestrierung, Task-Delegation, Reporting, Qualitäts-Gate
- Kosten: ~€30-60/Monat

### 4. 🔧 Dev-Agent
- Modell: Kimi K2.5 (Standard), Opus (Architektur), Ollama qwen2.5-coder (Drafts)
- Rolle: Code schreiben, Tests, PRs, Deployments vorbereiten
- Workflow: Branch → Implement → Test → PR → COO Review → Merge
- Kosten: ~€30-60/Monat + €0 Ollama

### 5. 🔍 Scout (Research & Business Dev)
- Modell: Kimi K2.5 (Research), Haiku (Scans)
- Rolle: Marktbeobachtung, Geschäftschancen finden, Konkurrenz-Monitoring
- Bewertungs-Framework: Umsetzbarkeit, Markt, Wettbewerb, Regulierung, Recurring Revenue
- Tägliche Scans: HN, Product Hunt, Reddit, EU-Regulierungen
- Wöchentlicher Market Report
- Kosten: ~€15-30/Monat + €5 Brave Search

### 6. 🚨 Ops-Agent
- Modell: Haiku (günstig, läuft oft)
- Rolle: Server-Monitoring, Security, Backups, Alerts
- Health-Checks alle 30 Min, Backup-Verify täglich
- Alerts → Discord #security
- Kosten: ~€5-10/Monat

### 7. 📝 Content-Agent
- Modell: Haiku (Drafts), Sonnet (finale Texte)
- Rolle: Blog-Posts, Docs, Marketing, E-Mail-Templates, Social Media
- Kosten: ~€10-20/Monat

### 8. 💼 Büro-Agent (100% LOKAL — DSGVO!)
- Modell: NUR Ollama (qwen2.5:14b, llama3.1:8b)
- Rolle: Buchhaltung, Rechnungen, Verträge, USt-Vorbereitung
- Netzwerk: ISOLIERT — kein Internet, kein Cloud-LLM
- Anbindung: IMAP (rechnungen@dobro.tech), lexoffice API
- GoBD-konformes Write-Once Archiv
- Kosten: €0 API + €25 lexoffice

---

## Modell-Strategie (5 Tiers)

1. **Lokal (€0):** Ollama qwen2.5-coder:14b, llama3.1:8b → Büro, Dev-Drafts
2. **Budget ($0.25-1.25/1M):** Haiku 3.5 → Ops, Heartbeats, Content-Drafts
3. **Mid ($0.60-2.00/1M):** Kimi K2.5 → Dev Standard, Scout
4. **Standard ($3-15/1M):** Sonnet 4.6 → Albert, Schmobro, COO, Content final
5. **Premium ($15-75/1M):** Opus 4.6 → Architektur, kritische Reviews

---

## Kommunikation: Datei-basierter Message-Bus

- /shared/tasks/ — strukturierte JSON-Tasks
- /shared/inbox/{agent}/ — pro Agent eine Inbox
- /shared/knowledge/ — geteiltes Wissen
- /shared/status/agents.json — wer ist online

Faktor 30-100x günstiger als Chat-basierte Kommunikation.

---

## Server: Hetzner AX102

- AMD Ryzen 9 7950X (16c/32t)
- 128 GB DDR5 RAM
- 2x 2TB NVMe (RAID 1)
- €76/Monat
- RAM-Bedarf geschätzt: ~32 GB, ~96 GB Puffer

---

## Sicherheit

- SSH Key-Only + Fail2Ban + Custom Port
- UFW: nur 443 + SSH
- Caddy + TLS 1.3 + CrowdSec WAF
- Docker: read_only, cap_drop ALL, isolierte Netzwerke
- LUKS Disk-Encryption
- Secrets in Docker Secrets
- 3 Docker-Netzwerke: external, agent-internal, backoffice-only

---

## Compliance

- DSGVO: Verarbeitungsverzeichnis, AVVs, Löschkonzept, DSFA, TOMs
- GoBD: Write-Once Archiv, 10 Jahre Aufbewahrung, Verfahrensdoku
- EU AI Act: Transparenz, menschliche Aufsicht, Logging
- Steuerlich: USt-Voranmeldung, Pflichtangaben Rechnungen

---

## E-Mail-Architektur

- info@dobro.tech → COO
- rechnungen@dobro.tech → Büro-Agent (isoliert)
- buchhaltung@dobro.tech → Büro-Agent (Ausgang)
- support@axessify.de → COO/Support
- datenschutz@dobro.tech → COO
- vincent@dobro.tech → Schmobro
- victor@dobro.tech → Albert

---

## Kosten

| Szenario | Monatlich |
|---|---|
| Sparsam | ~€283 |
| Normal | ~€363 |
| Heavy | ~€453 |
| **Durchschnitt** | **~€350** |

Zum Vergleich: 1 Werkstudent = ~€1.200/Monat

---

## Aufbau-Reihenfolge (4 Wochen)

1. **Woche 1:** Server + Hardening + Docker + Albert/Schmobro migrieren + Backup
2. **Woche 2:** COO + Ops + Ollama + /shared/ + Discord-Channels
3. **Woche 3:** Dev-Agent + Scout + Content + Inter-Agent-Komm testen
4. **Woche 4:** Büro-Agent + lexoffice + IMAP + DSGVO-Docs + GoBD-Archiv

---

## Offene Entscheidungen

- [ ] Rechtsform DobroTech (UG empfohlen wg. Haftung)
- [ ] Domain dobro.tech registrieren?
- [ ] OpenRouter vs. direkte API-Keys?
- [ ] GPU-Server für Ollama oder CPU-only?
- [ ] Banking-Anbindung: CSV-Import oder FinTS/PSD2 API?
