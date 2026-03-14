# Axessify WCAG-Scanner — Anforderungen 2026

*Erstellt: 24.02.2026*

---

## Überblick

Ein moderner WCAG-Scanner muss **WCAG 2.2 Level A + AA** vollständig abdecken. Das sind die gesetzlich relevanten Stufen (BFSG, EAA, EN 301 549). Zusätzlich gibt es Best Practices und optionale AAA-Regeln.

**Referenz:** axe-core (Deque) definiert den Industriestandard mit ~100 automatisierbaren Regeln. Unser Scanner sollte mindestens diese abdecken.

---

## 1. Automatisierbare Prüfkategorien

### 🔤 Textalternativen (WCAG 1.1)
- Bilder (`<img>`) haben alt-Text
- SVGs mit role="img" haben accessible name
- Image Maps (`<area>`) haben alt-Text
- `<input type="image">` hat alt-Text
- `<object>`, `<video>`, `<audio>` haben Alternativen
- Dekorative Bilder haben `role="none"` oder leeres alt

### 🎬 Zeitbasierte Medien (WCAG 1.2)
- Videos haben Untertitel/Captions
- Kein Autoplay von Audio >3 Sekunden ohne Stopp-Mechanismus

### 📐 Anpassbar / Struktur (WCAG 1.3)
- Korrekte Heading-Hierarchie (h1→h2→h3, keine Sprünge)
- Listen korrekt strukturiert (`<ul>/<ol>/<dl>`)
- Tabellen mit korrekten Headers (`<th>`, `headers`-Attribut)
- Formulare haben Labels
- Landmark-Regionen vorhanden (main, nav, header, footer)
- ARIA-Rollen korrekt eingesetzt
- Autocomplete-Attribute korrekt (WCAG 1.3.5)

### 🎨 Unterscheidbar / Visuell (WCAG 1.4)
- **Farbkontrast** Text vs. Hintergrund ≥ 4.5:1 (normal) / ≥ 3:1 (groß)
- **Nicht-Text-Kontrast** ≥ 3:1 für UI-Komponenten (WCAG 1.4.11)
- Kein Inhalt nur durch Farbe unterscheidbar
- Links in Textblöcken visuell unterscheidbar (nicht nur Farbe)
- Text-Resize bis 200% ohne Informationsverlust
- `<meta viewport>` deaktiviert Zoom nicht
- Inline-Spacing überschreibbar (WCAG 1.4.12)
- Kein horizontales Scrollen bei 320px Breite (Reflow, WCAG 1.4.10)

### ⌨️ Tastatur (WCAG 2.1)
- Alle Funktionen per Tastatur erreichbar
- Keine Keyboard-Traps
- Skip-Navigation vorhanden (Bypass-Mechanismus)
- Scrollbare Bereiche per Tastatur erreichbar
- Fokus nicht durch aria-hidden blockiert
- Frames mit fokussierbarem Inhalt nicht tabindex=-1
- Verschachtelte interaktive Elemente vermeiden

### ⏱️ Zeit & Bewegung (WCAG 2.2)
- Kein `<blink>` oder `<marquee>`
- Kein `<meta http-equiv="refresh">` für automatische Weiterleitung
- Bewegte Inhalte haben Pause-Mechanismus

### 🧭 Navigation (WCAG 2.4)
- Seitentitel (`<title>`) vorhanden und sinnvoll
- Link-Texte aussagekräftig (nicht "hier klicken")
- Fokus-Reihenfolge logisch
- Frame-Titel vorhanden und eindeutig
- **Target Size** ≥ 24x24px für Touch-Targets (WCAG 2.5.8, neu in 2.2!)

### 📝 Eingabe (WCAG 3.3)
- Formulare haben Error-Identification
- Labels oder Instruktionen vorhanden
- Keine mehrfachen Labels pro Feld

### 🌐 Sprache (WCAG 3.1)
- `<html lang>` vorhanden und gültig
- Sprachwechsel innerhalb der Seite korrekt markiert (`lang`-Attribut)
- lang und xml:lang stimmen überein

### 🔧 ARIA & Semantik (WCAG 4.1)
- ARIA-Rollen sind gültig
- ARIA-Attribute sind erlaubt für die jeweilige Rolle
- Pflicht-ARIA-Attribute vorhanden
- ARIA-Attribut-Werte gültig
- Keine veralteten ARIA-Rollen
- Buttons, Links, Menüitems haben accessible names
- Eingabefelder, Toggles, Tabs haben accessible names
- Keine doppelten IDs (ARIA-relevant)
- aria-hidden="true" nicht auf `<body>`

---

## 2. Scan-Features (über reine Regelprüfung hinaus)

### Must-Have
- **Multi-Page Crawling** — nicht nur eine Seite, sondern ganze Website scannen
- **Accessibility Score** — Gesamtbewertung (z.B. 0-100) als Quick-Indikator
- **Issue-Kategorisierung** nach Schwere: Critical / Serious / Moderate / Minor
- **Issue-Kategorisierung** nach Typ: Fehler / Warnung / Manuell prüfen
- **WCAG-Zuordnung** — jedes Issue zeigt welches WCAG-Kriterium verletzt wird
- **Element-Lokalisierung** — CSS-Selektor + HTML-Snippet des betroffenen Elements
- **Lösungsvorschläge** — Was muss gefixt werden? (Help-Text pro Regel)
- **BFSG/EAA-Mapping** — Regeln auf EN 301 549 / BFSG mappen
- **Regelmäßiges Monitoring** — automatischer Re-Scan (wöchentlich/monatlich)
- **Trend-Tracking** — Score-Verlauf über Zeit
- **PDF-Export** — Scan-Ergebnis als Report

### Should-Have
- **Seitenweise Aufschlüsselung** — Issues pro URL
- **Filterung** — nach WCAG-Level, Kategorie, Schwere, Seite
- **Vergleich** — Scan A vs. Scan B (was hat sich verbessert/verschlechtert?)
- **E-Mail-Alerts** — Benachrichtigung bei Score-Änderung oder neuen Issues
- **Accessibility Statement Generator** — Automatische Erklärung zur Barrierefreiheit
- **Sitemap-Support** — Crawl basierend auf sitemap.xml
- **Authentifizierte Scans** — Login-geschützte Bereiche scannen
- **Single Page App Support** — JavaScript-gerenderte Seiten (braucht Headless Browser)

### Nice-to-Have (später)
- **Browser Extension** — Inline-Audit direkt auf der Seite
- **API** — Scan per API triggern (für CI/CD oder Agenturen)
- **White-Label Reports** — Agentur-Branding auf PDF-Reports
- **Competitive Benchmarking** — "Deine Website vs. Branchendurchschnitt"
- **Best Practice Checks** — Über WCAG hinaus (z.B. Tabindex >0, leere Headings)

---

## 3. Technische Empfehlung

### Engine
**axe-core** als Basis-Engine:
- Open Source (MPL 2.0)
- Industriestandard, ~100 Regeln
- Zero-false-positive Philosophie
- Läuft im Browser / Headless Browser (Puppeteer/Playwright)
- Wird von Google, Microsoft, Deque selbst genutzt
- ACT-Rules-konform (W3C Standard-Testregeln)

**Ergänzend eigene Checks für:**
- Heading-Hierarchie (axe prüft nur ob Headings existieren, nicht die Logik)
- Content-Qualität (z.B. "alt='image'" ist technisch korrekt aber nutzlos)
- Performance-basierte Checks (Ladezeit beeinflusst Zugänglichkeit)
- BFSG-spezifische Anforderungen

### Crawler
- **Playwright** (Headless Chromium) für JavaScript-Rendering
- Sitemap.xml + Link-Discovery
- Respektiert robots.txt
- Konfigurierbare Tiefe und Seitenanzahl (nach Plan begrenzt)
- Paralleles Crawling für Speed

### Scoring
Empfehlung: **Gewichteter Score basierend auf Impact**
- Critical Issues: -10 Punkte
- Serious Issues: -5 Punkte  
- Moderate Issues: -2 Punkte
- Minor Issues: -1 Punkt
- Basis: 100 Punkte
- Minimum: 0

---

## 4. Vergleich: Was die Konkurrenz kann

| Feature | Eye-Able | accessiBe | Deque (axe) | Silktide | **Axessify (Ziel)** |
|---------|----------|-----------|-------------|----------|---------------------|
| Auto WCAG-Scan | ✅ | ✅ | ✅ | ✅ | ✅ |
| Multi-Page Crawl | ✅ | ✅ | ✅ | ✅ | ✅ |
| Score/Dashboard | ✅ | ✅ | ✅ | ✅ | ✅ |
| Monitoring | ✅ | ✅ | ✅ | ✅ | ✅ |
| WCAG 2.2 | ✅ | Teilweise | ✅ | ✅ | ✅ |
| PDF-Reports | ✅ | ✅ | ✅ | ✅ | ✅ |
| Browser Extension | ✅ | ❌ | ✅ | ✅ | Später |
| API | ✅ | ✅ | ✅ | ✅ | Enterprise |
| KI Auto-Fix | ✅ | ✅ | ❌ | ❌ | ❌ |
| Widget/Overlay | ✅ | ✅ | ❌ | ❌ | ✅ (Zugabe) |
| DSGVO/EU-Hosting | ✅ | ❌ | ❌ | ❌ | ✅ |
| **Preis Einstieg** | ~100€+/m | ~$40/m | Enterprise | Enterprise | **15€/m** |

**Unser Vorteil:** Günstigster seriöser Scanner im DACH-Raum mit EU-Hosting + Widget als Bonus.

---

## 5. Dashboard-Konzept (Dynamic Island Style)

Basierend auf Victors Vision — Apple Dynamic Island / Live Activities als Design-Referenz:

### Übersicht (Home)
- **Score-Kapsel** — großer Accessibility Score, pulsiert bei aktivem Scan
- **Status-Pills** — Critical (rot), Serious (orange), Moderate (gelb), Minor (grau)
- **Trend-Spark** — Mini-Graph der letzten 30 Tage im Score-Verlauf
- **Letzer Scan** — Timestamp + "Nächster Scan in X Tagen"

### Issues-View
- **Kompakte Issue-Kapseln** — Icon + Beschreibung + Seite + WCAG-Kriterium
- **Filter-Pills** — klickbare Kapseln zum Filtern (Severity, WCAG-Level, Seite)
- **Expandierbar** — Klick öffnet Details: HTML-Snippet, Lösungsvorschlag, betroffene URL
- **Batch-Ansicht** — gleiche Issues über mehrere Seiten gruppiert

### Seiten-View
- **URL-Kapseln** — jede Seite als Kapsel mit Mini-Score
- **Drill-Down** — Klick zeigt Issues der Seite

### Monitoring
- **Scan-Kapsel** — zeigt laufenden Scan mit Progress-Animation
- **Timeline** — vergangene Scans als Kapseln auf Zeitachse
- **Vergleichs-View** — zwei Scans nebeneinander, Diff markiert

### Reports
- **PDF-Export** — ein Klick, fertiger Bericht
- **Accessibility Statement** — Auto-generiert, Copy-Paste-ready
- **Share-Link** — öffentlicher Report-Link für Kunden/Chefs
