# NextJob — Technische Spezifikation & Fahrplan

**Angelegt:** 2026-03-08 | **Zuletzt aktualisiert:** 2026-03-08

---

## 🏗️ Gesamtarchitektur

### Prinzip: Monolith zuerst, Microservices wenn nötig
Für MVP kein Over-Engineering. Ein gut strukturierter Monolith ist schneller zu bauen,
einfacher zu debuggen und für die ersten 10.000 Nutzer absolut ausreichend.
Aufteilen wenn: Performance-Bottleneck nachgewiesen ODER Team > 5 Entwickler.

```
┌─────────────────────────────────────────────────────────┐
│                    BROWSER / APP                        │
│                    Next.js (React)                      │
└────────────────────────┬────────────────────────────────┘
                         │ HTTPS / WebSocket
┌────────────────────────▼────────────────────────────────┐
│                   BACKEND (FastAPI)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  REST API    │  │  WebSocket   │  │  Task Queue   │  │
│  │  /api/v1/... │  │  /ws/coach   │  │  (Celery)     │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
│         │                 │                  │           │
│  ┌──────▼─────────────────▼──────────────────▼───────┐  │
│  │              Service Layer                         │  │
│  │  AssessmentService | CareerService | CoachService │  │
│  │  LearningService   | UserService   | AnalyticsS.  │  │
│  └──────┬─────────────────────────────────────────────┘  │
└─────────┼───────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────────────────────────────┐
│                  DATEN-SCHICHT                          │
│  PostgreSQL    │  Redis Cache  │  S3 (Videos/Files)    │
│  (Hauptdaten)  │  (Sessions)   │  (Cloudflare CDN)     │
└────────────────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────────────────────────────┐
│              EXTERNE SERVICES                          │
│  Claude API   │  Stripe       │  Resend (Email)        │
│  (KI-Coach)   │  (Payments)   │  (Transactional Mail)  │
└────────────────────────────────────────────────────────┘
```

---

## 💾 Datenbank-Schema (PostgreSQL)

### Kern-Tabellen

```sql
-- Nutzer
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       VARCHAR(255) UNIQUE NOT NULL,
    name        VARCHAR(255),
    created_at  TIMESTAMP DEFAULT NOW(),
    tier        VARCHAR(20) DEFAULT 'free',  -- free | starter | pro
    stripe_id   VARCHAR(255)
);

-- Job-Risiko-Datenbank (kuratiert, kein User-Input)
CREATE TABLE job_profiles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title_de            VARCHAR(255) NOT NULL,  -- "Buchhalter/in"
    title_en            VARCHAR(255),           -- "Accountant"
    esco_code           VARCHAR(50),            -- ESCO Standardcode
    risk_score_2027     DECIMAL(3,2),           -- 0.00 - 1.00
    risk_score_2030     DECIMAL(3,2),
    risk_score_2035     DECIMAL(3,2),
    high_risk_tasks     JSONB,  -- ["Dateneingabe", "Standardberichte", ...]
    low_risk_tasks      JSONB,
    essential_skills    JSONB,  -- ESCO Skill IDs
    search_aliases      JSONB   -- ["Bilanzbuchhalter", "Finanzbuchhalter", ...]
);

-- User Assessment (Ergebnis des Fragebogens)
CREATE TABLE assessments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id),
    job_profile_id  UUID REFERENCES job_profiles(id),
    confirmed_skills    JSONB,   -- welche Skills der Nutzer bestätigt hat
    preferences     JSONB,   -- max_weeks, salary_pref, learning_hours
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Karrierepfade (kuratiert)
CREATE TABLE career_paths (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           VARCHAR(255) NOT NULL,     -- "KI-Operator"
    from_job_id     UUID REFERENCES job_profiles(id),
    to_job_id       UUID REFERENCES job_profiles(id),
    learning_weeks  INTEGER,
    salary_delta    DECIMAL(4,2),  -- +0.08 = +8%
    skill_overlap   DECIMAL(3,2),
    ai_risk_target  DECIMAL(3,2),  -- Risiko des Zielberufs
    description     TEXT,
    is_active       BOOLEAN DEFAULT TRUE
);

-- Lernmodule
CREATE TABLE modules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    career_path_id  UUID REFERENCES career_paths(id),
    title           VARCHAR(255) NOT NULL,
    description     TEXT,
    order_index     INTEGER,
    duration_min    INTEGER,   -- Geschätzte Lernzeit in Minuten
    is_free         BOOLEAN DEFAULT FALSE  -- erstes Modul kostenlos
);

-- Lektionen innerhalb eines Moduls
CREATE TABLE lessons (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module_id   UUID REFERENCES modules(id),
    title       VARCHAR(255) NOT NULL,
    content_type VARCHAR(50),  -- video | article | exercise | quiz
    content_url  VARCHAR(500), -- S3 URL oder externer Link
    content_md   TEXT,         -- Markdown für Artikel-Lektionen
    order_index  INTEGER,
    duration_min INTEGER
);

-- User Fortschritt
CREATE TABLE user_progress (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id),
    career_path_id  UUID REFERENCES career_paths(id),
    module_id       UUID REFERENCES modules(id),
    lesson_id       UUID REFERENCES lessons(id),
    status          VARCHAR(20),  -- not_started | in_progress | completed
    completed_at    TIMESTAMP,
    score           INTEGER  -- Quiz-Score falls vorhanden
);

-- KI-Coach Konversationen
CREATE TABLE coach_conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id),
    messages    JSONB,  -- [{role: "user", content: "..."}, {role: "assistant"...}]
    context     JSONB,  -- aktueller Lernstand, gewählter Pfad, etc.
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- Quiz-Antworten (für Lernanalyse)
CREATE TABLE quiz_responses (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id),
    lesson_id   UUID REFERENCES lessons(id),
    answers     JSONB,
    score       INTEGER,
    created_at  TIMESTAMP DEFAULT NOW()
);
```

---

## 🔌 API-Design (REST + WebSocket)

### REST Endpoints

```
AUTH
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
GET    /api/v1/auth/me

ASSESSMENT (Job-Risiko-Check)
GET    /api/v1/jobs/search?q=buchhalter     → Fuzzy-Search in job_profiles
GET    /api/v1/jobs/{id}/risk               → Risiko-Score + Tasks
POST   /api/v1/assessments                  → Skills-Fragebogen speichern
GET    /api/v1/assessments/{id}/matches     → 3 Karrierepfad-Empfehlungen

KARRIEREPFADE
GET    /api/v1/paths/{id}                   → Pfad-Details
POST   /api/v1/paths/{id}/enroll            → Pfad wählen
GET    /api/v1/paths/{id}/modules           → Module des Pfads

LERNEN
GET    /api/v1/modules/{id}                 → Modul mit Lektionen
GET    /api/v1/lessons/{id}                 → Lektion-Content
POST   /api/v1/lessons/{id}/complete        → Lektion als erledigt markieren
POST   /api/v1/quizzes/{id}/submit          → Quiz-Antworten einreichen

FORTSCHRITT
GET    /api/v1/users/me/progress            → Gesamtfortschritt
GET    /api/v1/users/me/dashboard           → Dashboard-Daten (Kurse, Stats)

PAYMENT
POST   /api/v1/billing/checkout             → Stripe Checkout Session
POST   /api/v1/billing/webhook              → Stripe Webhook (intern)
GET    /api/v1/billing/portal               → Stripe Customer Portal
```

### WebSocket: KI-Coach

```
ws://api.nextjob.de/ws/coach

Client → Server:
{
  "type": "message",
  "content": "Ich verstehe Modul 2 nicht, kannst du...",
  "context": {
    "current_lesson_id": "uuid",
    "career_path": "KI-Operator",
    "progress_pct": 34
  }
}

Server → Client (Streaming):
{
  "type": "stream_chunk",
  "content": "Klar! Lass mich das",
  "done": false
}
{
  "type": "stream_chunk", 
  "content": " erklären...",
  "done": true
}
```

---

## 🧠 Die Analyse-Engine — vollständig

### Modul 1: Job-Fuzzy-Search

Nutzer tippt "Bilanzbuchhalter" → System findet "Buchhalter/in" in der Datenbank.

```python
# PostgreSQL Full-Text-Search + Trigram-Ähnlichkeit
# pg_trgm Extension (eingebaut in PostgreSQL)

async def search_jobs(query: str, limit: int = 5):
    sql = """
    SELECT 
        id, title_de, risk_score_2030,
        similarity(title_de, :query) as sim,
        -- auch Aliases durchsuchen
        jsonb_array_elements_text(search_aliases) as alias
    FROM job_profiles
    WHERE 
        title_de % :query          -- trigram match (% = Ähnlichkeit)
        OR search_aliases::text ILIKE :pattern
    ORDER BY sim DESC
    LIMIT :limit
    """
    # Threshold: similarity > 0.3 → Match
    # Beispiel: "Bilanzbuchhalter" → "Buchhalter/in" mit sim=0.67 ✓
```

**MVP-Datenbank: 30-50 Berufe** händisch gepflegt.
**Phase 3:** Automatische Erweiterung via ESCO API + KI-Kategorisierung.

---

### Modul 2: Risiko-Score-Berechnung

MVP: Statische Datenbank aus publizierten Quellen.

```python
# Datenquellen die wir kombinieren:
# 1. IAB-Studie "Substituierbarkeitspotenziale" (Deutschland, 2021)
# 2. Oxford/Frey&Osborne (2013, 702 Berufe)
# 3. McKinsey MGI Automation Report (2017, aktualisiert 2023)
# 4. OECD Task-Based Approach (2019)

# Gewichtung der Quellen:
WEIGHTS = {
    "iab": 0.40,        # Deutschlandspezifisch → höchste Gewichtung
    "oxford": 0.25,     # Ältester aber breitester Datensatz
    "mckinsey": 0.25,   # Aktuelle Task-basierte Methode
    "oecd": 0.10        # Ergänzend
}

def calculate_risk(job_title: str) -> dict:
    raw_scores = fetch_from_all_sources(job_title)
    
    # Gewichteter Durchschnitt
    base_score = sum(
        raw_scores[source] * weight 
        for source, weight in WEIGHTS.items()
        if source in raw_scores
    )
    
    # Zeitprojektion (exponentielle Kurve)
    # KI-Adoption beschleunigt sich → nicht linear
    return {
        "current": base_score * 0.4,    # Heute schon teilweise
        "2027": base_score * 0.65,
        "2030": base_score,             # Basejahr der Studien
        "2035": min(base_score * 1.3, 0.98)
    }
```

---

### Modul 3: Skills-Matching-Algorithmus

```python
from dataclasses import dataclass
from typing import Set

@dataclass
class UserProfile:
    current_job_id: str
    confirmed_skills: Set[str]   # ESCO Skill-IDs
    max_weeks: int               # Wie lange darf Umschulung dauern?
    salary_preference: float     # 0.0 = egal, 1.0 = maximales Gehalt
    learning_hours_per_week: int

@dataclass 
class CareerMatchResult:
    career_path_id: str
    target_job_title: str
    match_score: float          # 0.0 - 1.0
    skill_overlap_pct: float    # % der Zielskills die Nutzer hat
    missing_skills: list        # Was noch gelernt werden muss
    learning_weeks: int         # Realistisch basierend auf Stunden/Woche
    salary_delta: float         # +0.08 = +8%
    ai_risk_target: float       # Wie sicher ist der Zielberuf?
    explanation: str            # Kurze Begründung (später KI-generiert)

def calculate_match(
    user: UserProfile,
    career_path: CareerPath
) -> CareerMatchResult:
    
    target_skills = set(career_path.required_skills)
    user_skills = set(user.confirmed_skills)
    
    # Skill-Überschneidung
    overlap = user_skills & target_skills
    missing = target_skills - user_skills
    overlap_pct = len(overlap) / len(target_skills)
    
    # Lernzeit berechnen
    # Annahme: ~20 Stunden pro fehlenden Skill-Block (variiert)
    skill_hours = sum(
        SKILL_HOURS.get(skill, 20) for skill in missing
    )
    weeks_needed = skill_hours / user.learning_hours_per_week
    
    # Passt es in den Zeitrahmen?
    time_feasibility = (
        1.0 if weeks_needed <= user.max_weeks 
        else user.max_weeks / weeks_needed  # Penalty wenn zu lang
    )
    
    # Gehalts-Score
    salary_score = career_path.salary_delta * user.salary_preference
    
    # Zukunftssicherheit (wichtigstes Kriterium nach Overlap)
    future_safety = 1 - career_path.ai_risk_target
    
    # FINAL SCORE
    # Gewichtung kann A/B-getestet werden
    score = (
        overlap_pct    * 0.40 +  # Skill-Überschneidung
        future_safety  * 0.30 +  # Wie sicher ist der neue Job?
        time_feasibility * 0.20 + # Realistisch in Zeitrahmen?
        salary_score   * 0.10    # Gehaltserwartung
    )
    
    return CareerMatchResult(
        career_path_id=career_path.id,
        target_job_title=career_path.target_title,
        match_score=score,
        skill_overlap_pct=overlap_pct,
        missing_skills=list(missing),
        learning_weeks=round(weeks_needed),
        salary_delta=career_path.salary_delta,
        ai_risk_target=career_path.ai_risk_target,
        explanation=generate_explanation(overlap_pct, weeks_needed)
    )

def get_top_matches(user: UserProfile, n: int = 3) -> list[CareerMatchResult]:
    all_paths = fetch_paths_for_job(user.current_job_id)
    results = [calculate_match(user, path) for path in all_paths]
    return sorted(results, key=lambda r: r.match_score, reverse=True)[:n]
```

---

### Modul 4: KI-Coach (Claude API Integration)

```python
import anthropic
from fastapi import WebSocket

COACH_SYSTEM_PROMPT = """
Du bist NextJob Coach — ein empathischer, motivierender Karriere- und Lerncoach.

Du kennst den Nutzer vollständig:
- Aktueller Job: {current_job}
- Gewählter Karrierepfad: {career_path}
- Aktuelles Modul: {current_module}
- Fortschritt: {progress_pct}% abgeschlossen
- Letzte abgeschlossene Lektion: {last_lesson}
- Schwierigkeiten bisher: {pain_points}

Deine Persönlichkeit:
- Empathisch aber direkt — keine leeren Floskeln
- Motivierend ohne falsche Versprechungen
- Erkläre Konzepte einfach, mit Beispielen aus dem alten Job
- Frage aktiv nach wenn unklar was der Nutzer braucht
- Merke dir was der Nutzer in dieser Session gesagt hat

Antworte IMMER auf Deutsch.
Halte Antworten kurz (max 3-4 Sätze) außer bei komplexen Erklärungen.
"""

async def coach_stream(
    websocket: WebSocket,
    user_id: str,
    user_message: str,
    context: dict
):
    client = anthropic.Anthropic()
    
    # Konversationshistorie laden (max. letzte 20 Nachrichten)
    history = await load_conversation_history(user_id, limit=20)
    
    # System-Prompt mit User-Kontext füllen
    system = COACH_SYSTEM_PROMPT.format(**context)
    
    # Neue User-Nachricht zur History hinzufügen
    messages = history + [{"role": "user", "content": user_message}]
    
    # Streaming Response
    full_response = ""
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=system,
        messages=messages
    ) as stream:
        for text in stream.text_stream:
            full_response += text
            await websocket.send_json({
                "type": "stream_chunk",
                "content": text,
                "done": False
            })
    
    # Konversation speichern
    await save_message(user_id, "user", user_message)
    await save_message(user_id, "assistant", full_response)
    
    await websocket.send_json({"type": "stream_chunk", "done": True})
```

---

## 🖥️ Frontend-Architektur (Next.js)

### Seiten-Struktur

```
/                          → Landing Page (SEO-optimiert)
/check                     → Job-Risiko-Check (kein Login)
/check/[jobId]/result      → Risiko-Ergebnis + CTA
/register                  → Account erstellen
/onboarding                → Skills-Fragebogen (nach Registration)
/onboarding/matches        → 3 Karrierepfad-Empfehlungen
/dashboard                 → Hauptbereich (nach Pfad-Wahl)
/learn/[pathId]            → Lernpfad-Übersicht
/learn/[pathId]/[moduleId] → Modul mit Lektionen
/learn/[pathId]/[moduleId]/[lessonId] → Einzelne Lektion
/coach                     → KI-Coach (Chat-Interface)
/profile                   → Profil + Fortschritt
/billing                   → Abo verwalten
```

### State Management

```typescript
// Zustand: einfach halten für MVP
// Kein Redux — React Query für Server State + Zustand für UI State

// Server State (React Query):
const { data: userProgress } = useQuery({
  queryKey: ['progress', userId],
  queryFn: () => api.get('/users/me/progress'),
  staleTime: 30_000  // 30 Sekunden Cache
})

// UI State (Zustand):
interface AppStore {
  currentLesson: Lesson | null
  coachOpen: boolean
  onboardingStep: number
  setCurrentLesson: (lesson: Lesson) => void
  toggleCoach: () => void
}
```

### KI-Coach UI (Sidebar)

```typescript
// WebSocket Hook für streaming Coach
function useCoachWebSocket(userId: string) {
  const [messages, setMessages] = useState<Message[]>([])
  const [streaming, setStreaming] = useState(false)
  const wsRef = useRef<WebSocket>()
  
  const sendMessage = useCallback((content: string, context: Context) => {
    setStreaming(true)
    let currentChunk = ""
    
    wsRef.current?.send(JSON.stringify({ 
      type: "message", content, context 
    }))
    
    // Streaming-Chunks zu letzter Nachricht hinzufügen
    wsRef.current.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.done) {
        setStreaming(false)
        return
      }
      currentChunk += data.content
      setMessages(prev => [
        ...prev.slice(0, -1),
        { role: "assistant", content: currentChunk }
      ])
    }
  }, [])
  
  return { messages, sendMessage, streaming }
}
```

---

## 🚀 Infrastruktur & Deployment

### Entwicklung (lokal)

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: nextjob
      POSTGRES_USER: nextjob
      POSTGRES_PASSWORD: local_dev

  redis:
    image: redis:7-alpine

  backend:
    build: ./backend
    ports: ["8000:8000"]
    volumes: ["./backend:/app"]
    depends_on: [db, redis]
    environment:
      DATABASE_URL: postgresql://nextjob:local_dev@db/nextjob
      REDIS_URL: redis://redis:6379
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    volumes: ["./frontend:/app"]
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000
```

### Produktion (Hetzner)

```
Hetzner VPS (CPX31: 4 vCPU, 8GB RAM, 160GB SSD) = ~18€/Monat

Deployment Stack:
├── Nginx (Reverse Proxy + SSL)
├── Docker Compose (Prod-Version)
│   ├── Backend (FastAPI, 2 Worker)
│   ├── Frontend (Next.js, Static Export)
│   ├── PostgreSQL
│   ├── Redis
│   └── Celery Worker (Async Tasks)
└── Cloudflare (DNS + CDN + DDoS-Schutz)

Backups:
├── PostgreSQL: täglicher Dump → Hetzner S3 (Backup Bucket)
└── Code: GitHub (Private Repo)

SSL: Let's Encrypt (automatisch via Nginx)
```

### CI/CD (GitHub Actions)

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Backend Tests
        run: cd backend && pytest
      - name: Run Frontend Build
        run: cd frontend && npm run build

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.HETZNER_IP }}
          script: |
            cd /opt/nextjob
            git pull origin main
            docker compose -f docker-compose.prod.yml up -d --build
            docker compose exec backend alembic upgrade head
```

---

## 📅 Detaillierter Fahrplan

### 🔴 Phase 0 — Foundation (Woche 1-2)
*Alles aufsetzen bevor die erste Zeile Business-Code*

**Woche 1:**
- [ ] GitHub Repo anlegen (Monorepo: `/backend`, `/frontend`, `/data`)
- [ ] Docker Compose lokal aufsetzen (PostgreSQL + Redis + FastAPI + Next.js)
- [ ] Datenbankschema implementieren (alle Tabellen von oben)
- [ ] Alembic Migrations aufsetzen (DB-Versionierung)
- [ ] FastAPI Projekt-Struktur (Router, Services, Models, Schemas)
- [ ] Next.js Projekt-Struktur (Pages, Components, Hooks, API-Client)
- [ ] Auth implementieren (JWT Tokens, Register/Login/Me Endpoints)
- [ ] Tailwind CSS + Design System Basis (Farben, Typografie, Buttons)

**Woche 2:**
- [ ] Hetzner VPS aufsetzen + Nginx konfigurieren
- [ ] GitHub Actions CI/CD Pipeline (Test + Deploy)
- [ ] Domain + SSL (Let's Encrypt via Nginx)
- [ ] Monitoring: Sentry (Error Tracking) für Frontend + Backend
- [ ] Stripe Account + Webhook-Endpoint (Basis)
- [ ] Claude API Integration testen (einfacher Chat-Test)
- [ ] **Meilenstein: "Hello World" läuft auf Produktion**

---

### 🟡 Phase 1 — Analyse-Engine (Woche 3-6)
*Das Herzstück — Risiko-Check + Karrierepfad-Matching*

**Woche 3: Job-Datenbank**
- [ ] 30 Berufe aus IAB + Oxford + McKinsey Daten kuratieren
  - Buchhalter/in, Steuerfachangestellte/r
  - Verwaltungsangestellte/r, Sachbearbeiter/in
  - Sekretär/in, Bürokaufmann/-frau
  - Paralegal, Rechtsanwaltsfachangestellte/r
  - Personalreferent/in, Personalassistent/in
  - Bankkaufmann/-frau, Versicherungskaufmann/-frau
  - Einkäufer/in, Logistikkaufmann/-frau
  - Journalist/in, Texter/in (Copywriter)
  - Grafikdesigner/in, Mediengestalter/in
  - Customer Service Agent, Call-Center-Agent
  - + 10 weitere basierend auf Nutzer-Interviews
- [ ] ESCO Skills-Mapping für alle 30 Berufe
- [ ] Seed-Script für Datenbank

**Woche 4: Karrierepfade**
- [ ] 5-8 Pivot-Ziele für jeden der 30 Berufe definieren
- [ ] Pivot-Targets: KI-Operator, Datenschutzbeauftragter, UX Researcher,
  Data Analyst (Junior), HR-Tech Specialist, Prozessmanager/in,
  IT-Koordinator/in, E-Commerce Manager/in
- [ ] Learning Weeks + Salary Delta für jede Kombination
- [ ] Matching-Algorithmus implementieren + Tests

**Woche 5: Job-Risiko-Check (Frontend)**
- [ ] Landing Page (Hero, Proof Points, CTA)
- [ ] Such-Input mit Autocomplete (Fuzzy-Search gegen Job-DB)
- [ ] Risiko-Ergebnis-Seite (Score-Visualisierung, Tasks, CTA)
- [ ] Mobile-responsive (WCAG 2.2 AA)

**Woche 6: Skills-Fragebogen + Matches**
- [ ] Fragebogen UI (Multi-Step, Progress-Bar)
- [ ] Skills-Fragebogen Backend (Assessment speichern)
- [ ] Matching-Algorithmus API-Endpoint
- [ ] Karrierepfad-Cards UI (3 Optionen, Score-Anzeige)
- [ ] **Meilenstein: Nutzer kann Risiko-Check + Pfad-Empfehlung durchlaufen**

---

### 🟢 Phase 2 — Lernpfad (Woche 7-10)
*Erster vollständiger Lernpfad von A bis Z*

**Woche 7-8: Content — Buchhalter → KI-Operator**

Lernpfad-Struktur (6 Module):
```
Modul 1: Was ist KI? (kostenlos, 45 Min)
  → Lektion 1: KI einfach erklärt (Video 10 Min)
  → Lektion 2: KI in deinem alten Job (Artikel)
  → Lektion 3: Was KI kann und was nicht (Video 10 Min)
  → Quiz: 5 Fragen

Modul 2: Prompt Engineering Grundlagen (Pro, 2h)
  → Lektion 1: Was ist ein Prompt?
  → Lektion 2: Grundregeln für gute Prompts
  → Lektion 3: Prompts für Buchhalter (Praxisbeispiele!)
  → Übung: Schreib 5 Prompts für typische Buchhalter-Aufgaben
  → Quiz: 8 Fragen

Modul 3: KI-Tools in der Praxis (Pro, 3h)
  → ChatGPT, Claude, Copilot — Unterschiede
  → Workflow-Integration (wie nutze ich KI täglich?)
  → Daten-Analyse mit KI (Excel → KI)
  → Praxisprojekt: Erstelle einen KI-gestützten Monatsreport

Modul 4: KI koordinieren & steuern (Pro, 2h)
  → KI-Outputs prüfen und korrigieren
  → Qualitätssicherung KI-generierter Inhalte
  → Dokumentation von KI-Prozessen
  → Rechtliche Grundlagen (DSGVO + KI-Outputs)

Modul 5: Erste Schritte als KI-Operator (Pro, 3h)
  → Was macht ein KI-Operator beruflich?
  → Typische Tätigkeiten + Verantwortlichkeiten
  → Stellenprofile und Gehaltsrahmen
  → Selbstpräsentation: KI-Skills im Lebenslauf

Modul 6: Abschlussprojekt (Pro, 4h)
  → Eigenes Unternehmen wählen (fiktiv oder echt)
  → KI-Einsatzmöglichkeiten identifizieren
  → Präsentation erstellen
  → Peer-Review (andere Nutzer geben Feedback)
```

- [ ] Content für alle 6 Module schreiben/kuratieren
- [ ] Videos: Screen-Recordings + Voiceover (kein Profi-Studio nötig für MVP)
- [ ] S3 Bucket für Video-Hosting aufsetzen
- [ ] Cloudflare Stream oder Vimeo als Video-Player

**Woche 9: Lern-Interface**
- [ ] Modul-Übersicht mit Fortschrittsbalken
- [ ] Lektion-Player (Video + Artikel + Übung)
- [ ] Quiz-Interface (Multiple Choice)
- [ ] Fortschritts-Speicherung (API + Frontend)
- [ ] "Nächste Lektion" Logik
- [ ] Modul abschließen → Celebration-Screen

**Woche 10: Payment**
- [ ] Stripe Checkout Integration (Pro Tier: 19€/Monat)
- [ ] Modul-Locking (Modul 1 frei, Rest hinter Paywall)
- [ ] Stripe Webhook → Tier in Datenbank updaten
- [ ] Stripe Customer Portal (Abo kündigen, Rechnung herunterladen)
- [ ] **Meilenstein: Nutzer kann Lernpfad buchen + durcharbeiten**

---

### 🔵 Phase 3 — KI-Coach (Woche 11-12)
*Das emotionale Herzstück — warum Nutzer bleiben*

**Woche 11: Backend Coach**
- [ ] WebSocket Endpoint implementieren
- [ ] Claude API Integration mit Streaming
- [ ] Kontext-Injection (aktueller Lernstand, Pfad, Modul)
- [ ] Konversationshistorie speichern + laden
- [ ] Rate-Limiting (Free: 5 Nachrichten/Tag, Pro: unlimitiert)
- [ ] Proaktive Coach-Nachrichten (Celery Task):
  - 3 Tage kein Login → "Alles ok? Du warst 3 Tage nicht da"
  - Modul abgeschlossen → "Glückwunsch! Weiter zu Modul X?"
  - Schwieriges Quiz (< 60%) → "Soll ich das nochmal erklären?"

**Woche 12: Coach-UI + Launch-Vorbereitung**
- [ ] Chat-Interface (Sidebar oder eigene Seite)
- [ ] Streaming-Anzeige (Buchstaben erscheinen progressiv)
- [ ] Coach-Trigger aus Lernpfad (Kontextmenü in Lektionen: "Coach fragen")
- [ ] Onboarding-Email-Sequenz (Resend.com):
  - Tag 0: "Willkommen, dein Risiko-Report"
  - Tag 2: "Schau dir Karrierepfad X an"
  - Tag 5: "Fang heute an — Modul 1 ist kostenlos"
  - Tag 14: "Wie läuft's? Dein Coach wartet"
- [ ] Beta-Nutzer aus Waitlist einladen (50 Personen)
- [ ] **Meilenstein: MVP live, erste zahlende Nutzer**

---

## 📏 Technische Entscheidungen & Begründungen

| Entscheidung | Gewählt | Alternativen | Warum |
|---|---|---|---|
| Backend-Sprache | Python | Node.js, Go | KI-Libraries (Anthropic SDK, Pandas) sind in Python zuhause |
| Web-Framework | FastAPI | Django, Flask | Async-native (wichtig für WebSocket + KI-Streaming), automatische API-Docs |
| Frontend | Next.js | Remix, SvelteKit | Größtes Ökosystem, SSR für SEO, Vincent kennt React |
| Datenbank | PostgreSQL | MySQL, MongoDB | pg_trgm für Fuzzy-Search eingebaut, JSONB für flexible Felder, solide |
| Cache | Redis | Memcached | Pub/Sub für WebSocket-Skalierung später, allgemeiner einsetzbar |
| ORM | SQLAlchemy + Alembic | Prisma, Tortoise | Python-nativ, Alembic für DB-Migrationen ist Industriestandard |
| KI-Coach | Claude API | OpenAI GPT-4 | Längerer Kontext-Window, nuancierter in Deutsch, Anthropic-Erfahrung vorhanden |
| Hosting | Hetzner | AWS, Vercel | 10x günstiger als AWS für gleiche Performance, DSGVO-konform (EU) |
| Payment | Stripe | Paddle, Braintree | Bester Developer-Experience, sofort verfügbar in DE, SEPA-Support |
| Email | Resend | SendGrid, Postmark | Moderne API, günstig, Next.js-Integration |
| Video | S3 + Cloudflare | Vimeo, Wistia | Günstigste Option, volle Kontrolle |

---

## 🔐 Sicherheit & DSGVO

```
Pflicht von Tag 1:
├── Passwort-Hashing: bcrypt (nicht SHA, nicht MD5!)
├── JWT: kurze Laufzeit (15 Min Access Token, 7 Tage Refresh Token)
├── HTTPS: immer, kein HTTP
├── SQL Injection: SQLAlchemy ORM verhindert das automatisch
├── Rate Limiting: Nginx + FastAPI-Middleware
├── CORS: nur eigene Domain erlaubt
└── Secrets: .env Dateien, nie im Git-Repository!

DSGVO:
├── Datenschutzerklärung + Impressum (Pflicht DE)
├── Cookie-Banner (nur notwendige Cookies ohne Banner)
├── Recht auf Löschung: DELETE /api/v1/users/me Endpoint
├── Daten-Export: GET /api/v1/users/me/export (JSON)
├── Hosting: Hetzner (EU, DSGVO-konform)
└── Claude API: Anthropic verarbeitet Prompts nicht für Training (Business API)
```

---

## 💰 Kostenübersicht MVP (monatlich)

```
Hetzner VPS CPX31:          18€/Monat
Hetzner S3 (Videos, 50GB):   3€/Monat
Cloudflare (Free Tier):       0€/Monat
Claude API (100 Nutzer):     ~50€/Monat  (geschätzt)
Stripe:                       0€ + 1,4% + 0,25€/Transaktion
Resend (3.000 Mails/Monat):   0€/Monat (Free Tier)
Domain:                       1€/Monat
Sentry (Free Tier):           0€/Monat
────────────────────────────────────────
GESAMT MVP:                  ~72€/Monat

Break-Even:
4 Pro-Nutzer à 19€ = 76€ → kostendeckend 🎯
```

---

## 📋 Offene technische Fragen

1. **Video-Content selbst produzieren?** Screen-Recording + Voiceover reicht für MVP.
   Professionelle Videos erst wenn Nutzer-Feedback das verlangt.
2. **KI-generierter Content?** Für Long-Tail-Berufe sinnvoll — aber erst nach MVP.
3. **Mobile App?** React Native nach Phase 3. Erstmal Web.
4. **Mehrsprachigkeit?** Englisch ab Phase 4. MVP nur Deutsch.
5. **Zertifikate?** IHK-Partnerschaft anstreben ab Phase 3 — gibt enormen Vertrauensbonus.

---

## 🕷️ Scraping-Infrastruktur

Modul: `workspace/modules/human_scraper.py`
Geteilt mit TradeMind — gleiche Codebasis, verschiedene Scraper-Klassen.

Für NextJob relevante Scraper:
- `JobBoardScraper` — Bundesagentur API (offiziell) + Indeed/StepStone (Playwright)
- `EscoScraper` — ESCO API (offiziell, kostenlos) für Skills-Mapping
- `HumanScraper` (Basis) — allgemeine Sites

Verwendung im Backend:
```python
from modules.human_scraper import create_scraper

# Jobs von Bundesagentur (offiziell, kein Scraping nötig)
jobs_scraper = create_scraper("jobs")
offene_stellen = jobs_scraper.search_bundesagentur("KI-Operator", "Deutschland")

# ESCO Skills für Beruf
esco = create_scraper("esco")
berufe = esco.search_occupation("Buchhalter")
skills = esco.get_skills_for_occupation(berufe[0]["uri"])

# Marktbedarf (Indeed, Playwright benötigt)
stellen_indeed = jobs_scraper.scrape_indeed("Datenschutzbeauftragter", "Deutschland")
```

Installation:
```bash
pip install -r workspace/modules/requirements.txt
playwright install chromium
```

Humanisierungs-Techniken im Modul:
- User-Agent Rotation (7 echte Browser-Strings)
- Vollständige Browser-Headers (kein Scraper-Fingerprint)
- Normalverteilte Delays (kein Maschinenrhythmus)
- Session Persistence (Cookies)
- Rate Limiting per Domain (konfigurierbar)
- Playwright + Stealth (für JS-heavy / Cloudflare)
- Browser Fingerprint Randomisierung (Viewport, Locale, Timezone)
- Retry-Logik mit exponentiellem Backoff
- Automatischer Fallback: 403 → Playwright
