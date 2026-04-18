# PrivatTeacher — Anforderungskatalog

## MODUL 1: Diagnose (Student Modeling)

**Input:** Schüler schreibt Antwort oder Lösung  
**Output:** System versteht:
- ✅ Was der Schüler kann
- ❌ Was der Schüler nicht kann
- 🔴 Welche falschen Konzepte hat der Schüler?
- 📊 Verständnis-Level nach Bloom (1-6)

**Beispiel:**
```
Input: "Ein statisch unbestimmtes System ist beweglich"
AI erkennt: 
  ❌ FALSCH (Level 1: Remember)
  🔴 Fehlkonzept: "Unbestimmt = beweglich"
  → Richtig wäre: "Unbestimmt = starr ABER überbestimmt"
```

**Tech:** NLP + Concept Mapping + Error Database

---

## MODUL 2: Adaptive Scaffolding (Hints & Guidance)

**Input:** Schüler steckt fest  
**Output:** Passende Hilfe basierend auf:
- 📊 Wo steckt der Schüler? (ZPD-Level)
- 🧠 Sein Lerntyp (auditiv/kinästhetisch/visuell)
- 🔴 Sein Fehlkonzept (nicht Zufalls-Hint!)

**Scaffolding-Stufen (progressiv):**

```
Stufe 1 (Minimal): Frage stellen
  "Schau dir nochmal an: Was ist ein Stab?"

Stufe 2 (Gedanken-Hint): Richtung geben
  "Denk an Momentengleichgewicht am Gelenk"

Stufe 3 (Formalhint): Formal helfen
  "M_E: CH × l = 0. Was muss CH sein?"

Stufe 4 (Lösung-Anfang): Erste Schritte zeigen
  "Berechne erst die Lagerkräfte mit ΣM_A = 0"

Stufe 5 (Volle Lösung): Komplette Lösung + Erklärung
  (nur im Notfall!)
```

**Schüler wählt Stufe:** "Ich brauch einen Hint" → System gibt Stufe 1 → Schüler versucht → "Noch nicht verstanden" → Stufe 2

---

## MODUL 3: Fehlkonzept-Datenbank

**Was:** Ein System kennt für jedes Thema:
- ✅ Richtige Konzepte
- 🔴 Häufige falsche Konzepte
- 📝 Warum Schüler das falsch machen
- 🔧 Wie man es richtig macht

**Beispiel für Statik:**

```
Konzept: "Statische Bestimmtheit"

❌ Fehlkonzept 1: "f=0 bedeutet unbewegt"
   Realität: f=0 bedeutet "lösbar mit Gleichgewicht"
   Grund: Schüler verwechselt "Bestimmtheit" mit "Bewegung"
   Fix: Formel zeigen + Beispiel mit beweglichem System (f>0)

❌ Fehlkonzept 2: "Mehr Lager = besser"
   Realität: Mehr Lager kann PROBLEMATISCH sein (unbestimmt)
   Grund: Schüler denkt "Mehr Halt = stabiler"
   Fix: Temperatur-Beispiel (Dehnung → Spannungen)

❌ Fehlkonzept 3: "Gelenkträger = Fachwerk"
   Realität: Gelenkträger = Balken mit Gelenken
   Grund: Beide haben Gelenke, aber unterschiedlich
   Fix: Vergleich-Tabelle
```

---

## MODUL 4: Multiple Representations (Verschiedene Erklärungen)

**Input:** Schüler versteht NICHT  
**Output:** Andere Erklärungsweise

**Für jeden Konzept 3+ Darstellungen:**

```
KONZEPT: "Stab überträgt nur Längskräfte"

Representation 1 (Verbal):
  "Ein Stab ist an beiden Enden gelenkig. 
   Momentengleichgewicht zeigt: Querkräfte heben sich auf."

Representation 2 (Grafik):
  Freikörperbild mit Momenten um beide Gelenke

Representation 3 (Numerisch):
  "CH × 2m = 0 → CH = 0"

Representation 4 (Kinästhetisch):
  "Zeichne selbst einen Stab, markiere Kräfte"

Representation 5 (Beispiel):
  "Dachbinder-Strebe: Drückt oben, zieht unten = NUR Längskraft"
```

System merkt: "Schüler versteht Representation 1 nicht" → versucht 2, 3, 4, 5

---

## MODUL 5: Metacognitive Prompting (Selbst-Reflexion)

**Input:** Schüler hat Aufgabe gelöst  
**Output:** Fragen zur Selbstreflexion

```
Nach Lösung:
  1. "Wie hast du das gelöst?"
     → Schüler erzählt seinen Prozess
  
  2. "Warum hast du Punkt A als Momentenpunkt gewählt?"
     → Schüler muss Logik erklären
  
  3. "Was wäre passiert, wenn du Punkt B genommen hättest?"
     → Schüler denkt über Alternativen
  
  4. "Wie könntest du deine Lösung überprüfen?"
     → Schüler plant nächsten Schritt (Probe)
```

**Ziel:** Schüler wird aktiv selbst zum Denker (nicht passiver Empfänger)

---

## MODUL 6: Individualisierte Schwierigkeit (Adaptive Difficulty)

**Input:** Schülers aktuelle Performance  
**Output:** Nächste Aufgabe angepasst

```
IF Schüler löst 3 Aufgaben korrekt:
  → Nächste Aufgabe: SCHWIERIGER (mehr Körper, mehr Lager)

IF Schüler löst 2/5 Aufgaben falsch:
  → Nächste Aufgabe: ÄHNLICHES NIVEAU
  
IF Schüler löst 4/5 Aufgaben falsch:
  → Nächste Aufgabe: LEICHTER (zurück zu Basics)
  → Review: "Lass uns nochmal Stäbe üben"
```

**Ziel:** ZPD immer optimal treffen

---

## MODUL 7: Feedback-Engine

**Input:** Schüler sendet Lösung  
**Output:** Strukturiertes Feedback (nicht einfach "Falsch!")

**Feedback-Struktur:**

```
TASK LEVEL (Was ist konkret falsch?):
  "Dein Freikörperbild ist richtig."

PROCESS LEVEL (Wie hast du das gemacht?):
  "Aber du hast das Moment um den FALSCHEN Punkt berechnet.
   Das macht die Gleichung kompliziert."

SELF-REGULATION LEVEL (Wie könntest du es besser machen?):
  "Nächstes Mal: Schau wo deine Unbekannten sind.
   Wähle einen Momentenpunkt, wo Unbekannte sich aufheben."

SELF LEVEL (Ermutigung):
  "Du machst Fortschritt — Freiköperbild war perfekt!"
```

**NICHT:** "Das ist falsch. Richtig ist..." (demoralisierend)

---

## MODUL 8: Learning Analytics & Progress Tracking

**Input:** Alles was Schüler tut (Antworten, Zeit, Hints)  
**Output:** Dashboard für Schüler + AI

```
Schüler-Dashboard:
  ✅ Häufig richtig: Stäbe, Lagertypen
  ⚠️ Mittelmäßig: Momentenpunkt-Wahl
  ❌ Häufig falsch: Statische Bestimmtheit
  
  📊 Progress: "Diese Woche: +15% in Fachwerken"
  
  🎯 Empfehlung: "Nächstes Thema: Nullstäbe (Basis für Fachwerke)"
```

---

## MODUL 9: Lerntyp-Adaption

**Input:** Schüler-Profil (auditiv/kinästhetisch/visuell)  
**Output:** Erklärungen in seiner Sprache

```
SCHÜLER A (AUDITIV):
  → Mündliche Erklärungen (TTS)
  → Aufgefordert zu sprechen ("Erklärs mir laut")
  → Podcasts / Audionotizen

SCHÜLER B (KINÄSTHETISCH):
  → "Zeichne selbst" Aufgaben
  → Hands-On Experimente
  → Fotos von Zeichnungen + Feedback

SCHÜLER C (VISUELL):
  → Grafiken, Diagramme, Freikörperbilder
  → Farbcodierung
  → Videos (später)
```

---

## MODUL 10: Motivations-Engine

**Input:** Schülers Engagement + Performance  
**Output:** Adaptive Motivation-Strategies

```
IF Schüler macht Fehler (aber versucht):
  ✅ "Du bist auf dem richtigen Weg!"

IF Schüler steckt fest:
  ✅ "Das ist normal. Die nächsten 5 Minuten sind wichtig."

IF Schüler hat 5 richtig in Folge:
  🎉 "Krass! Du verstehst Stäbe jetzt!"
  → Zeige PROGRESS (Woche 1 vs. Jetzt)

IF Schüler ist demoralisiert:
  ✅ "Sieh dir an, was du letzte Woche nicht konntest
      und heute kannst!"
```

---

## Tech-Stack (Grobe Idee)

```
Frontend (Schüler-Interface):
  - Next.js (Aufgaben + Feedback + Progress)
  - Canvas (für Zeichnungen)
  - TTS (für Audio)

Backend (KI-Engine):
  - Claude API (Diagnose, Feedback, Hints)
  - Embedding-DB (Fehlkonzepte, ähnliche Aufgaben)
  - Learning Analytics (Tracking)

Speicher:
  - PostgreSQL (User, Progress, Aufgaben)
  - Vector DB (Konzept-Embeddings)
  - File Storage (Schüler-Zeichnungen, Audios)
```

---

## Entwicklungs-Roadmap

**MVP (4 Wochen):**
- Module 1, 2, 3, 5, 7 (Kern: Diagnose + Scaffolding + Feedback)
- Mit TME102 testen
- Basis-Fehlkonzept-DB für Statik

**Phase 2 (8 Wochen):**
- Modul 4 (Multiple Representations)
- Modul 6 (Adaptive Difficulty)
- Modul 9 (Lerntyp-Adaption)

**Phase 3 (12 Wochen):**
- Modul 8 (Analytics)
- Modul 10 (Motivation)
- UI Polish
- Beta-Tests mit 10 Schülern

---

## KRITISCHE FRAGEN

1. **Wie erkenne ich ein Fehlkonzept?** 
   → NLP-Klassifizierer trainieren mit 100+ Beispielen

2. **Wie wähle ich den richtigen Hint?**
   → Kombination von Fehlkonzept + Lerntyp + ZPD-Level

3. **Woher kommt die Fehlkonzept-Datenbank?**
   → Anfang: Manuell für TME102
   → Später: Crowdsourced + KI-generiert

4. **Ist das zu komplex?**
   → JA! MVP sollte nur 3-4 Module sein.
   → Stepweise komplexer werden.

5. **Wer zahlt dafür?**
   → B2C: €9-19/Monat (Schüler)
   → B2B: €0.50-1.00 pro Schüler/Monat (Unis)
