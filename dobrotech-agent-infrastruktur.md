# DobroTech — Agent-Infrastruktur Konzept

**Version:** 1.0  
**Erstellt:** 25.02.2026 (Nachtsession Vincent + Albert)  
**Status:** Konzeptphase — zur Review

---

## 🎯 Ziel

DobroTech als Firma mit einem Team aus 8 KI-Agents betreiben — DSGVO/GoBD-konform, sicher und kosteneffizient. Kein Werkstudent (~€1.200/Monat), stattdessen ~€350/Monat für das gesamte Team.

---

## 🤖 Die 8 Agents

### 1. 🎩 Albert — Victors Assistent
- **Modell:** Sonnet (default), Opus (komplex)
- **Aufgaben:** Coding, Server, Projekte — Victors rechte Hand
- **Kosten:** ~€40–80/Monat

### 2. 🤖 Schmobro — Vincents Assistent
- **Modell:** Sonnet (default), Opus bei Bedarf
- **Aufgaben:** Strategie, Recherche, Texte — Vincents rechte Hand
- **Kosten:** ~€40–80/Monat

### 3. 👔 COO-Agent „Chief"
- **Modell:** Sonnet (default), Opus (Entscheidungen)
- **Aufgaben:** Orchestrierung, Task-Delegation, Reporting, Qualitäts-Gate
- **Kosten:** ~€30–60/Monat

### 4. 🔧 Dev-Agent
- **Modell:** Kimi K2.5 (Standard), Opus (Architektur), Ollama qwen2.5-coder (Drafts)
- **Aufgaben:** Code schreiben, Tests, PRs, Deployments vorbereiten
- **Workflow:** Branch → Implement → Test → PR → COO Review → Merge
- **Kosten:** ~€30–60/Monat + €0 Ollama

### 5. 🔍 Scout — Research & Business Dev
- **Modell:** Kimi K2.5 (Research), Haiku (Scans)
- **Aufgaben:** Marktbeobachtung, Geschäftschancen finden, Konkurrenz-Monitoring
- **Tägliche Scans:** HN, Product Hunt, Reddit, EU-Regulierungen
- **Output:** Wöchentlicher Market Report
- **Kosten:** ~€15–30/Monat + €5 Brave Search

### 6. 🚨 Ops-Agent
- **Modell:** Haiku (günstig, läuft oft)
- **Aufgaben:** Server-Monitoring, Security, Backups, Alerts
- **Health-Checks:** alle 30 Min; Backup-Verify täglich
- **Alerts:** → Discord #security
- **Kosten:** ~€5–10/Monat

### 7. 📝 Content-Agent
- **Modell:** Haiku (Drafts), Sonnet (finale Texte)
- **Aufgaben:** Blog-Posts, Docs, Marketing, E-Mail-Templates, Social Media
- **Kosten:** ~€10–20/Monat

### 8. 💼 Büro-Agent — ⚠️ 100% LOKAL (DSGVO!)
- **Modell:** NUR Ollama (qwen2.5:14b, llama3.1:8b) — kein Cloud-LLM!
- **Aufgaben:** Buchhaltung, Rechnungen, Verträge, USt-Vorbereitung
- **Netzwerk:** Isoliert — kein Internet, kein Cloud-Zugriff
- **Anbindung:** IMAP (rechnungen@dobro.tech), lexoffice API
- **Archiv:** GoBD-konformes Write-Once Archiv
- **Kosten:** €0 API + €25 lexoffice

---

## 💰 Modell-Strategie (5 Tiers)

| Tier | Modell | Einsatz | Preis/1M Tokens |
|------|--------|---------|-----------------|
| 1 — Lokal | Ollama qwen2.5-coder, llama3.1 | Büro, Dev-Drafts | €0 |
| 2 — Budget | Haiku 3.5 | Ops, Heartbeats, Content-Drafts | $0.25–1.25 |
| 3 — Mid | Kimi K2.5 | Dev Standard, Scout | $0.60–2.00 |
| 4 — Standard | Sonnet 4.6 | Albert, Schmobro, COO, Content final | $3–15 |
| 5 — Premium | Opus 4.6 | Architektur, kritische Reviews | $15–75 |

---

## 📡 Kommunikation zwischen Agents

Datei-basierter Message-Bus — **30–100x günstiger** als Chat-basierte Kommunikation.

```
/shared/tasks/           → strukturierte JSON-Tasks
/shared/inbox/{agent}/   → pro Agent eine Inbox
/shared/knowledge/       → geteiltes Wissen
/shared/status/agents.json → wer ist online
```

---

## 🖥️ Server: Hetzner AX102

| Spec | Wert |
|------|------|
| CPU | AMD Ryzen 9 7950X (16c/32t) |
| RAM | 128 GB DDR5 |
| Storage | 2× 2TB NVMe (RAID 1) |
| Preis | €76/Monat |

Geschätzter RAM-Bedarf: ~32 GB → ~96 GB Puffer für Ollama-Modelle.

---

## 🔒 Sicherheit

- SSH Key-Only + Fail2Ban + Custom Port
- UFW: nur Port 443 + SSH
- Caddy + TLS 1.3 + CrowdSec WAF
- Docker: `read_only`, `cap_drop ALL`, isolierte Netzwerke
- LUKS Disk-Encryption
- Secrets in Docker Secrets
- **3 Docker-Netzwerke:** `external`, `agent-internal`, `backoffice-only`

---

## ⚖️ Compliance

- **DSGVO:** Verarbeitungsverzeichnis, AVVs, Löschkonzept, DSFA, TOMs
- **GoBD:** Write-Once Archiv, 10 Jahre Aufbewahrung, Verfahrensdoku
- **EU AI Act:** Transparenz, menschliche Aufsicht, Logging
- **Steuerlich:** USt-Voranmeldung, Pflichtangaben auf Rechnungen

---

## 📧 E-Mail-Architektur

| Adresse | Empfänger |
|---------|-----------|
| info@dobro.tech | COO-Agent |
| rechnungen@dobro.tech | Büro-Agent (isoliert) |
| buchhaltung@dobro.tech | Büro-Agent (Ausgang) |
| support@axessify.de | COO/Support |
| datenschutz@dobro.tech | COO |
| vincent@dobro.tech | Schmobro |
| victor@dobro.tech | Albert |

---

## 💶 Kosten-Übersicht

| Szenario | Monatlich |
|----------|-----------|
| Sparsam | ~€283 |
| Normal | ~€363 |
| Heavy | ~€453 |
| **Durchschnitt** | **~€350** |

**Zum Vergleich:** 1 Werkstudent = ~€1.200/Monat

---

## 🗓️ Aufbau-Reihenfolge (4 Wochen)

**Woche 1:** Server aufsetzen + Hardening + Docker + Albert & Schmobro migrieren + Backup-System  
**Woche 2:** COO + Ops + Ollama installieren + `/shared/`-Struktur + Discord-Channels  
**Woche 3:** Dev-Agent + Scout + Content + Inter-Agent-Kommunikation testen  
**Woche 4:** Büro-Agent + lexoffice + IMAP + DSGVO-Docs + GoBD-Archiv  

---

## ❓ Offene Entscheidungen

- [ ] Rechtsform DobroTech (UG empfohlen wg. Haftung)
- [ ] Domain `dobro.tech` registrieren?
- [ ] OpenRouter vs. direkte API-Keys?
- [ ] GPU-Server für Ollama oder CPU-only?
- [ ] Banking-Anbindung: CSV-Import oder FinTS/PSD2 API?
