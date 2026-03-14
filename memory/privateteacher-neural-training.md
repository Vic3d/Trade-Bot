# PrivatTeacher — Neural Network Training Infrastructure

## VISION: Vom Regelwerk zur gelernten KI

**Heute:** KI-Tutor mit expliziten Regeln (if-else, Templates)
**Morgen (2027+):** Echtes neuronales Netzwerk, das aus echten Schüler-Interaktionen lernt

**Das erfordert eine ANDERE ARCHITEKTUR VON ANFANG AN.**

---

## 1. DER PARADIGMENWECHSEL

### Alt: Rule-Based Tutoring
```
Regel: IF (answer == wrong) AND (misconception == "XYZ")
       THEN show_fix("XYZ")
```
- Manuell geschrieben
- Inflexibel
- Nicht lernfähig

### Neu: Data-Driven Learning
```
Training Data:
  ├─ 100.000 Schüler-Interaktionen
  ├─ Pro Interaction: Input + Output + Outcome
  ├─ Pro Schüler: Profil (Lerntyp, Fähigkeiten, etc.)
  └─ Pro Aufgabe: Schwierigkeit, Konzept, Fehlkonzepte

Neural Network lernt:
  "Gegeben diese Schüler + diese Aufgabe → best feedback?"
  "Gegeben diese Antwort → welches Fehlkonzept?"
  "Gegeben diesen Zustand → nächste optimale Aufgabe?"
```

---

## 2. DATENINFRASTRUKTUR — Das Fundament

### 2a. Was muss ALLES getracked werden?

```python
@dataclass
class InteractionEvent:
    # IDENTIFIERS
    student_id: UUID
    session_id: UUID
    timestamp: datetime
    
    # CONTEXT
    concept: str  # "Stäbe", "Lager", etc.
    task_id: str
    task_difficulty: float  # 0.1 - 1.0
    task_type: str  # "classification", "calculation", "explanation"
    
    # STUDENT STATE (VOR Aufgabe)
    student_state_before: {
        "mastery_level": float,  # 0-1
        "confidence": float,  # 0-1
        "recent_correct_count": int,  # How many correct in a row?
        "total_attempts": int,
        "time_since_last_correct": timedelta,
        "motivation_level": float,  # 0-1 (estimated)
        "learning_style": str,  # "auditory", "kinesthetic", "visual"
        "mood": str  # "frustrated", "confident", "neutral"
    }
    
    # INTERACTION
    student_action: str  # Was the student doing?
    time_taken: float  # seconds
    response: str  # What did student answer?
    response_type: str  # "text", "image", "calculation", "multiple_choice"
    hint_requests: int  # How many hints?
    hint_levels_used: List[int]  # [1, 2, 3] if needed multiple hints
    
    # OUTCOME
    is_correct: bool
    correctness_score: float  # 0.0 - 1.0 (partial credit)
    misconception_detected: str  # which misconception? (if any)
    misconception_confidence: float  # how sure are we?
    
    # FEEDBACK GIVEN
    feedback_type: str  # "task_level", "process_level", etc.
    feedback_text: str
    hint_given: str  # if any
    
    # NEXT STEP
    next_action: str  # "continue", "advance", "remediate", "pause"
    
    # OUTCOME TRACKING (später)
    student_state_after: {
        "mastery_level": float,  # hat sich das geändert?
        "confidence": float,
        "motivation_level": float,
    }
```

**Warum so detailliert?**
- Neural Network lernt aus ALLEM
- Nicht nur "richtig/falsch", sondern: Zeit, Hints, Kontext, State-Änderung
- Mit 100.000 solcher Events können wir echte Muster erkennen

### 2b. Beispiel: Ein kompletter Event

```json
{
  "student_id": "vic_001",
  "session_id": "session_2026_03_14_001",
  "timestamp": "2026-03-14T15:23:45Z",
  
  "concept": "Stäbe",
  "task_id": "stab_classification_003",
  "task_difficulty": 0.3,
  "task_type": "classification",
  
  "student_state_before": {
    "mastery_level": 0.3,
    "confidence": 0.6,
    "recent_correct_count": 2,
    "total_attempts": 8,
    "time_since_last_correct": 120,
    "motivation_level": 0.7,
    "learning_style": "kinesthetic",
    "mood": "neutral"
  },
  
  "student_action": "answered_question",
  "time_taken": 85.5,
  "response": "Ja, das ist ein Stab weil es gelenkig ist",
  "response_type": "text",
  "hint_requests": 0,
  "hint_levels_used": [],
  
  "is_correct": false,
  "correctness_score": 0.0,
  "misconception_detected": "Querkräfte_übertragbar",
  "misconception_confidence": 0.85,
  
  "feedback_type": "process_level",
  "feedback_text": "Du denkst, ein Stab ist gelenkig = Stab. Das ist teilweise wahr, aber unvollständig...",
  "hint_given": "Moment um E: CH × l = 0. Was muss CH sein?",
  
  "next_action": "remediate",
  
  "student_state_after": {
    "mastery_level": 0.25,  # sank!
    "confidence": 0.5,  # sank!
    "motivation_level": 0.6  # slight dip
  }
}
```

---

## 3. TRAINING-DATEN-PIPELINE

### 3a. Wie generieren wir Millionen von Events?

**Phase 1: MVP (4 Wochen)**
- ~100 Events (Victor macht 30 Aufgaben, 3x durchgespielt)
- Manuell labeln

**Phase 2: Beta (2-3 Monate)**
- 10 Schüler × 50 Aufgaben × 2 Durchläufe = 1.000 Events
- Halbautomatisch labeln

**Phase 3: Expansion (6-12 Monate)**
- 100 Schüler × verschiedene Kurse = 100.000+ Events
- Vollautomatisch labeln (mit AI)

**Phase 4: Scale (2027+)**
- 1.000+ Schüler = 1.000.000+ Events
- Neural Network training beginnt

### 3b. Was labeln wir?

```
LABEL 1: Correctness (automatisch)
  ├─ "correct" (is_correct=true)
  ├─ "partially_correct" (correctness_score=0.5)
  └─ "incorrect" (is_correct=false)

LABEL 2: Misconception (AI-unterstützt, Mensch-reviewed)
  ├─ Welches Fehlkonzept? ("Querkräfte_übertragbar", "Stab_Balken_verwechslung", etc.)
  ├─ Wie sicher? (0.5 - 1.0)
  └─ Ist es neues Fehlkonzept? (ja/nein)

LABEL 3: Feedback-Effektivität (später)
  ├─ Hat Feedback geholfen? (nächste Aufgabe besser?)
  ├─ Welcher Feedback-Typ war best? (Task/Process/Regulation/Self)
  └─ Welcher Hint-Level optimal? (1-5)

LABEL 4: Learning Outcome (langfristig)
  ├─ Retension: Erinnert sich Student das in 1 Woche?
  ├─ Transfer: Kann er das auf neuen Kontext anwenden?
  └─ Deepening: Geht er zu Fachwerken über? Versteht das?
```

---

## 4. DER TRAININGS-ZYKLUS

### Schritt 1: DATEN SAMMELN (Regel-basierter Tutor)

```
Student macht Aufgabe
    ↓
Regelwerk entscheidet: Richtig/Falsch?
    ↓
Regelwerk entscheidet: Welches Feedback?
    ↓
Regelwerk entscheidet: Nächste Aufgabe?
    ↓
ALLES wird geloggt: student_action, feedback_given, outcome
    ↓
Event wird in DB gespeichert
```

### Schritt 2: LABELN & VALIDIEREN

```
Events in DB
    ↓
AI-Modell versucht Labels zu generieren (mit Confidence)
    ↓
Human-in-the-loop: Menschen überprüfen Label (oder akzeptieren AI)
    ↓
Labeled Dataset: [Event, Labels]
```

### Schritt 3: OFFLINE ANALYSIS

```
"Welche Feedback-Typen funktionieren best?"
    ↓
  Aggregiere Events:
    - Feedback_type="task_level" + next_outcome="correct" = 65% success
    - Feedback_type="process_level" + next_outcome="correct" = 80% success
    → Process-Level Feedback ist bessER!
    
"Welche Schüler-Profile brauchen welche Hints?"
    ↓
  Aggregate:
    - kinesthetic_students + hint_level=2 + visual_explanation = 75% success
    - kinesthetic_students + hint_level=3 + abstract_explanation = 40% success
    → Kinesthetic brauchen visuelle Hints!

"Wie genau sind unsere Fehlkonzept-Detektoren?"
    ↓
  Precision/Recall:
    - "Querkräfte_übertragbar" detector: 85% Precision, 70% Recall
    → Ganz gut, aber 30% werden wir nicht erkannt
```

### Schritt 4: RULE-UPDATES

```
Neue Erkenntnisse aus Analysis:
    ├─ "Process-Level Feedback funktioniert besser"
    └─ "Kinesthetic + visual hints = best"
    
Update Regelwerk:
    ├─ Mehr Process-Level Feedback geben
    └─ Kinesthetic Schüler immer visuelle Hints
    
    ↓
    Neue Rule-Version deployed
    
    ↓
    Neue Events sammeln mit UPDATE
    
    ↓
    Metrics verbessern sich (hoffentlich!)
```

### Schritt 5: SPÄTER - NEURAL NETWORK TRAINING

```
1.000.000+ gelabelter Events

    ↓

Neural Network Architecture:
  Input Layer:
    ├─ Student State (mastery, confidence, learning_style, mood, etc.)
    ├─ Task Features (difficulty, type, concept, etc.)
    ├─ Interaction History (recent correct count, time patterns, etc.)
    └─ Response Features (text embeddings, time taken, etc.)
  
  Hidden Layers:
    ├─ Student Encoder (characterize student)
    ├─ Task Encoder (characterize task)
    ├─ Interaction Encoder (characterize response)
    └─ Cross-Modal Attention (wie Student × Task × Response interagieren)
  
  Output Layers:
    ├─ Correctness Predictor (wird Student richtig antworten?)
    ├─ Misconception Classifier (welches Fehlkonzept?)
    ├─ Best Feedback Ranker (welcher Feedback-Typ für diesen Schüler?)
    ├─ Next Task Recommender (welche Aufgabe als nächste?)
    └─ Motivation Predictor (wird Schüler demoralisiert?)

Training:
  Loss = L_correctness + L_misconception + L_feedback + L_next_task + L_motivation
  
  Optimizer: Adam
  Batch Size: 32-64
  Epochs: 10-100 (depending on convergence)
  
    ↓
    
  Trained Model:
    "Gegeben [Student State + Task + Response] → Best [Feedback + Next Task]"
    
    ↓
    
  A/B Test:
    - Version A: Rule-Based Tutor (alt)
    - Version B: Neural Network Tutor (neu)
    - Metric: Lernfortschritt nach 4 Wochen
    - Hypothesis: Neural > Rule (um 15%+)
```

---

## 5. WAS OPTIMIEREN WIR FÜR?

### 5a. Metrik 1: Learning Speed

**Def:** Wie schnell lernt Schüler ein Konzept?

```
metric = (time_to_mastery_with_AI) / (time_to_mastery_without_AI)

Ziel: metric < 0.7 (AI macht 30% schneller)

Wie messen:
  - Erste Aufgabe "richtig" nach N Versuchen?
  - Erreiche "Mastery" (80%) nach wie viel Zeit?
  - Halte Mastery über 1 Woche?
```

### 5b. Metrik 2: Retention

**Def:** Erinnert sich Schüler das?

```
metric = percentage_correct(test_after_1_week)

Ziel: > 85%

Wie messen:
  - Nach 1 Woche: Test ohne Hints
  - Wie viele Konzepte noch beherrscht?
```

### 5c. Metrik 3: Transfer

**Def:** Kann Schüler das auf NEUEN Kontext anwenden?

```
metric = percentage_correct(new_context_task)

Ziel: > 70%

Wie messen:
  - Konzept X auf "original context" gelernt
  - Dann: Aufgabe in "neuer context" (z.B. neues Tragwerk-Szenario)
  - Kann Schüler transferieren?
```

### 5d. Metrik 4: Engagement

**Def:** Bleibt Schüler motiviert?

```
metric = session_completion_rate * avg_motivation_score

Ziel: > 0.8 (80% fertigmachen Sessions, Motivation bleibt high)

Wie messen:
  - Sitzungen, die komplett durchgearbeitet werden?
  - Self-reported motivation (1-5 scale)?
  - Return rate (kommt Schüler nächste Woche wieder)?
```

### 5e. Metrik 5: Equitable Learning

**Def:** Lernen alle Schüler-Typen?

```
Breakdown by learning_style:
  - Auditory students: median_mastery = 0.85?
  - Kinesthetic students: median_mastery = 0.85?
  - Visual students: median_mastery = 0.85?
  
Ziel: Alle gleich gut! (gap < 5%)

Wenn gap > 5%:
  → "Kinesthetic students lernen schlechter!"
  → Debug: Welche Hints/Feedback nicht optimal?
  → Rebuild Module für Kinesthetic
  → Remeasure
```

---

## 6. INFRASTRUKTUR FÜR MAXIMALES LERNEN

### 6a. Spaced Repetition (aus Neuroscience)

**These:** Gehirn braucht MEHRFACH-Exposure über Zeit

```
Optimale Timing (Ebbinghaus-Kurve):

Tag 1: Lerne Konzept X
  ↓ (24 Stunden)
Tag 2: Review X (wenn vergessen → -25% retention)
  ↓ (3 Tage)
Tag 5: Review X (refresh)
  ↓ (7 Tage)
Tag 12: Review X (noch sicherer)
  ↓ (21 Tage)
Tag 33: Review X (langfristige Speicherung)

System sollte AUTOMATISCH diese Timing steuern:
  - Student lernt Stäbe Tag 1
  - System erinnert am Tag 2 ("Hey, lass uns Stäbe nochmal ansehen")
  - Auch Tag 5, 12, 33
  - Mit spaced Repetition: Retention steigt von 50% → 90%
```

### 6b. Interleaving (aus Neuroscience)

**These:** Mixen von Konzepten macht Gehirn besser (statt Blocking)

```
SCHLECHT (Blocking):
  1. Stäbe: 10 Aufgaben Stäbe
  2. Lager: 10 Aufgaben Lager
  3. Bestimmtheit: 10 Aufgaben Bestimmtheit
  → Schüler verwechselt Konzepte später!

GUT (Interleaving):
  1. Aufgabe: Stab-Klassifizierung
  2. Aufgabe: Lager-Typ identifizieren
  3. Aufgabe: Bestimmtheit berechnen
  4. Aufgabe: Stab ODER Balken? (mixin!)
  5. Aufgabe: Neuer Lagertyp, erkenne ihn
  ...
  → Gehirn lernt Unterschiede!

System sollte:
  - Nicht reine "Stäbe-Blöcke", sondern mixed
  - Aber intelligent (kein totales Chaos)
  - "Spacing" + "Interleaving" = optimales Lernen
```

### 6c. Elaboration (aus Neuroscience)

**These:** Tiefer Processing → besseres Lernen

```
OBERFLÄCHLICH:
  "Stab überträgt nur Längskräfte"
  → Student merkt sich Satz

ELABORATIV:
  "Stab überträgt nur Längskräfte WARUM?
   → Momentengleichgewicht!
   → Praktisches Beispiel: Dachbinder-Strebe
   → Analogie: Wie Schaukelachse
   → Test dich selbst: Was würde passieren wenn...?"
  → Student versteht TIEFERGEHEND!

System sollte ELABORATION fördern:
  - Nicht nur Info geben, sondern erklären WARUM
  - Mehrere Perspektiven geben
  - Schüler fragen "Warum?" stellen
  - Transfer-Aufgaben geben
```

### 6d. Metacognition (aus Neuroscience)

**These:** Schüler muss über sein LERNEN nachdenken

```
Gutes Metacognition:
  "Ich habe diese Aufgabe falsch gemacht WEIL..."
  "Nächstes Mal muss ich..."
  "Mein Verständnis von X ist..."

System sollte:
  - Nach jeder Aufgabe fragen: "Wie machst du das?"
  - "Was war schwer?"
  - "Was brauchst du nächstes Mal?"
  - Schüler reflektieren → wird besser!
```

---

## 7. KONKRETE IMPLEMENTIERUNG (MVP)

### 7a. Die Infrastruktur JETZT bauen (für späteren Training)

```typescript
// backend/types/event.ts
interface InteractionEvent {
  student_id: string;
  session_id: string;
  timestamp: Date;
  
  // Task
  concept: string;
  task_id: string;
  task_difficulty: number;
  task_type: "classification" | "calculation" | "explanation";
  
  // Student state BEFORE
  student_state_before: {
    mastery: number;
    confidence: number;
    motivation: number;
    learning_style: "auditory" | "kinesthetic" | "visual";
    recent_correct: number;
    time_since_last_correct: number;
  };
  
  // Interaction
  response: string;
  time_taken: number;
  hint_requests: number;
  hint_levels: number[];
  
  // Outcome
  is_correct: boolean;
  misconception?: string;
  misconception_confidence?: number;
  
  // Feedback
  feedback_given: string;
  feedback_type: "task_level" | "process_level" | "regulation_level" | "self_level";
  
  // Next action
  next_action: "continue" | "advance" | "remediate" | "pause";
  
  // Student state AFTER
  student_state_after?: {
    mastery: number;
    confidence: number;
    motivation: number;
  };
}
```

```python
# backend/services/event_logger.py
class EventLogger:
    def log_interaction(self, event: InteractionEvent) -> None:
        """
        Log EVERY interaction for future training
        """
        # Store in DB
        db.interactions.insert(event.to_dict())
        
        # Also: Stream to analytics queue (for offline analysis)
        analytics_queue.publish({
            "event_id": event.id,
            "concept": event.concept,
            "outcome": "correct" if event.is_correct else "wrong",
            "misconception": event.misconception,
            "feedback_type": event.feedback_type,
        })
        
        # Later: This will feed neural network training!
```

### 7b. Spaced Repetition im MVP

```python
# backend/services/spacing_service.py
class SpacingService:
    def schedule_review(self, student_id: str, concept: str) -> datetime:
        """
        Calculate when to show this concept again
        Using Ebbinghaus curve: 1d, 3d, 7d, 21d, ...
        """
        last_interaction = db.interactions.find_last(
            student_id=student_id,
            concept=concept
        )
        
        if not last_interaction:
            return datetime.now()  # Show immediately
        
        num_correct_in_row = db.interactions.count_consecutive_correct(
            student_id=student_id,
            concept=concept
        )
        
        # After 3 correct: review after 1 day
        if num_correct_in_row >= 3:
            return last_interaction.timestamp + timedelta(days=1)
        
        # After 5 correct: review after 3 days
        if num_correct_in_row >= 5:
            return last_interaction.timestamp + timedelta(days=3)
        
        # After 7 correct: review after 7 days
        if num_correct_in_row >= 7:
            return last_interaction.timestamp + timedelta(days=7)
        
        # Otherwise: show next task now
        return datetime.now()
    
    def suggest_review_task(self, student_id: str) -> Task | None:
        """
        Find concept that's due for review
        """
        due_concepts = db.concepts.find_due_for_review(student_id)
        
        if not due_concepts:
            return None
        
        # Pick one (could be random, or based on forgetting curve)
        concept = due_concepts[0]
        
        # Return a review task for that concept
        return db.tasks.find_review_task(concept)
```

### 7c. Interleaving im MVP

```python
# backend/services/task_sequencer.py
class TaskSequencer:
    def get_next_task(self, student_id: str) -> Task:
        """
        Not pure "Stäbe block then Lager block"
        Instead: Mix concepts intelligently
        """
        student = db.students.find(student_id)
        
        # Get candidate concepts (where student is learning)
        learning_concepts = [
            c for c in student.active_concepts
            if student.mastery[c] < 0.8  # Not yet mastered
        ]
        
        # Get spacing-due concepts (review needed)
        due_concepts = db.concepts.find_due_for_review(student_id)
        
        # Mix them: 70% new learning, 30% review/spacing
        if random.random() < 0.7:
            # New learning: pick from learning_concepts
            concept = random.choice(learning_concepts)
        else:
            # Review/spacing: pick from due_concepts
            concept = random.choice(due_concepts or learning_concepts)
        
        # Find task: slightly harder than current mastery
        target_difficulty = student.mastery[concept] + 0.1
        task = db.tasks.find_closest_difficulty(
            concept=concept,
            target_difficulty=target_difficulty
        )
        
        return task
```

---

## 8. METRIKEN IM MVP

```python
# backend/analytics/metrics.py

def learning_speed(student_id: str, concept: str) -> float:
    """
    Time to mastery (80% correct)
    """
    events = db.interactions.find_all(
        student_id=student_id,
        concept=concept
    )
    
    correct_count = sum(1 for e in events if e.is_correct)
    time_to_mastery = None
    
    for i, event in enumerate(events):
        if sum(1 for e in events[:i+1] if e.is_correct) / (i+1) >= 0.8:
            time_to_mastery = event.timestamp - events[0].timestamp
            break
    
    return time_to_mastery.total_seconds() / 3600 if time_to_mastery else None


def retention(student_id: str, concept: str, days: int = 7) -> float:
    """
    What % does student remember after N days?
    """
    learning_events = db.interactions.find_all(
        student_id=student_id,
        concept=concept,
        timestamp__lt=datetime.now() - timedelta(days=days)
    )
    
    if not learning_events:
        return None
    
    last_learning = learning_events[-1]
    review_events = db.interactions.find_all(
        student_id=student_id,
        concept=concept,
        timestamp__gte=last_learning.timestamp + timedelta(days=days-1),
        timestamp__lte=last_learning.timestamp + timedelta(days=days+1)
    )
    
    if not review_events:
        return None
    
    correct_reviews = sum(1 for e in review_events if e.is_correct)
    return correct_reviews / len(review_events)


def misconception_detection_accuracy() -> float:
    """
    Of all detected misconceptions, how many were actually correct?
    (Precision of misconception classifier)
    """
    labeled_events = db.interactions.find_all(
        has_human_label=True
    )
    
    correct_detections = sum(
        1 for e in labeled_events
        if e.misconception == e.human_labeled_misconception
    )
    
    return correct_detections / len(labeled_events)


def engagement(student_id: str) -> float:
    """
    Session completion rate * avg motivation
    """
    sessions = db.sessions.find_all(student_id=student_id)
    completed = sum(1 for s in sessions if s.completed)
    
    avg_motivation = sum(
        s.student_state_after.motivation
        for s in sessions
    ) / len(sessions)
    
    return (completed / len(sessions)) * avg_motivation
```

---

## 9. ROADMAP: VOM MVP ZUM NEURAL NETWORK

```
PHASE 1 (4 Wochen - MVP):
  ├─ Rule-based Tutor (explizite Regeln)
  ├─ Event Logger (sammle ALLE Daten)
  ├─ Spaced Repetition (basic)
  ├─ Interleaving (random mix)
  └─ Metrics Dashboard (track learning_speed, retention)
  
  Output: 100-500 labeled events
  Goal: "System funktioniert, Victor lernt schneller"

PHASE 2 (8 Wochen):
  ├─ Offline Analysis (was funktioniert?)
  ├─ Rule Refinement (basierend auf Daten)
  ├─ Misconception DB erweitern (10+ Fehler pro Konzept)
  ├─ Feedback Library erweitern (mehr Variationen)
  └─ 10 Beta-Schüler testen
  
  Output: 5.000-10.000 labeled events
  Goal: "System macht Schüler 20% schneller"

PHASE 3 (12 Wochen):
  ├─ Automated Labeling (AI labels, Mensch reviews)
  ├─ Feature Engineering (statistischen Features aus Events)
  ├─ Erste ML-Modelle (Decision Trees, Random Forests)
  │  └─ Predict: is_correct, misconception, best_feedback
  ├─ A/B Test: Rule-based vs. ML-based
  └─ 100 Schüler in Beta
  
  Output: 50.000-100.000 labeled events
  Goal: "ML-System schlägt Rules in A/B Test"

PHASE 4 (2027 - Full Neural Network):
  ├─ Neural Network Design (Student + Task + Interaction Encoders)
  ├─ Training (mit 1.000.000+ Events)
  ├─ Hyperparameter Optimization
  ├─ Production Deployment
  └─ Continuous Learning (neuen Daten jeden Tag)
  
  Output: Echtes trainierbares System!
  Goal: "KI-Tutor schlägt alle Baselines"
```

---

## 10. ANTWORT AUF DEINE FRAGE: "WIE HOLE ICH MAXIMUM RAUS?"

### TL;DR: So optimierst du Schüler-Lernen

**1. SPACED REPETITION**
- Nicht: "Stäbe → done"
- Sondern: "Stäbe (Tag 1) → Review (Tag 2) → Review (Tag 5) → Review (Tag 12)"
- Retention steigt von 50% → 90%

**2. INTERLEAVING**
- Nicht: "10 Stab-Aufgaben hintereinander"
- Sondern: "Stab, dann Lager, dann Stab again, dann Bestimmtheit, etc."
- Gehirn lernt Unterschiede!

**3. ELABORATION**
- Nicht: "Ein Stab überträgt nur Längskräfte [Fact]"
- Sondern: "[Why?] Momentengleichgewicht! [Praktik] Dachbinder! [Analogie] Wie Schaukelachse!"
- Tiefer Processing!

**4. METACOGNITION**
- "Wie hast du das gelöst?"
- "Was war schwer?"
- "Was brauchst du nächstes Mal?"
- Schüler reflektiert → wird selbst zum Lehrer

**5. ADAPTIVE DIFFICULTY**
- Nicht: "Alle Schüler machen gleiche Aufgaben"
- Sondern: "Jeder Schüler: [Mastery + 0.1] Schwierigkeit"
- = Optimal Challenge (ZPD treffen!)

**6. IMMEDIATE FEEDBACK**
- Mit Fehlkonzept-Analyse (nicht nur "falsch!")
- Mit Process-Level (nicht nur Task-Level)
- Mit Motivation (Ermutigung!)

**7. TRACKING & ADAPTATION**
- Logge ALLES (für späteren Training)
- Erkenne Muster (Data-Driven!)
- Passe Regeln an (Continuous Improvement!)

**8. LANGFRISTIGE SPEICHERUNG**
- Review-Schedule
- Concept Interleaving
- Metriken: Learning Speed, Retention, Transfer, Engagement

---

## 11. KONKRETE TODO für MVP

```markdown
## TODO - PrivatTeacher MVP (Data-First)

### Backend Setup
- [ ] PostgreSQL Schema für InteractionEvent
- [ ] EventLogger Service (alles loggen)
- [ ] Spaced Repetition Calculator
- [ ] Task Sequencer (Interleaving)
- [ ] Metrics Dashboard

### Data Collection
- [ ] Victor macht 30 Aufgaben (5 Sessions á 6 Aufgaben)
- [ ] Jede Interaction: Auto-Logged
- [ ] Human Labels: Misconceptions, Feedback Quality
- [ ] Quality Check: Ist das Logging vollständig?

### Analysis & Insights
- [ ] Learning Speed: Wie schnell lernt Victor?
- [ ] Retention: Erinnert er sich nach 1 Woche?
- [ ] Misconception Accuracy: Wie gut erkennen wir Fehler?
- [ ] Feedback Effectiveness: Welcher Feedback-Typ best?

### First ML Models (Phase 2)
- [ ] Feature Engineering (aus Events)
- [ ] Decision Tree: Predict is_correct
- [ ] Decision Tree: Predict misconception
- [ ] Decision Tree: Predict best_feedback

### A/B Test (Phase 3)
- [ ] Rule-Based Version (alt)
- [ ] ML-Based Version (neu)
- [ ] Metrics: Learning Speed, Retention, Engagement
- [ ] Statistical Significance Test
```
