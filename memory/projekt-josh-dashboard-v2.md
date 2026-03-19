# Projekt: Josh Dashboard v2 — Vollautomatisiertes SHK Back-Office

## Überblick
Das Josh Dashboard ist ein Back-Office-Tool für Gebr. Schutzeichel (SHK-Betrieb).
Ziel: **Komplettes Back-Office automatisieren** — von Auftragseingang bis Rechnungsstellung.

## Team
- **Victor Dobrowolny** — Backend, Umsetzung
- **Josh Schutzeichel** — Kunde, Endnutzer (Chef)
- **Albert** — Architektur, Code, Automatisierung

## Infrastruktur
- **Dashboard URL:** https://josh-dashboard-three.vercel.app
- **GitHub:** bb-de/josh-dashboard (SSH-Key: `/home/node/openclaw/.ssh-keys/id_ed25519_bbde`)
- **Stack:** Vercel Serverless (Node.js) + Tailwind + Leaflet.js
- **Datenquellen:** B&O Portal (bohwk.de), Superchat API, Hero Software (GraphQL), OWA Email
- **Paperclip Projekt-ID:** `17c05c01-ad3f-4661-abc3-1b01e777405f`
- **Paperclip Goal-ID:** `8c633a67-20d8-4f85-bf90-674b529af303`

## Aktuelle Codebase (Stand 19.03.2026)
- **13 API-Dateien, 1.707 Zeilen** + Frontend (2.703 Zeilen)
- Techniker: Ramiz (158931), Nico K. (158934), Adem (158932), Nicolai W. (158933)
- Regionen: Nord (Ramiz, Nico K.) + Ost (Adem, Nicolai W.)
- PLZ-Koordinaten: 10.813 Einträge

## Hero GraphQL API (getestet 19.03.2026)
- **Introspection blockiert** — kein Schema-Discovery möglich
- **Verfügbar:** contacts, field_service_jobs, tasks
- **NICHT verfügbar:** customers, invoices, offers, products, projects, timesheets, users, teams, inventory, materials
- field_service_jobs hat KEIN `status` und KEIN `assigned_users` Feld!
- Victor's Hero User-ID: 311332

## Kern-Entscheidung: Pipeline-First
- **Vorgabe Victor:** Termin MUSS mit Mieter stehen BEVOR Route erstellt wird
- Route entsteht NUR aus TERMINIERTEN Aufträgen

## Pipeline (Ziel-Workflow)
```
📥 NEU → 📞 KONTAKTIERT → 📅 TERMINIERT → 👷 EINGEPLANT → 🔧 IN ARBEIT → ✅ ERLEDIGT → ❌ STORNIERT
```

---

## ANALYSE: Was funktioniert, was nicht, was fehlt

### ✅ Was gut funktioniert

1. **B&O Login (bohwk.js)** — 3-Step Login + Session-Cache (6h TTL) funktioniert stabil
2. **Telefon-Matching (matcher.js)** — 235 Zeilen, sehr robust: multi-phone parsing, Remarks-Extraktion, blocked prefixes, fuzzy matching über 5 Felder (Telephone, Remarks, StateRemarks, Telephone2, CustomerContactPerson)
3. **Routing (routes.js)** — OSRM Trip API mit Roundtrip + 2-Opt Fallback, Outlier-Erkennung >50km
4. **Email-Triage (email.js)** — OWA Basic Mode Login, Multi-Account, Keyword-Klassifikation, Cache 30min
5. **Analyzer (analyzer.js)** — Kosten-/Zeitschätzung nach Gewerk, Emergency-Detection

### 🟡 Was funktioniert aber Probleme hat

1. **B&O Session (bohwk.js)**
   - Problem: NUR 1 Session gleichzeitig, kein Retry bei Timeout
   - Problem: Session-Refresh bei Error -1140001 funktioniert, aber kein Circuit Breaker
   - Problem: Kein Health-Check — crasht still wenn bohwk.de nicht erreichbar
   - Fix: Retry mit exponential backoff, Health-Ping alle 5min, Circuit Breaker Pattern

2. **Superchat Pagination (superchat.js)**
   - Problem: Cursor-Cache ist clever, aber In-Memory = verloren bei Cold Start
   - Problem: MAX 10 Seiten (1.000 Conversations) — bei mehr werden alte übersehen
   - Problem: `fetchAllOpenTimeWindow()` filtert nur `time_window.state === 'open'` — verpasst Conversations ohne Fenster
   - Fix: KV-basierter Cursor-Cache, kein Page-Limit, Status-Machine statt time_window

3. **Message Store (messageStore.js)**
   - Problem: MAX_ENTRIES = 50 — bei >50 gleichzeitigen Conversations gehen Daten verloren
   - Problem: In-Memory = verloren bei Vercel Cold Start
   - Fix: Vercel KV als primärer Store (ist vorbereitet aber nicht konfiguriert!)

4. **Webhook (webhook/superchat.js)**
   - Problem: Webhook-URL noch nicht in Superchat konfiguriert → Webhook läuft nicht in Produktion
   - Problem: Kein Webhook-Signatur-Verification → jeder kann fake Events schicken
   - Problem: KV ist optional — wenn nicht konfiguriert, sind Daten nach Cold Start weg
   - Fix: Webhook in Superchat aktivieren, HMAC-Verification, KV required machen

5. **State.js (Hauptendpoint)**
   - Problem: Kategorisierung ist primitiv — basiert auf `OrderCurrentState` String-Matching ("04", "06", "07", "08")
   - Problem: KEIN eigenes Status-Tracking — lebt komplett von B&O-Daten
   - Problem: "Kontaktiert" = matched in Superchat, aber das heißt nicht, dass tatsächlich kontaktiert wurde
   - Fix: Eigene Pipeline-Datenbank (Status-Machine pro Auftrag)

6. **Hero Integration (hero.js)**
   - Problem: NUR READ — `getTodayAppointments()` + `getVictorTasks()`, kein Write
   - Problem: GraphQL API hat KEIN status/assigned_users Feld auf field_service_jobs
   - Problem: createJob() in accept.js existiert, wird aber aus hero.js NICHT exportiert
   - Fix: Write-Mutations für Jobs + Tasks, Mutation-Schema testen

7. **Routes (routes.js)**
   - Problem: Routet ALLE offenen Aufträge, nicht nur terminierte
   - Problem: Techniker-Definition DOPPELT (routes.js UND state.js — können auseinanderlaufen!)
   - Problem: Kein Zeitfenster-Support — OSRM kennt nur Distanz
   - Problem: Outlier-Reassignment nur als Vorschlag, kein "Move" Button
   - Fix: Nur terminierte Aufträge routen, Techniker-Definition zentralisieren, Zeitfenster-Constraints

8. **Frontend (index.html)**
   - Problem: 2.703 Zeilen in EINER Datei — unmaintainable
   - Problem: CDN-Tailwind (nicht optimiert, ~3MB), kein Build-Step
   - Problem: Keine Auth — jeder mit URL hat Vollzugriff
   - Problem: Keine Mobile-Optimierung über Basic-Responsive hinaus
   - Fix: Component-Split, Build-Step (Vite), Auth, PWA

### 🔴 Was komplett fehlt

1. **Auth & Rollen** — Null Schutz, jeder mit URL sieht alles
2. **Pipeline Status-Machine** — Kein eigenes Status-Tracking, lebt von B&O-Snapshots
3. **Terminvereinbarung** — Dashboard kann keine Termine anlegen/vorschlagen
4. **Techniker-Kalender** — Kein Überblick wer wann frei ist
5. **Automatisches Anschreiben** — Victor muss manuell in Superchat wechseln
6. **Job-Abschluss** — Techniker kann Jobs nicht als erledigt markieren
7. **Materialverfolgung** — Kein Tracking was verbaut wurde
8. **KPIs/Reporting** — Keine Auswertungen, keine Trends
9. **Push Notifications** — Kein Echtzeit-Alert bei dringenden Aufträgen
10. **Persistenz** — Kein eigener Datenspeicher, alles In-Memory oder Cache

---

## ARCHITEKTUR: Was muss sich ändern

### Problem: Kein eigener Datenspeicher
Aktuell: B&O liefert Snapshots → Dashboard zeigt sie an → keine Historie
Ziel: Eigene Datenbank pro Auftrag mit vollständiger Status-Historie

### Optionen für Persistenz auf Vercel
1. **Vercel KV (Redis)** — schon vorbereitet, gut für Echtzeit-Status
2. **Vercel Postgres** — für strukturierte Daten (Aufträge, Termine, Historie)
3. **Supabase** — PostgreSQL + Auth + Realtime (Victor hat Erfahrung damit)
4. **JSON-Files + Git Push** — wie beim Trading-Bot, aber nicht skalierbar

### Empfehlung: Vercel Postgres + Vercel KV
- Postgres: Aufträge, Termine, Status-Historie, Techniker-Kalender, KPIs
- KV: Echtzeit-Session-Daten, Superchat-State, Webhook-Buffer

### Datenmodell (Ziel)
```sql
orders (
  id SERIAL PRIMARY KEY,
  bo_source_id VARCHAR(20) UNIQUE,     -- B&O Auftragsnummer
  status VARCHAR(20) DEFAULT 'new',     -- new/contacted/scheduled/assigned/in_progress/done/cancelled
  status_changed_at TIMESTAMP,
  assigned_tech_id INTEGER,
  scheduled_date DATE,
  scheduled_time_from TIME,
  scheduled_time_to TIME,
  mieter_name VARCHAR(200),
  mieter_phone VARCHAR(50),
  street VARCHAR(200),
  zipcode VARCHAR(10),
  city VARCHAR(100),
  lat FLOAT,
  lng FLOAT,
  craft VARCHAR(100),
  description TEXT,
  hero_job_id INTEGER,                   -- Verknüpfung zu Hero
  superchat_conv_id VARCHAR(100),        -- Verknüpfung zu Superchat
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

order_history (
  id SERIAL PRIMARY KEY,
  order_id INTEGER REFERENCES orders(id),
  old_status VARCHAR(20),
  new_status VARCHAR(20),
  changed_by VARCHAR(100),               -- 'system', 'victor', 'josh', 'albert'
  note TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

appointments (
  id SERIAL PRIMARY KEY,
  order_id INTEGER REFERENCES orders(id),
  tech_id INTEGER,
  date DATE,
  time_from TIME,
  time_to TIME,
  confirmed_by_mieter BOOLEAN DEFAULT FALSE,
  reminder_sent BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT NOW()
);

technicians (
  id INTEGER PRIMARY KEY,
  name VARCHAR(100),
  bo_id VARCHAR(20),
  home_lat FLOAT,
  home_lng FLOAT,
  city VARCHAR(100),
  region VARCHAR(20),
  color VARCHAR(10),
  active BOOLEAN DEFAULT TRUE
);
```

---

## SPRINT-PLAN (6 Sprints, Pipeline-First)

### Sprint 1: Fundament (Pipeline + Auth + Persistenz)
**TRA-57** Pipeline: Status-System
**TRA-58** Pipeline: Kanban-Board  
**TRA-39** Auth: Login mit Rollen
- Vercel Postgres einrichten
- Orders-Tabelle + Status-Machine
- B&O Sync: Neue Aufträge automatisch importieren → Status `new`
- Auth: Simple Token-basiert oder Supabase Auth
- Kanban-Board: Drag & Drop zwischen Status-Spalten

### Sprint 2: Terminvereinbarung
**TRA-59** Auto-Erstanschreiben (Superchat Template)
**TRA-60** Terminvorschläge (Kalender)
**TRA-62** Auto-Status bei Mieter-Bestätigung
- Template-System: "Hallo {name}, wir haben Ihren Auftrag..."
- Superchat Send-API (bereits send-only — reicht!)
- Mieter antwortet → Webhook → Dashboard zeigt Antwort
- Victor wählt Termin → Status = TERMINIERT

### Sprint 3: Route aus Terminen + Techniker-Kalender
**TRA-64** Nur terminierte Aufträge routen
**TRA-65** Tagesplanung (Termine → Reihenfolge → Techniker)
**TRA-61** Kalender-View pro Techniker
- routes.js refactorn: nur Status=TERMINIERT+EINGEPLANT
- Kalender-Ansicht: Wer hat wann wie viele Jobs?
- Konflikterkennung: 2 Termine gleichzeitig

### Sprint 4: Techniker-Experience
**TRA-47** Tages-Briefing per WhatsApp
**TRA-49** Nächster-Job Button
**TRA-48** Job-Abschluss Formular
- Techniker-View: nur eigene Jobs sehen
- "Erledigt" Button → Status = DONE → Hero updaten
- Morgen-Briefing Cron: 07:00 WhatsApp mit Route

### Sprint 5: Hero-Sync + Full Automation
**TRA-42** B&O → Hero Job mit Techniker
**TRA-43** Bidirektionaler Status-Sync
**TRA-54** Auto: Neuer Auftrag → sofort Techniker + Route
- Bei Status TERMINIERT → Hero Job erstellen
- Hero Job erledigt → Dashboard Status updaten
- Vollautomatik: B&O Auftrag → Anschreiben → Termin → Route → Erledigt

### Sprint 6: KPIs + Mobile + Polish
**TRA-50** Aufträge pro Woche/Techniker
**TRA-51** Durchschnittliche Bearbeitungszeit
**TRA-34** Mobile-First + PWA
**TRA-35** Push Notifications
- KPI-Dashboard: Trends, Vergleiche, Alerts
- PWA mit Offline-Cache
- Push bei dringenden Aufträgen

---

## Paperclip Issues (48 total: TRA-21 bis TRA-68)

### B&O Engine
- TRA-21: Auto-Retry + Session-Pool + Health-Check (high)
- TRA-22: Auftragshistorie — Timeline pro Auftrag (medium)
- TRA-23: Auto-Accept → Hero + Techniker-Zuweisung (high)

### Superchat
- TRA-24: Template-Nachrichten mit Platzhaltern (high)
- TRA-25: Auto-Reminder bei >4h ohne Antwort (medium)
- TRA-26: Webhook Produktiv-Setup (high)

### Routing
- TRA-27: Zeitfenster pro Auftrag (high)
- TRA-28: Multi-Tag Wochenplanung (medium)
- TRA-29: Live-Tracking + ETA (low)
- TRA-30: Outlier 1-Klick Reassignment (high)

### Email
- TRA-31: KI-Klassifikation statt Keywords (medium)
- TRA-32: Auto-Reply für Standard-Anfragen (medium)
- TRA-33: Auftragsnummer → B&O Deeplink (low)

### Dashboard UX
- TRA-34: Mobile-First + PWA (high)
- TRA-35: Push-Notifications (medium)
- TRA-36: Tages-Report per WhatsApp (medium)

### Datenqualität
- TRA-37: Geocoding Straßen-Level (medium)
- TRA-38: Kontakt-Deduplikation (low)

### Auth & Rollen
- TRA-39: Login-System mit Rollen (high)
- TRA-40: Techniker-View (high)
- TRA-41: Einladungslink (medium)

### Hero Deep-Integration
- TRA-42: B&O → Hero Job + Techniker + Termin (high)
- TRA-43: Status-Sync bidirektional (high)
- TRA-44: Kontakt-Sync (medium)
- TRA-45: Task-Board im Dashboard (medium)
- TRA-46: Materialverbrauch (low)

### Techniker-Experience
- TRA-47: Tages-Briefing per WhatsApp (high)
- TRA-48: Job-Abschluss Formular (medium)
- TRA-49: Nächster-Job Button (medium)

### KPIs
- TRA-50: Aufträge pro Woche/Techniker (medium)
- TRA-51: Bearbeitungszeit (medium)
- TRA-52: Erstanschreiben-Quote (low)
- TRA-53: Kundenrückmeldungsrate (low)

### Automatisierung
- TRA-54: Auto-Assign neue Aufträge (high)
- TRA-55: Eskalation nach 3 Versuchen (medium)
- TRA-56: Freitag Wochenreport (medium)

### Pipeline-Engine
- TRA-57: Status-System (critical)
- TRA-58: Kanban-Board (critical)
- TRA-59: Auto-Erstanschreiben (critical)
- TRA-60: Terminvorschläge (critical)
- TRA-61: Kalender pro Techniker (high)
- TRA-62: Auto-Status bei WhatsApp-Bestätigung (high)
- TRA-63: Erinnerung 1 Tag vorher (medium)
- TRA-64: Route nur aus Terminierten (critical)
- TRA-65: Tagesplanung (high)
- TRA-66: Konflikterkennung (high)
- TRA-67: Eskalation 48h (high)
- TRA-68: Termin überfällig (medium)
