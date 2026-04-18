# Smart PDF Reader - Web App Architecture

## Vision: "Wie Kindle für PDFs"

**Was der User sieht:**
```
┌─────────────────────────────────────────┐
│  📚 Smart PDF Reader                    │
├─────────────────────────────────────────┤
│                                         │
│  📚 My Documents                        │
│  ├─ TME102_Statik.pdf      (NEW)       │
│  ├─ NextJob_Handbook.pdf   (In Progress)
│  └─ Marketing_Guide.pdf    (Completed) │
│                                         │
├─────────────────────────────────────────┤
│  📖 Currently Reading: TME102            │
│                                         │
│  Chapter 1: Tragelemente                │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━ 45%         │
│                                         │
│  [◄◄] [▶] [▶▶] [1.0x] [settings]      │
│                                         │
│  Ein Stab ist ein gerades Bauteil...   │
│  (transcript scrolls + highlights)     │
│                                         │
├─────────────────────────────────────────┤
│  💾 Progress saved: 5m 32s              │
│  📊 Comprehension: 85%                  │
└─────────────────────────────────────────┘
```

---

## Tech Stack

### Frontend
```
React / Next.js
├─ PDF Upload Component
├─ Audio Player (custom)
├─ Transcript + Highlighting
├─ Progress Bar
└─ Settings Panel

UI Library: Tailwind CSS
State: zustand or Redux
Audio API: Web Audio API
```

### Backend
```
Node.js / Express
├─ PDF Processing (smart extraction)
├─ TTS Audio Generation (pyttsx3 + worker)
├─ User Progress Tracking
├─ Session Management
└─ REST API

Database: PostgreSQL (or SQLite for MVP)
Storage: Local Filesystem or S3
```

### Infrastructure
```
Option 1 (Simple): 
  - Vercel (Frontend)
  - Vercel (Backend)
  - PostgreSQL (Managed)

Option 2 (Full Control):
  - Docker Container
  - Hetzner VPS
  - PostgreSQL
  - Nginx Reverse Proxy
```

---

## MVP Scope (2-4 Weeks)

### Phase 1: Core (Week 1)

**What works:**
- ✅ Upload PDF
- ✅ Automatic extraction (smart + boilerplate removal)
- ✅ Generate audio
- ✅ Play audio

**What NOT in MVP:**
- ❌ User authentication (start simple)
- ❌ Multiple users
- ❌ Cloud storage (local only)
- ❌ Sharing/Export
- ❌ Advanced settings

### Phase 2: Progress Tracking (Week 2)

**Add:**
- ✅ Save progress (where did user stop?)
- ✅ Resume from last position
- ✅ Play/Pause/Forward/Backward
- ✅ Speed control (0.75x, 1.0x, 1.25x, 1.5x)
- ✅ Transcript display + scroll sync

### Phase 3: Polish (Week 3-4)

**Add:**
- ✅ Comprehension questions (optional)
- ✅ Analytics (time listened, comprehension score)
- ✅ Multiple documents
- ✅ Dark mode
- ✅ Mobile responsive

---

## Database Schema (Simple)

```sql
-- Users (MVP: skip auth, use local storage)
CREATE TABLE users (
  id UUID PRIMARY KEY,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Documents (PDFs uploaded)
CREATE TABLE documents (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  filename VARCHAR(255),
  original_pdf_path VARCHAR(512),
  upload_date TIMESTAMP DEFAULT NOW(),
  status VARCHAR(50) -- "processing", "ready", "error"
);

-- Chapters (extracted from PDFs)
CREATE TABLE chapters (
  id UUID PRIMARY KEY,
  document_id UUID REFERENCES documents(id),
  chapter_num INTEGER,
  title VARCHAR(255),
  cleaned_text TEXT,
  audio_path VARCHAR(512),
  duration_seconds INTEGER,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Sessions (user listening sessions)
CREATE TABLE sessions (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  chapter_id UUID REFERENCES chapters(id),
  started_at TIMESTAMP DEFAULT NOW(),
  last_position_seconds INTEGER,
  completed BOOLEAN DEFAULT FALSE,
  completion_percentage FLOAT,
  playback_speed FLOAT DEFAULT 1.0,
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Comprehension (optional Q&A after listening)
CREATE TABLE comprehension_results (
  id UUID PRIMARY KEY,
  session_id UUID REFERENCES sessions(id),
  question VARCHAR(512),
  user_answer TEXT,
  score FLOAT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

---

## API Endpoints (Backend)

```
POST   /api/documents/upload          → Upload PDF
GET    /api/documents                  → List user's PDFs
GET    /api/documents/:id              → Get document details
GET    /api/documents/:id/chapters     → List chapters

POST   /api/chapters/:id/generate-audio → Start audio generation
GET    /api/chapters/:id/audio         → Stream audio file

POST   /api/sessions                   → Start listening session
GET    /api/sessions/:id               → Get session progress
PUT    /api/sessions/:id               → Save progress (position + speed)

POST   /api/comprehension              → Submit Q&A answer
GET    /api/analytics/user             → Get user analytics (time, comprehension)
```

---

## Frontend Components

```typescript
// Main App
<SmartPDFReaderApp>
  ├─ <DocumentList />           (Left sidebar: all documents)
  ├─ <DocumentUpload />         (Upload new PDF)
  ├─ <AudioPlayer />            (Center: play/pause/controls)
  ├─ <Transcript />             (Bottom: text + sync)
  ├─ <ProgressBar />            (Where are we?)
  ├─ <ComprehensionModal />     (Optional Q after listening)
  └─ <Analytics />              (Stats: time, comprehension)
```

### AudioPlayer Component
```typescript
<AudioPlayer
  audioUrl="/api/chapters/:id/audio"
  duration={chapter.duration_seconds}
  onPlay={() => saveSession()}
  onPause={() => saveProgress()}
  onPositionChange={(pos) => saveProgress(pos)}
  onSpeedChange={(speed) => saveSpeed(speed)}
  speeds={[0.75, 1.0, 1.25, 1.5]}
/>
```

### Transcript Component
```typescript
<Transcript
  text={chapter.cleaned_text}
  currentTimeMs={audioCurrentTime}
  syncHighlight={true}
  onSelection={(text) => handleSelection(text)}
/>
```

---

## Workflow (User Perspective)

### First Time
```
1. Open app → "Upload PDF"
2. Select TME102.pdf
3. System: Extracts chapters automatically
4. System: Generates audio (background worker)
5. Status: "Chapter 1 processing... 45%"
6. Once ready: "Chapter 1: Click to listen"
```

### Listening
```
1. Click "Chapter 1"
2. Audio player loads
3. Transcript shows below
4. Click PLAY
5. Audio starts, transcript highlights + scrolls
6. User can:
   - Pause/Resume
   - Change speed (1.5x for faster)
   - Jump forward/backward (±15s buttons)
   - Click transcript to jump to time
7. Session saves automatically every 30 seconds
```

### Resume Later
```
1. Open app
2. "Continue: Chapter 1 (5:32 / 7:45)"
3. Click → resumes at 5:32
4. Keeps going from where you left off
```

### Progress Display
```
All documents list shows:
- Filename
- Number of chapters
- Current chapter
- Progress bar (% complete)
- Time listened so far
- Comprehension score (if done Q&A)

Example:
  📖 TME102_Statik.pdf
     Chapter 1/8 • 45% complete
     ━━━━━━━░░░░ 3h 25m listened
     Comprehension: 87%
```

---

## Backend Worker (Audio Generation)

```python
# Worker process (can run in background)
from celery import Celery
from pyttsx3_wrapper import generate_speech

@celery.task
def generate_chapter_audio(chapter_id: str):
    """
    Background job to generate audio
    1. Fetch chapter text from DB
    2. Generate audio
    3. Save to storage
    4. Update DB status
    5. Notify frontend (WebSocket)
    """
    
    chapter = db.chapters.get(chapter_id)
    
    try:
        # Generate
        audio_bytes = generate_speech(
            chapter.cleaned_text,
            language='de-DE',
            speed=140
        )
        
        # Save
        audio_path = f"/storage/chapters/{chapter_id}.mp3"
        save_file(audio_path, audio_bytes)
        
        # Update DB
        db.chapters.update(chapter_id, {
            'audio_path': audio_path,
            'status': 'ready',
            'duration_seconds': get_duration(audio_path)
        })
        
        # Notify via WebSocket
        notify_user(chapter.document_id, f"Chapter {chapter.chapter_num} ready!")
        
    except Exception as e:
        db.chapters.update(chapter_id, {'status': 'error', 'error_msg': str(e)})
        notify_user(chapter.document_id, f"Error: {str(e)}")
```

---

## Progress Tracking (Detailed)

### Auto-Save
```typescript
// Every 30 seconds OR on pause:
saveProgress({
  sessionId: current_session_id,
  currentPosition: audioPlayer.currentTime,
  speed: audioPlayer.playbackRate,
  timestamp: Date.now()
});

// Response saves to DB:
UPDATE sessions 
SET last_position_seconds = ?, playback_speed = ?, updated_at = NOW() 
WHERE id = ?;
```

### Resume Logic
```typescript
// When user opens document:
const session = await getLatestSession(documentId, chapterId);
if (session && session.completed === false) {
  // Resume
  audioPlayer.currentTime = session.last_position_seconds;
  audioPlayer.playbackRate = session.playback_speed;
} else {
  // Start fresh
  audioPlayer.currentTime = 0;
}
```

### Analytics
```
Time Listened:
  SELECT SUM(last_position_seconds) 
  FROM sessions 
  WHERE user_id = ? AND completed = true;

Comprehension Over Time:
  SELECT chapter_id, AVG(score) as avg_score
  FROM comprehension_results
  WHERE session_id IN (SELECT id FROM sessions WHERE user_id = ?)
  GROUP BY chapter_id;

Documents Progress:
  SELECT 
    d.filename,
    COUNT(c.id) as total_chapters,
    COUNT(CASE WHEN s.completed THEN 1 END) as completed_chapters,
    (COUNT(CASE WHEN s.completed THEN 1 END) / COUNT(c.id) * 100) as progress_percent
  FROM documents d
  LEFT JOIN chapters c ON d.id = c.document_id
  LEFT JOIN sessions s ON c.id = s.chapter_id
  WHERE d.user_id = ?
  GROUP BY d.id;
```

---

## MVP Roadmap

### Week 1: Core (MVP 1.0)
- [x] Frontend (React component)
- [x] Backend (Node.js API)
- [x] PDF extraction
- [x] Audio generation
- [x] Audio playback
- [x] Progress save/resume
- [ ] NOT: Auth, multiple users, cloud storage

### Week 2: UX Polish
- [ ] Speed controls (0.75x, 1.5x)
- [ ] Transcript sync + highlight
- [ ] Better visual design
- [ ] Mobile responsive
- [ ] Better progress indication

### Week 3: Analytics + Q&A
- [ ] Optional comprehension questions
- [ ] Simple analytics dashboard
- [ ] Document list with progress

### Week 4: Launch Ready
- [ ] Error handling
- [ ] Better loading states
- [ ] Documentation
- [ ] Victor test + feedback
- [ ] Deploy to production

---

## Tech Stack Details

### Frontend
```json
{
  "framework": "Next.js 14",
  "styling": "Tailwind CSS",
  "state": "zustand",
  "components": "shadcn/ui",
  "audio": "Web Audio API + custom player",
  "storage": "localStorage (MVP)"
}
```

### Backend
```json
{
  "runtime": "Node.js 20",
  "framework": "Express.js",
  "database": "PostgreSQL (or SQLite for MVP)",
  "pdf-processing": "pdfplumber + pypdf",
  "tts": "pyttsx3 (via Python worker)",
  "file-storage": "Local filesystem (or S3 later)",
  "async-jobs": "Bull queue (Redis) - optional"
}
```

### Deployment
```
Option 1 (Simplest):
  - Vercel (Next.js Frontend)
  - Vercel Serverless (Express Backend)
  - PostgreSQL (Vercel Postgres)
  → Total: ~$10-30/month

Option 2 (More Control):
  - Docker container
  - Hetzner VPS (€3-10/month)
  - PostgreSQL (managed)
  → Total: ~€5-15/month
```

---

## Why This is Smart

1. **Self-contained:** Everything in one app
2. **Persistent:** Saves progress automatically
3. **Scalable:** Easy to add more documents
4. **Data-driven:** Tracks time + comprehension
5. **Learnable:** Each interaction → data for neural network (2027)
6. **Fundational:** First MVP for PrivatTeacher + NextJob

---

## Timeline

- **Week 1-2:** Build MVP (core features)
- **Week 3-4:** Polish + test with Victor
- **Week 4:** Deploy
- **Week 5+:** Integrate with PrivatTeacher (tracking) + NextJob (learning paths)

---

## The Bigger Picture

```
Smart PDF Reader Web App
    ↓ (User listens, system tracks)
PrivatTeacher
    ├─ Spaced Repetition (review schedule)
    ├─ Interleaving (mix topics)
    ├─ Elaboration (multiple explanations)
    └─ Adaptive Feedback (personalized)
    ↓ (Data from 100k+ users)
NextJob
    ├─ Diagnose (what can they learn?)
    ├─ Matching (what job fits?)
    └─ Reskilling (PrivatTeacher + Mentor)
    ↓
= HUMAN RESILIENCE INFRASTRUCTURE
```

This is not "just a PDF reader".  
This is the **first real product** in your $15B ecosystem.

---

## Decision Time

**Question:** How soon do you want this built?

- **Option A (MVP 4 weeks):** Basic but functional. Minimal features.
- **Option B (MVP + Polish 6-8 weeks):** Polished, beautiful, production-ready.
- **Option C (Start now + iterate):** Build together, iterate based on usage.

**My recommendation:** Option C. Build Week 1 MVP, then Victor uses it + gives feedback. Week 2-3 we fix/improve.
