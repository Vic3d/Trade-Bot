# PrivatTeacher — KI-Tutoring-System (Core Engine für Human Resilience)

## Vision (Langfristig)

**PrivatTeacher ist nicht "nur Lernapp". Es ist die Core Learning Engine für ein größeres Ökosystem:**

> "Infrastruktur für Human Resilience in der AI Era"
>
> KI ersetzt Jobs. Menschen brauchen nicht Angst, sondern echte Umschulung.
> Nicht "Was solltest du werden?" sondern "Wer bist du WIRKLICH? Was passt zu deinen Stärken?"

**PrivatTeacher = Die optimale Lern-Engine**
- Neben dem Schüler "sitzt" (async + strukturiert)
- Schüler-Lerntypen anpasst (auditiv, kinästhetisch, visuell, kognitiv)
- Fehlkonzepte erkennt (nicht nur Antworten checken)
- Rhythmus anpasst (nicht zu schnell/langsam)
- Echtes Feedback gibt (nicht nur "richtig/falsch")
- **Spaced Repetition + Interleaving + Elaboration** (Science-based)
- **Daten sammelt für Neural Network Training** (Future-proof)

**Status:** Phase 0 ✅ ABGESCHLOSSEN (14.03.2026, 16:40)  
**Nächster Schritt:** Phase 1 — Referenzsysteme + MVP-Planung

---

## Phase 0: ✅ ERLEDIGT — Lernwissenschaft verstanden

**Outputs:**
1. **teaching-science-research.md** (4 KB)
   - Bloom's Taxonomy (Remember → Create)
   - Vygotsky's Zone of Proximal Development
   - Fehlkonzept-Didaktik (Misconception Theory)
   - Metacognition & Feedback-Wissenschaft
   - Multiple Representations
   - Adaptive Teaching & Intrinsic Motivation

2. **teacher-competencies.md** (12 KB) 
   - **7 Lehr-Kompetenzen katalogisiert:**
     - Fachkompetenz (Tiefe, Struktur, Grenzen)
     - Pädagogische Kompetenz (Design, Erklären, Fragen, Differenzieren)
     - **Diagnostische Kompetenz** (Vorwissen, Fehlkonzepte, ZPD) ← KRITISCH!
     - Interpersonale Kompetenz (Empathie, Geduld, Motivation) ← KI-Schwachpunkt
     - Reflektive Kompetenz (Selbst-Reflexion, Schüler-Reflexion)
     - Kulturelle Kompetenz (verschiedene Lernstile, Inklusion)
     - Technologische Kompetenz (sinnvoller Tech-Einsatz)
   - **Wahrheit:** KI kann Menschen-Lehrer nicht vollständig ersetzen
   - **Aber:** KI kann skalieren, personalisieren, konsistent sein

3. **ai-tutor-architecture.md** (27 KB) — TECHNISCHES SYSTEM-DESIGN
   - **Student Model** (Profil + Lerngeschichte)
   - **Domain Model** (Konzept-Netzwerk, Fehlkonzepte, Erklärungen, Aufgaben)
   - **Tutoring Engine** (6 Module: Diagnose, Scaffold, Feedback, Adaption, Sequencing, Motivation)
   - **Learning Sequencer** (Decision Tree für nächste Schritte)
   - **MVP Vision** (4 Wochen, nur 3 Konzepte)

## Phase 1: DATA-FIRST MVP (14.03 - 21.03) — DER PARADIGMENWECHSEL

**KERNIDEE (VOM TALK KLARGEWORDEN):**

Nicht "ein Tutor-System bauen und hoffen dass es funktioniert"  
Sondern **"eine Data-Infrastruktur bauen, die später echte neuronale Netzwerke trainiert"**

**Das ändert ALLES:**
- Nicht nur Regeln, sondern **Event Logging** von Anfang an
- Nicht nur "funktioniert", sondern **messbar besser** (Speed, Retention, Transfer)
- MVP jetzt → ML-Modelle (Phase 2) → echtes Neural Network (2027)

---

### 1. MVP-Fokus: Data Collection + Spaced Repetition + Interleaving

**Was wir JETZT bauen (4 Wochen):**

```
✅ Event Logger (ALLE Interaktionen tracken)
   └─ Student State (vorher/nachher)
   └─ Task Features
   └─ Response + Time + Hints
   └─ Outcome + Misconception + Feedback

✅ Spaced Repetition
   └─ Nicht "Stäbe → done", sondern "Tag 1, 2, 5, 12, 33"
   └─ Retention steigt von 50% → 90%

✅ Interleaving
   └─ Nicht "10 Stab-Aufgaben", sondern "Mix Stab/Lager/Bestimmtheit"
   └─ Gehirn lernt Unterschiede!

✅ Elaboration
   └─ "Warum?" + Praktik + Analogie (nicht nur Facts)

✅ Metacognition Prompts
   └─ "Wie hast du das gemacht?" nach jeder Aufgabe

✅ Metrics Dashboard
   └─ Learning Speed: Zeit bis Mastery?
   └─ Retention: Erinnert sich nach 1 Woche?
   └─ Transfer: Kann er auf Neues anwenden?
   └─ Engagement: Bleibt motiviert?
```

### 2. Für Victor: Die 4-Wochen-Case-Study

```
Week 1:
  - Victor: 30 Aufgaben (Stäbe, Lager, Bestimmtheit)
  - System: Logged ALLES
  - Metrics: Learning Speed, Retention nach 1 Woche

Week 2:
  - Victor: Review (Spaced Repetition)
  - System: Interleaving (mix Konzepte)
  - Metrics: Retention, Transfer

Week 3:
  - Analysis: Was funktioniert? Welche Fehlkonzepte häufig?
  - Victor: Targeted Remediation (gezielt schwache Punkte)

Week 4:
  - Victor: Mastery Check (80% correct?)
  - Metrics: Finale Learning Speed, Retention
  - Output: "Victor lernt 25% schneller mit KI-Tutor als klassisch"
```

### 3. Konkrete TODO

**Tech Stack (DATEN-FIRST):**
- [ ] PostgreSQL: InteractionEvent Schema (alles für Training vorbereitet)
- [ ] Backend: Python (scikit-learn, later TensorFlow)
- [ ] Event Logger: Real-time logging
- [ ] Metrics Dashboard: Live-Tracking

**MVP Features:**
- [ ] 3 Konzepte: Stäbe, Lager, Bestimmtheit
- [ ] 15-20 Aufgaben pro Konzept
- [ ] Fehlkonzepte: 5-10 pro Konzept
- [ ] Rule-Based Tutor (aber strukturiert für ML später)
- [ ] Spaced Repetition + Interleaving
- [ ] Event Logging + Metrics

**Testing mit Victor:**
- [ ] 30 Aufgaben durcharbeiten (5 Sessions)
- [ ] ALLES gelogged
- [ ] Nach 1 Woche: Retention Test
- [ ] Metrics sammeln

## Phase 2: MVP (4 Wochen)
- [ ] Kern-Engine bauen
- [ ] Mit TME102 testen
- [ ] Feedback-Loop einbauen

## Phase 3: Vermarktung (2027)
- Zielgruppe: Studierende, Schüler 16+
- B2C: €9-19/Monat
- B2B: Unis, Online-Schulen

---

## Zentrale Frage
**"Wie lehrt ein guter Privatlehrer?"**
Das müssen wir erst verstehen, bevor wir es automatisieren.

---

---

## KEY INSIGHTS (Mindshift: Rule-Based → Data-Driven)

### 🎯 Die zentrale Erkenntnis

**NICHT:** "Baue einen Tutor und hoffe es funktioniert"  
**SONDERN:** "Baue eine Data-Infrastruktur, die selbst lernfähig wird"

### 1. Paradigmenwechsel (MVP → Neural Network)

**MVP (jetzt):** Rule-Based Tutor
- Explizite Regeln: IF (falsch) THEN (Feedback)
- Funktioniert, aber nicht adaptiv

**Phase 2 (8 Wo):** ML-Modelle
- Decision Trees + Random Forests
- Lernen aus echten Schüler-Daten
- Bessere Vorhersagen als Rules

**Phase 3 (12 Wo):** Neural Networks
- 1.000.000+ Events trainiert
- Student + Task + Interaction Encoders
- A/B Test: "KI schlägt alle Baselines"

### 2. Was wir loggen (für späteren Training)

Nicht nur "richtig/falsch", sondern:
- 👤 Student State (Mastery, Confidence, Mood, Learning Style)
- 📋 Task Features (Difficulty, Type, Concept)
- ⏱️ Interaction Data (Time, Hints, Attempts)
- 🎯 Outcome (Correct? + Misconception?)
- 💬 Feedback Given (welcher Typ? wirksam?)
- ➡️ Next Action (welche Aufgabe nächste?)

**Mit 100.000+ Events:** Neural Network lernt echte Muster!

### 3. Neuroscience-basierte Optimierungen

**Spaced Repetition** (Ebbinghaus)
- Tag 1, 2, 5, 12, 33 Review statt "einmal done"
- Retention: 50% → 90%

**Interleaving**
- Mix Stäbe + Lager + Bestimmtheit
- Gehirn lernt Unterschiede!

**Elaboration**
- Nicht nur Fact, sondern WARUM + Analogie + Praxis
- Tiefer Processing!

**Metacognition**
- "Wie hast du das gemacht?"
- Schüler wird selbst zum Lehrer

### 4. Metriken (was optimieren wir?)

- **Learning Speed:** Zeit bis Mastery (80%) — Ziel: 30% schneller
- **Retention:** Erinnert sich nach 1 Woche? — Ziel: > 85%
- **Transfer:** Auf neuen Kontext anwendbar? — Ziel: > 70%
- **Engagement:** Motiviert bleiben? — Ziel: 80% completion
- **Equity:** Lernen ALLE Student-Typen gleich? — Ziel: Gap < 5%

### 5. Was KI NICHT kann (noch)

- Echte emotionale Empathie
- Spontane kreative Anpassung
- Echte menschliche Beziehung

### 6. Was KI sehr GUT kann

- Niemals ungeduldig sein
- Sofort verfügbar (24/7)
- Konsistent über 10.000+ Schüler
- Skalierbar + billig
- ALLE Fehler kennen (wenn trainiert)
- Objektivere Entscheidungen

### 7. BEST PRACTICE: Hybrid-Ansatz

**KI-Tutor:** Structure + Personalization + Patience  
**Menschlicher Mentor:** Inspiration + Guidance + Relationship  
**Zusammen:** Optimal!

---

## Notizen
- Victor könnte erste Case Study sein (TME102)
- Startpunkt: Statik (Stäbe, Lager, Bestimmtheit) — konkret, überschaubar
- MVP muss ECHTE Werte zeigen: "Schüler lernt schneller mit KI-Tutor als ohne"
