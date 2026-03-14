# Lern-Bot AKAD — Projekt Status

**Version:** 1.0 MVP — Full Dashboard + 3-Tage-Plan
**Status:** ✅ READY FOR 13:00 START (14.03.2026)
**Ziel:** TME102 in 3 Tagen Meistern (Prüfung Anfang April)

---

## 📋 Was ist fertig

### **Phase 1: Lernstrategie + Plan**
- ✅ `LERNSTRATEGIE.md` — Psychologie-basierter Lernansatz
- ✅ `3-TAGE-PLAN.md` — Minutengenaue Timeline (Sa 13:00 - Mo 12:00)
- ✅ Kapitel-Struktur aus TME102 Script analysiert (2 Chapters, 8 Subkapitel)

### **Phase 2: Lernmodule (Kapitel 1.1–1.3 fertig)**
- ✅ `lernmodule/01-grundlagen/1-1_tragelemente.md` 
  - Stabförmig vs. Flächenartig
  - 2 Worked Examples
  - 2 Aufgaben
  
- ✅ `lernmodule/01-grundlagen/1-2_lager-anschluesse.md`
  - 3 Lagertypen (Fest-, Bolzen-, Roller)
  - Freiheitsgrad-Konzept
  - Symbol-Übersicht
  
- ✅ `lernmodule/01-grundlagen/1-3_lagerreaktionen.md` ⭐ KERN!
  - Gleichgewichtsbedingungen (ΣFx=0, ΣFy=0, ΣM=0)
  - Freikörperdiagramme
  - 2 detaillierte Worked Examples
  - 2 Aufgaben

### **Phase 3: Full MVP Dashboard**

#### **Features:**
- ✅ **Quick-Start Card** (oben links)
  - Zeigt aktuelles Kapitel
  - Duration + Aufgabenanzahl
  - [JETZT STARTEN] Button
  
- ✅ **Progress Tracker** (oben rechts)
  - 8 Kapitel mit Progress-Bars
  - Gesamtfortschritt % + Count (0/28 Aufgaben)
  - Status: Todo / In Progress / Done
  
- ✅ **Cognitive Load Meter** (unten links)
  - Real-time Brain Fatigue (0-10 Skala)
  - Farbencodiert (Grün/Orange/Rot)
  - Automatische Pause-Warnung bei Load > 7
  - Berechnungslogik: Zeit + Fehler + Base-Load
  
- ✅ **Weak Points Analyzer** (unten rechts)
  - Erfasst Fehler pro Kapitel
  - Accuracy % tracking
  - "Üben" + "Tipp" Buttons
  
- ✅ **Timer System**
  - Start/Pause/Resume Funktionalität
  - Farbige Warnung (Grün → Orange → Rot)
  - Auto-Fertig-Warnung bei 0:00
  
- ✅ **Aufgaben-Checker**
  - Textarea für Antwort
  - [✓ Überprüfen] → ✅/❌ Feedback
  - Automatischer Cognitive Load Update
  
- ✅ **Auto-Save via localStorage**
  - Alle Progress-Daten persistent
  - Browser-Restart = Daten erhalten
  
- ✅ **Responsive Design**
  - Desktop: 3-Spalten
  - Tablet: 2-Spalten
  - Mobile: Vertikal gestapelt
  
- ✅ **Insights & Recommendations**
  - Nächste Pause-Zeit
  - Realistische Zeitplanung
  - Motivations-Tipps

#### **Tech Stack:**
- HTML5 + CSS3 (responsive grid/flexbox)
- Vanilla JavaScript (no frameworks = schnell!)
- localStorage (no backend needed)
- Color-coded UI (Grün/Orange/Rot für Status)

#### **Dateien:**
```
dashboard/
├── index.html           (UI + Modal Structure)
├── css/styles.css      (Responsive Design)
├── js/app.js           (Main Controller)
├── js/tracker.js       (Progress Tracking)
├── js/cognitive-load.js (Brain Meter)
├── progress.html       (older version, unused)
└── README.md           (Bedienungsanleitung)
```

---

## 🗺️ Ablauf ab 13:00

### **TAG 1: SAMSTAG 13:00–18:00 (5 Stunden)**

| Zeit | Kapitel | Min | Was |
|------|---------|-----|-----|
| 13:00–13:40 | 1.1 Tragelemente | 40 | Erklärung + 2 Aufgaben |
| 13:45–14:45 | 1.2 Lager & Anschlüsse | 60 | Lagertypen, Freiheitsgrade |
| 14:50–16:00 | 1.3 Lagerreaktionen ⭐ | 70 | **KERN! Gleichgewicht, FKD** |
| 16:05–17:15 | 1.4 Stat. Bestimmtheit ⭐ | 70 | Bestimmtheitscheck |
| 17:20–17:50 | 1.5 Mehrkörpersysteme | 30 | Gerberträger |

### **TAG 2: SONNTAG 09:00–15:00 (6 Stunden)**

| Zeit | Kapitel | Min | Was |
|------|---------|-----|-----|
| 09:00–09:30 | 2.1 Fachwerk Def. | 30 | Theorie |
| 09:35–10:10 | 2.2 Stat. Bestimmtheit | 35 | Check-Verfahren |
| 10:15–12:15 | 2.3 Fachwerk-Berechnung ⭐⭐ | 120 | **Knotenpunkt + Ritterschnitt** |
| 12:15–13:00 | Mittagspause | 45 | – |
| 13:00–15:00 | Wiederholung + Vertiefung | 120 | Schwache Punkte |

### **TAG 3: MONTAG 09:00–12:00 (3 Stunden)**

| Zeit | Was | Min |
|------|-----|-----|
| 09:00–10:00 | Wiederholung schwache Punkte | 60 |
| 10:00–12:00 | PRÜFUNGS-SIMULATION (3 Mixed-Aufgaben) | 120 |

---

## 📊 Dashboard-Metriken (Was wird trackt?)

### **Pro Kapitel:**
- ⏱️ Zeit investiert
- 📝 Aufgaben richtig/falsch
- 🎯 Accuracy % (wie viel korrekt)
- 🧠 Cognitive Load während Kapitel

### **Global:**
- 📈 Gesamtfortschritt % (0-100)
- 🔴 Rote Flaggen (Problem-Punkte)
- ⚡ Fatigue-Level (0-10)
- 🕐 Zeitbudget-Abweichung

---

## 🧠 Cognitive Load Logik

**Berechnung:**
```
Load = Base (2) + Time Factor (t*0.1) + Error Factor (e*0.8)
Max = 10
```

**Beispiel:**
- 30 Min gelernt, 2 Fehler: Load = 2 + 3 + 1.6 = 6.6/10 🟡
- 60 Min gelernt, 5 Fehler: Load = 2 + 6 + 4 = 12 → capped at 10 🔴

**Auto-Warning:**
- Load > 7: "Bitte mach eine Pause!"
- Load > 8: Dringend!
- Load > 9: Hirnstatus kritisch!

---

## 🔄 Nächste Schritte (Nach Tag 1)

### **Morgen (So):**
- [ ] Module für 1.4, 1.5, 2.1, 2.2, 2.3 schreiben (Albert)
- [ ] Dashboard mit echtem Daten-Feedback verbinden (optional)
- [ ] Spaced Repetition Erinnerungen einbauen (optional)

### **Nach Prüfung:**
- [ ] TME101 + TME103 Scripts durcharbeiten
- [ ] Weitere Scripts (falls vorhanden)
- [ ] Dashboard -> Web-App (Vercel deploy)

---

## ✅ Ready-Checks

- ✅ GitHub Repo (`git@github.com:Vic3d/lernbot.git`) angelegt
- ✅ Dashboard lädt ohne Fehler (lokal getestet)
- ✅ Timer funktioniert
- ✅ Progress wird trackt + gespeichert
- ✅ Cognitive Load Meter zeigt korrekt
- ✅ Responsive auf Desktop/Tablet/Mobile
- ✅ Lernmodule 1.1–1.3 geschrieben + mit Aufgaben
- ✅ README für Dashboard geschrieben
- ✅ Alles ins Git gepusht

---

## 🚀 Wie starten um 13:00?

1. **Dashboard öffnen:**
   ```
   lernbot/dashboard/index.html
   ```
   → Im Browser (Chrome/Firefox/Safari)

2. **Klick [▶️ JETZT STARTEN]**
   → Timer startet (30 Min für 1.1)
   → Modal mit Lernmodul-Info öffnet

3. **Öffne parallel in neuem Tab:**
   ```
   lernbot/lernmodule/01-grundlagen/1-1_tragelemente.md
   ```
   → Lies Erklärung + Worked Examples
   → Mach Aufgaben auf Papier

4. **Gib Antworten ins Dashboard:**
   → [✓ Überprüfen]
   → Feedback + Progress-Update automatisch

5. **Nach 30 Min:** Timer = 00:00
   → [✅ Kapitel abgeschlossen]
   → Nächstes Kapitel (1.2) startet

---

## 📞 Kontakt für Probleme

- **Browser-Fehler:** F12 → Console → Screenshot der Fehlermeldung
- **Dashboard funktioniert nicht:** localStorage.clear() + Reload
- **Lernmodul zu schnell/langsam:** Feedback geben → Albert passt an
- **Cognitive Load zu pessimistisch?** Berechnung justieren

---

**Status: 🟢 READY FOR LAUNCH**

Alles vorbereitet für Sa 13:00 Start! 🚀
