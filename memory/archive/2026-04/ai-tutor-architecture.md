# AI-TUTOR ARCHITECTURE — Wie man einen KI-Lehrer baut

## KERN-IDEE: Ein KI-Tutor ist kein Chatbot

**Chatbot:** "Frag mich Fragen, ich antworte"
- Passiv
- Reaktiv
- Keine Struktur

**KI-Tutor:** "Ich plane dein Lernen, erkenne Fehler, passe mich an"
- Aktiv (gibt Aufgaben)
- Proaktiv (gibt Hints BEVOR du fragst)
- Strukturiert (Curriculum + Adaptation)

---

## SYSTEM-ARCHITEKTUR (High-Level)

```
┌─────────────────────────────────────────────────────────┐
│                     AI TUTOR SYSTEM                     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │         SCHÜLER-PROFIL (Student Model)           │  │
│  │  ├─ Vorwissen                                     │  │
│  │  ├─ Lerntypen (auditiv/kinästhetisch/visuell)   │  │
│  │  ├─ Aktuelle Fähigkeiten (pro Konzept)          │  │
│  │  ├─ Fehlkonzepte (was denkt er falsch?)        │  │
│  │  ├─ ZPD-Level (was ist optimal?)                │  │
│  │  └─ Motivation/Engagement                        │  │
│  └──────────────────────────────────────────────────┘  │
│                          ↕                             │
│  ┌──────────────────────────────────────────────────┐  │
│  │      WISSENS-REPRÄSENTATION (Domain Model)       │  │
│  │  ├─ Konzept-Netzwerk (wie Konzepte zusammen)   │  │
│  │  ├─ Fehlkonzept-Datenbank (häufige Fehler)      │  │
│  │  ├─ Erklärungen (multiple Representationen)     │  │
│  │  ├─ Fragen (pro Bloom-Level)                    │  │
│  │  ├─ Aufgaben (verschiedene Schwierigkeiten)     │  │
│  │  └─ Lernpfade (Reihenfolge der Konzepte)        │  │
│  └──────────────────────────────────────────────────┘  │
│                          ↕                             │
│  ┌──────────────────────────────────────────────────┐  │
│  │    TUTORING ENGINE (Die eigentliche KI)         │  │
│  │  ├─ Diagnose-Modul (Was versteht der Schüler?) │  │
│  │  ├─ Scaffold-Modul (Gib richtige Hints)         │  │
│  │  ├─ Feedback-Modul (Task/Process/Regulation)    │  │
│  │  ├─ Adaption-Modul (Schwierigkeit anpassen)     │  │
│  │  ├─ Motivation-Modul (Keep engaged)             │  │
│  │  └─ Reflection-Modul (Bring zum Nachdenken)     │  │
│  └──────────────────────────────────────────────────┘  │
│                          ↕                             │
│  ┌──────────────────────────────────────────────────┐  │
│  │         LERNKONTROLLE (Learning Sequences)        │  │
│  │  ├─ Welche Aufgabe als nächste?                 │  │
│  │  ├─ Wann Hints geben?                            │  │
│  │  ├─ Wann Schwierigkeit ändern?                   │  │
│  │  └─ Wann zum nächsten Konzept?                   │  │
│  └──────────────────────────────────────────────────┘  │
│                          ↕                             │
│  ┌──────────────────────────────────────────────────┐  │
│  │           INTERFACE (was Schüler sieht)          │  │
│  │  ├─ Aufgaben-Präsentation                        │  │
│  │  ├─ Hint-Mechaniken                              │  │
│  │  ├─ Feedback-Display                             │  │
│  │  ├─ Progress-Visualisierung                      │  │
│  │  └─ Motivation-Messages                          │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 1. SCHÜLER-PROFIL (Student Model) — Detailliert

### 1a. Was muss das System über den Schüler WISSEN?

```python
@dataclass
class StudentProfile:
    # Demographie
    name: str
    level: str  # "Anfänger", "Fortgeschritten", "Experte"
    subject: str  # "Statik", "Mathe", etc.
    
    # LERNTYPEN
    learning_style: {
        "auditiv": 0.6,      # 60% → Audio bevorzugt
        "visuell": 0.8,      # 80% → Grafiken wichtig
        "kinästhetisch": 0.9  # 90% → Anfassen wichtig
    }
    
    # VORWISSEN (basierend auf Placement Test)
    prerequisites: {
        "Vektorrechnung": 0.8,      # 80% verstanden
        "Kräfte": 0.7,
        "Momentengleichgewicht": 0.5  # schwach!
    }
    
    # AKTUELLE FÄHIGKEITEN (Pro Konzept)
    # Belief State: "Wie wahrscheinlich versteht Schüler X?"
    competencies: {
        "Stäbe": {
            "mastery": 0.3,  # 30% gemeistert
            "confidence": 0.6,  # 60% sicher, dass Schüler versteht
            "misconceptions": ["Querkräfte übertragbar", "Balken = Stab"],
            "last_tested": "2026-03-14 15:00"
        },
        "Lager": {
            "mastery": 0.5,
            "confidence": 0.7,
            "misconceptions": ["Lager macht Kraft", "Mehr Lager = stabiler"],
            "last_tested": "2026-03-14 14:00"
        },
        # ... mehr Konzepte
    }
    
    # ZPD-LEVEL (Where should we pitch difficulty?)
    zpd_level: {
        "Stäbe": "EXPLAIN_MORE",     # Zu einfach → erklär mehr
        "Lager": "JUST_RIGHT",       # Perfect Zone
        "Fachwerke": "TOO_HARD"      # Zu schwer → wait
    }
    
    # MOTIVATIONS-STATE
    motivation: {
        "intrinsic": 0.7,    # Schüler will was lernen
        "extrinsic": 0.3,    # Externe Belohnung
        "engagement": 0.6,   # Aktiv beteiligt?
        "frustration_level": 0.3,  # Wie frustriert? (0=entspannt, 1=verzweifelt)
        "recent_success": True  # Letzte Aufgabe erfolgreich?
    }
    
    # LERNGESCHICHTE (für Reflection)
    learning_history: [
        {
            "date": "2026-03-14 15:00",
            "concept": "Stäbe",
            "task": "Ist Teil X ein Stab?",
            "result": "WRONG",
            "time_taken": 120,  # Sekunden
            "misconception_detected": "Denkt Querkräfte sind OK",
            "feedback_given": "Task Level"
        },
        # ... mehr History
    ]
    
    # VERTRÄGE (was Schüler sich selbst versprochen hat)
    goals: [
        {"by": "2026-03-21", "goal": "Fachwerke verstehen"},
        {"by": "2026-04-04", "goal": "TME102-Prüfung bestehen"}
    ]
```

**Warum so detailliert?**
- Damit die KI PERSONALISIERT anpassen kann
- Nicht "alle Schüler sind gleich"
- Jede Entscheidung basiert auf DIESEM Profil

---

### 1b. Wie aktualisiert sich das Profil?

**Ständig! Nach jeder Interaktion.**

```
1. Schüler beantwortet Aufgabe
   ↓
2. Diagnose-Modul analysiert Antwort
   ├─ "Ist die Antwort richtig?"
   ├─ "Hat Schüler die Methode verstanden?"
   ├─ "Welche Fehlkonzepte sehe ich?"
   └─ "Wie schnell hat er geantwortet?"
   ↓
3. Student Model aktualisiert sich
   ├─ competencies["Stäbe"]["mastery"] += 0.1 (if correct)
   ├─ competencies["Stäbe"]["misconceptions"] ← neu entdeckt
   ├─ zpd_level["Stäbe"] ← neu berechnet
   └─ motivation["frustration_level"] ← erhöht wenn viele Fehler
   ↓
4. Learning Sequences entscheidet nächsten Schritt
   ├─ Aufgabe zu leicht? → Schwierigkeit erhöhen
   ├─ Aufgabe zu schwer? → Zurück zu Basics
   ├─ Fehlkonzept erkannt? → Spezielles Feedback
   └─ Zu frustiert? → Pause + Ermutigung
```

---

## 2. WISSENS-REPRÄSENTATION (Domain Model) — Statik als Beispiel

### 2a. Konzept-Netzwerk

**Nicht isolierte Facts, sondern Netzwerk:**

```
                 ┌─ Stäbe
                 │  └─ Stabkräfte (Zug/Druck)
                 │     └─ Fachwerke
                 │
Freiheitsgrade ─┼─ Lager
                 │  ├─ Lagertypen
                 │  └─ Lagerreaktionen
                 │     └─ Bestimmtheit
                 │
                 └─ Balken
                    ├─ Biegung
                    └─ Schnittgrößen

Verbindungen:
- "Fachwerk braucht Stab-Konzept"
- "Bestimmtheit braucht Lagertypen"
- "Balken = Erweiterung von Stab"
```

**Wichtig:** System WEIDET, welche Konzepte zusammenhängen!

Wenn Schüler Stäbe nicht versteht → "Du brauchst aber Freikörperbild zuerst"

### 2b. Fehlkonzept-Datenbank

**Für JEDES Konzept: Liste von Fehlkonzepten**

```python
misconceptions = {
    "Stäbe": [
        {
            "name": "Querkräfte übertragbar",
            "description": "Schüler denkt, ein Stab kann auch Querkräfte übertragen",
            "why": "Verwechselt mit Balken, oder versteht Momentengleichgewicht nicht",
            "how_to_detect": [
                "Antwortet: 'Ein Stab mit seitlicher Last ist OK'",
                "Zeichnet Querkräfte in Freikörperbild des Stabes",
                "Rechnet mit Querkraft-Komponenten für Stab"
            ],
            "how_to_fix": [
                {
                    "name": "Momentengleichgewicht-Weg",
                    "text": "M_E: CH × l = 0. Warum muss CH = 0 sein?",
                    "level": "conceptual"
                },
                {
                    "name": "Vergleichs-Weg",
                    "text": "Vergleiche Stab (nur Längskraft) mit Balken (beliebige Kräfte)",
                    "level": "analogical"
                },
                {
                    "name": "Praktischer Weg",
                    "text": "Denk an echte Dachbinder-Strebe: Drückt/zieht nur längs",
                    "level": "concrete"
                }
            ],
            "prevention": "Bevor Schüler Fachwerke tut: Übe Stab-Konzept 5x"
        },
        # ... mehr Fehlkonzepte
    ],
    # ... mehr Konzepte
}
```

**Warum so wichtig?**
- Nicht "Schüler hat Fehler gemacht" (generic)
- Sondern "Schüler hat Fehlkonzept X" (spezifisch)
- → Jeder Fehlkonzept hat speziellen Fix!

### 2c. Erklärungen (Multiple Representations)

**NICHT eine Erklärung, sondern viele!**

```python
explanations = {
    "Warum_Stab_nur_Längskräfte": [
        {
            "type": "verbal",
            "learning_style": ["auditiv"],
            "level": 1,  # Bloom: Remember
            "text": """
            Ein Stab ist an beiden Enden gelenkig.
            Kräfte greifen nur an Gelenken an (nicht über Länge).
            Deswegen: Nur Längskräfte!
            """
        },
        {
            "type": "visual_freebody",
            "learning_style": ["visuell"],
            "level": 2,  # Bloom: Understand
            "image": "stab_freebody.png",
            "explanation": """
            Schau Gelenk E. Es gibt CH und CV.
            Moment um E: CH × l = 0
            Da l ≠ 0: CH = 0!
            """
        },
        {
            "type": "numerical",
            "learning_style": ["auditiv", "visuell"],
            "level": 2,
            "example": """
            Stab, Länge 2m.
            CH = 10 kN, CV = 0 (angenommen)
            M_E = 10 × 2 = 20 kNm ≠ 0 ← NICHT im Gleichgewicht!
            
            Also: CH muss 0 sein!
            """
        },
        {
            "type": "kinesthetic",
            "learning_style": ["kinästhetisch"],
            "level": 2,
            "task": "Zeichne einen Stab. Mark Gelenke rot. Zeichne Kräfte. Was heben sich auf?"
        },
        {
            "type": "analogy",
            "learning_style": ["auditiv", "visuell"],
            "level": 3,
            "analogy": """
            Das ist wie eine Schaukel mit Gelenkachse.
            Du kannst die Schaukel heben/senken (Längskraft).
            Aber wenn du seitlich drückst (Querkraft):
            Die Gelenkachse muss compensieren → wird irgendwann kaputt!
            """
        },
        {
            "type": "historical",
            "learning_style": ["auditiv"],
            "level": 4,
            "text": """
            Die Annahme "Stab nur Längskraft" ist eine IDEALISIERUNG.
            In der Realität (mit Eigengewicht): nicht ganz wahr.
            Aber: Die Annahme macht Berechnung einfach und ist meist präzise genug.
            So funktioniert Ingenieurwerk: Idealisieren, berechnen, überprüfen.
            """
        }
    ],
    # ... mehr Konzepte
}
```

**Warum so viele?**
- Nicht alle Schüler verstehen die gleiche Erklärung!
- Auditiver Schüler: Verbal + Analogy
- Visueller Schüler: Grafik + Numerisch
- Kinästhetischer Schüler: "Zeichne selbst!"

### 2d. Fragen (Pro Bloom-Level)

```python
questions = {
    "Stäbe": {
        1: [  # Bloom Level 1: Remember
            "Was ist ein Stab?",
            "Ein Stab ist an seinen Enden ___ verbunden",
            "Wo greifen Kräfte an einem Stab an?"
        ],
        2: [  # Bloom Level 2: Understand
            "Warum überträgt ein Stab nur Längskräfte?",
            "Erkläre mit Momentengleichgewicht, warum CH = 0 sein muss",
            "Welcher Unterschied ist es zwischen Stab und Balken?"
        ],
        3: [  # Bloom Level 3: Apply
            "Ist Teil X in diesem Tragwerk ein Stab oder Balken?",
            "Berechne die Stabkraft mit Knotenpunktverfahren",
            "Erkenne die Stäbe im gegebenen Fachwerk"
        ],
        4: [  # Bloom Level 4: Analyze
            "Warum ist der erste Momentenpunkt schlecht gewählt?",
            "Was würde passieren, wenn dieser Stab nicht gelenkig wäre?",
            "Warum braucht ein Fachwerk nur Stäbe, keine Balken?"
        ],
        5: [  # Bloom Level 5: Evaluate
            "Ist diese Idealisierung (nur Längskraft) in der Realität gültig?",
            "Wann würde die Annahme 'Stab' scheitern?",
            "Wie könnte man das realistischer modellieren?"
        ],
        6: [  # Bloom Level 6: Create
            "Erfinde ein Tragwerk, das nur Stäbe braucht",
            "Wie würde man ein Fachwerk für ein 10-stöckiges Gebäude entwerfen?",
            "Schreib einen Beweis: Warum muss ein Stab Längskraft sein?"
        ]
    },
    # ... mehr Konzepte
}
```

**Wichtig:** System stellt nicht zufällige Fragen, sondern:
- **Anfangs:** Level 1 (erinnern)
- **Fortschritt:** Level 2-3 (verstehen + anwenden)
- **Experte:** Level 4-6 (analysieren + bewerten + erstellen)

### 2e. Aufgaben (verschiedene Schwierigkeiten)

```python
tasks = {
    "Stabklassifizierung": [
        {
            "difficulty": 1,
            "scenario": "Einfach: Balken mit 2 Gelenken, keine Lasten → IST DAS EIN STAB?",
            "hints": ["Sind beide Enden gelenkig?", "Gibt es Lasten über Länge?"],
            "solution": "Ja, das ist ein Stab",
            "expected_time": 120,  # seconds
            "misconceptions_tested": ["Querkräfte übertragbar"]
        },
        {
            "difficulty": 2,
            "scenario": "Mittel: Tragwerk mit Balken + Stab. Welche Teile sind Stäbe?",
            "hints": ["Zähle: Wie viele Gelenke hat jeder Teil?", "Gibt es Kräfte dazwischen?"],
            "solution": "Teile A und C sind Stäbe, B ist Balken",
            "expected_time": 240,
            "misconceptions_tested": ["Stab ≠ Balken", "Gelenkig ≠ notwendig"]
        },
        {
            "difficulty": 3,
            "scenario": "Schwer: Komplexes Fachwerk. Sind alle Teile Stäbe? Falls nein: warum?",
            "hints": ["Schau genau: Sind ALLE gelenkig?", "Gibt es Kräfte zwischen Gelenken?"],
            "solution": "Die meisten sind Stäbe, aber Teil X ist Balken weil...",
            "expected_time": 480,
            "misconceptions_tested": ["Alle Fachwerk-Teile sind Stäbe (falsch!)", "Definition von Stab"]
        }
    ],
    # ... mehr Aufgaben
}
```

---

## 3. TUTORING ENGINE — Die Intelligenz

### 3a. Diagnose-Modul

**Input:** Schüler-Antwort (Text, Bild, Formel)  
**Output:** Was versteht Schüler wirklich?

```python
def diagnose(student_answer, expected_answer, concept):
    """
    Nutzt NLP + Fehlkonzept-Matching um WARUM der Fehler auftrat
    """
    
    # Schritt 1: Ist Antwort richtig/falsch?
    correctness = evaluate_answer(student_answer, expected_answer)
    # → "WRONG", "PARTIALLY_CORRECT", "CORRECT"
    
    # Schritt 2: Warum war Antwort falsch?
    if correctness != "CORRECT":
        # Passt Antwort zu bekannten Fehlkonzepten?
        detected_misconceptions = []
        for misconception in misconceptions[concept]:
            similarity = nlp_match(student_answer, misconception)
            if similarity > 0.7:
                detected_misconceptions.append(misconception)
        
        # Falls nicht: neues Fehlkonzept!
        if not detected_misconceptions:
            new_misconception = generate_hypothesis(student_answer)
            # → Speichern für später
    
    # Schritt 3: Auf welchem Bloom-Level ist Antwort?
    bloom_level = assess_bloom_level(student_answer)
    # → 1-6
    
    # Schritt 4: Wie selbstbewusst war der Schüler?
    confidence = estimate_confidence(student_answer, time_taken)
    # → 0-1
    
    # Schritt 5: Diagnosis-Report
    return {
        "correctness": correctness,
        "misconceptions": detected_misconceptions,
        "bloom_level": bloom_level,
        "confidence": confidence,
        "interpretation": "Schüler versteht Konzept X, aber hat Fehlkonzept Y"
    }
```

### 3b. Scaffold-Modul (Hints)

**Nicht "Sag mir die Lösung!" sondern "Gib mir einen Hint!"**

```python
def provide_hint(student_state, misconception=None, zpd_level=None):
    """
    Gib den RICHTIGEN Hint zum RICHTIGEN ZEITPUNKT
    """
    
    # Hint-Strategie basierend auf Situation
    if misconception:
        # Schüler hat spezifisches Fehlkonzept
        fixes = misconceptions[concept].how_to_fix
        best_fix = select_by_learning_style(fixes, student.learning_style)
        return hint_from_fix(best_fix)
    
    elif zpd_level == "TOO_EASY":
        # Schüler ist unter-herausgefordert
        return "Challenge: Versuch das genereller zu lösen..."
    
    elif zpd_level == "TOO_HARD":
        # Schüler ist über-herausgefordert
        # Gib Interim-Schritt
        return "Schritt 1: Berechne erst die Lagerkräfte..."
    
    elif zpd_level == "JUST_RIGHT":
        # Schüler ist im Flow, aber steckt fest
        # Gib minimalen Hint
        return "Denk an: Welcher Momentenpunkt eliminiert Unbekannte?"
    
    # Hint-Strategie: Stufen-weise (Schüler entscheidet)
    hint_levels = [
        "Minimal Hint",      # Level 1: Nur Frage
        "Thought Hint",      # Level 2: Richtung geben
        "Formal Hint",       # Level 3: Formal helfen
        "Solution Start",    # Level 4: Erste Schritte
        "Full Solution"      # Level 5: Komplette Lösung (avoid!)
    ]
    
    return hint_levels[student.hint_request_count % len(hint_levels)]
```

### 3c. Feedback-Modul

**Gutes Feedback: Nicht "Falsch!", sondern strukturiert**

```python
def provide_feedback(student_answer, correct_answer, diagnosis):
    """
    Feedback nach Hattie's Struktur: Task/Process/Self-Regulation/Self
    """
    
    feedback = []
    
    # TASK LEVEL: Was ist konkret falsch?
    if diagnosis.correctness == "WRONG":
        task_error = identify_task_level_error(student_answer, correct_answer)
        feedback.append(f"❌ Task: {task_error}")
        # Z.B.: "Dein Freikörperbild hat Lagerkraft B in die falsche Richtung"
    else:
        feedback.append(f"✅ Task: Aufgabe korrekt gelöst!")
    
    # PROCESS LEVEL: Wie/Warum Fehler?
    if diagnosis.misconceptions:
        for misconception in diagnosis.misconceptions:
            process_error = explain_misconception(misconception)
            feedback.append(f"⚠️ Process: {process_error}")
            # Z.B.: "Du denkst, Lagerreaktion = äußere Last. Das ist falsch!"
            # Gib best fix:
            feedback.append(f"   💡 Fix: {misconception.fix}")
    
    # SELF-REGULATION LEVEL: Wie könnte Schüler es besser machen?
    strategy = suggest_strategy(diagnosis)
    feedback.append(f"🎯 Strategie für nächstes Mal: {strategy}")
    # Z.B.: "Schreib ERST alle Unbekannten auf, dann wähle Momentenpunkt"
    
    # SELF LEVEL: Ermutigung + Progress
    if diagnosis.correctness == "CORRECT":
        progress = compare_to_history(student_id, concept)
        feedback.append(f"🎉 Progress: {progress}")
        # Z.B.: "Das ist dein 3. richtiges Freikörperbild! Du machst Fortschritt!"
    else:
        feedback.append(f"💪 Versuch: Das ist eine schwere Konzept. Bleib dran!")
    
    return feedback
```

**Beispiel-Output:**
```
❌ Task: Deine horizontale Lagerkraft AH ist falsch. Du hast +5 kN, sollte -5 kN sein.

⚠️ Process: Du hast das Moment um den falschen Punkt berechnet. Das macht die Gleichung zu kompliziert!
   💡 Fix: Wähle einen Momentenpunkt, wo die UNbekannten durchgehen → sie eliminieren sich!

🎯 Strategie für nächstes Mal: 
   1. Markiere alle 3 Unbekannten (AH, AV, B)
   2. Schau wo sie greifen an
   3. Wähle Momentenpunkt wo 2 davon durchgehen
   4. DANN rechnen

💪 Versuch: Lagerreaktionen ist knifflig. Letzte Woche konntest du das noch nicht. 
   Du machst Fortschritt! 🚀
```

---

## 4. LERNKONTROLLE (Learning Sequences)

**Wer entscheidet, was als nächstes passiert?**

```python
class LearningSequencer:
    def get_next_step(self, student_profile, current_concept):
        """
        Entscheidet ADAPTIV, was der nächste Schritt ist
        """
        
        # Analyse: Wie gut versteht Schüler aktuelles Konzept?
        mastery = student_profile.competencies[current_concept]["mastery"]
        confidence = student_profile.competencies[current_concept]["confidence"]
        misconceptions = student_profile.competencies[current_concept]["misconceptions"]
        
        # DECISION TREE
        
        if confidence < 0.3:
            # System ist sich UNSICHER, ob Schüler versteht
            return "EXPLAIN_AGAIN", {
                "representation": "andere Erklärungsweise",
                "level": "verbal→visual→kinesthetic"
            }
        
        elif misconceptions and confidence > 0.3:
            # System erkennt FALSCHES Verständnis
            return "REMEDIATE", {
                "target_misconception": misconceptions[0],
                "method": "spezifischer Fix",
                "tasks": 3  # Gib 3 Tasks zum Fehlkonzept
            }
        
        elif mastery < 0.5 and confidence > 0.6:
            # Schüler versteht, aber braucht MEHR ÜBUNG
            return "PRACTICE", {
                "difficulty": "SAME",
                "num_tasks": 5,
                "variation": "verschiedene Szenarien"
            }
        
        elif mastery > 0.8 and confidence > 0.8:
            # Schüler beherrscht Konzept
            # Geh zu nächstem Konzept?
            next_concept = get_next_in_curriculum(current_concept)
            
            if prerequisite_satisfied(next_concept):
                return "ADVANCE", {
                    "new_concept": next_concept,
                    "introduction": "brief"
                }
            else:
                return "CHALLENGE", {
                    "difficulty": "HARDER",
                    "synthesis": "kombiniere mehrere Konzepte"
                }
        
        elif mastery > 0.5 and mastery < 0.8:
            # Schüler ist mittelmäßig
            return "CONSOLIDATE", {
                "difficulty": "SLIGHTLY_HARDER",
                "type": "application_tasks",
                "hints_available": True
            }
        
        # MOTIVATION CHECK
        if student_profile.motivation["frustration_level"] > 0.8:
            # Zu frustriert!
            return "PAUSE", {
                "message": "Du machst Fortschritt! Lass uns eine Minute pausieren.",
                "show_progress": True
            }
        
        if student_profile.motivation["engagement"] < 0.3:
            # Zu gelangweilt!
            return "CHALLENGE", {
                "difficulty": "MUCH_HARDER"
            }
        
        return "CONTINUE", {
            "same_concept": True,
            "next_task": "select_appropriate_difficulty"
        }
```

---

## 5. MODUL-ZUSAMMENFASSUNG (TL;DR)

| Modul | Aufgabe | Input | Output |
|-------|---------|-------|--------|
| **Diagnose** | Was versteht Schüler? | Antwort + erwartete Antwort | Correctness + Fehlkonzept + Bloom-Level |
| **Scaffold** | Gib Hint | Schüler-State + Fehlkonzept | Passender Hint (Stufe 1-5) |
| **Feedback** | Strukturiertes Feedback | Diagnose | Task/Process/Regulation/Self Feedback |
| **Adaption** | Schwierigkeit anpassen | Mastery + Confidence | Nächste Aufgabe-Schwierigkeit |
| **Motivation** | Keep engaged | Frustration + Engagement | Motivational Messages |
| **Sequencing** | Entscheide nächsten Schritt | Alle vorherigen | Advance/Practice/Remediate/Challenge/Pause |

---

## 6. WAS BRAUCHT MAN ZUM BAUEN?

### 6a. Data
- ✅ Fachliches Wissen (für jedes Fach)
- ✅ Fehlkonzept-Datenbank (häufige Fehler)
- ✅ Erklärungen in mehreren Stilen
- ✅ Fragen pro Bloom-Level
- ✅ Aufgaben verschiedener Schwierigkeiten

### 6b. Algorithmen
- ✅ Diagnostic Classifiers (Fehlkonzept-Erkennung)
- ✅ Personalized Sequencing (nächste Aufgabe)
- ✅ Hint Selection (richtiger Hint zur richtigen Zeit)
- ✅ Adaptive Difficulty (Schwierigkeit anpassen)
- ✅ Mastery Estimation (wie gut versteht Schüler?)

### 6c. Tech
- ✅ LLM (Claude für Erklärungen, Feedback, Diagnose)
- ✅ Vector DB (Embeddings für Konzept-Matching)
- ✅ Rule Engine (Entscheidungslogik)
- ✅ Student Model (Datenspeicherung)
- ✅ Frontend (Interface für Schüler)

### 6d. Iterationen
- ✅ Beta-Test mit echten Schülern
- ✅ Messung: Lernen sie wirklich?
- ✅ Feedback-Loop: Was funktioniert, was nicht?
- ✅ Verbesserung: Fehlkonzepte hinzufügen, Feedback verfeinern

---

## 7. MVP VISION (4 Wochen)

**Start KLEIN. Nur essenzielle Module:**

```
MVP für TME102 (Statik):

✅ Konzepte: Stäbe, Lager, Bestimmtheit (3 Konzepte)
✅ Aufgaben: 10-15 Aufgaben pro Konzept
✅ Fehlkonzepte: 5-10 häufige Fehler pro Konzept
✅ Erklärungen: 2-3 Darstellungen pro Konzept

MODUL 1 (Diagnose): 
  - Erkenne Richtig/Falsch
  - Erkenne 3-5 häufige Fehlkonzepte
  
MODUL 2 (Feedback): 
  - Task Level + Process Level (nicht Regulation/Self)
  
MODUL 3 (Scaffold): 
  - 2 Hint-Level (Minimal, Formal)
  
MODUL 4 (Sequencing): 
  - "Nächste Aufgabe is similar difficulty" oder "Harder" oder "Easier"
  
MODUL 5 (Motivation): 
  - Nur Basis-Messages ("Du machst Fortschritt")

Schnittstelle:
  - Next.js Frontend (Text-Input + Bilder hochladen)
  - Claude API Backend (Diagnose, Feedback)
  - PostgreSQL (Student Profiles, Aufgaben)

TEST mit Victor:
  - Macht 30 Aufgaben durch
  - Geben Feedback: Was funktioniert? Was nervt?
  - Iterieren!
```

---

## 8. LANGE VISION (2027+)

**Wenn MVP funktioniert: Erweitern zu:**

```
Phase 2:
  ✅ Video-Erklärungen
  ✅ Simulationen (interaktive Tragwerke)
  ✅ Handschrift-Erkennung (Schüler zeichnet, AI erkennt)
  
Phase 3:
  ✅ Multi-Subject (nicht nur Statik, sondern komplette Technische Mechanik)
  ✅ Social Features (Schüler können sich vergleichen, Gruppen)
  ✅ Teacher Dashboard (Lehrerinnen können Schüler-Progress sehen)
  
Phase 4:
  ✅ Proctored Exams (AI überwacht Prüfungen)
  ✅ Certification (Offizielle Zertifikate)
  ✅ Integration mit Unis (AKAD, FernUni, etc.)
  
BUSINESS MODEL:
  - B2C: €9/Monat (Schüler)
  - B2B: €0.50-1.00 pro Schüler/Monat (Unis)
  - B2G: Government Training
  - Enterprise: Firmen-Trainings
```

Geschätzte Marktgröße (weltweit):
- 500M Schüler × €0.50 = $250M potential (B2C)
- 1000 Unis × 5000 Schüler × €1 = $5B potential (B2B)
