# Projekt: Turnverein Willich Website

## Status (Stand: 26.02.2026, 23:50)
**Phase:** Prototyp fertig — Angebot wird an Kunden gesendet  
**Prototyp live:** http://167.235.250.10:8080/ (bleibt mind. 1 Woche online)  
**Lokal:** /data/.openclaw/workspace/wtv-prototype/  
**Server:** /var/www/html/wtv-prototype/ auf Hetzner (167.235.250.10)  
**Nginx:** Port 8080, Config: /etc/nginx/sites-available/wtv-preview  
**Seiten:** 18 HTML-Seiten, 0 kaputte Links, 3-Klick-Regel vollständig erfüllt

## Beteiligte
- **Kunde:** Willicher Turnverein 1892 e.V.
- **Ansprechpartner Kunde:** Gaby Heinemeyer (ÖA-Team) — info@willicher-turnverein.de
- **Umsetzer:** Victor (Branding Brothers)

## Nächste Schritte
1. E-Mail an Gaby Heinemeyer senden → Entwurf: `memory/wtv-email-angebot.md`
2. Auf Antwort / Preisvorschlag des Vereins warten
3. Nach Zusage: echte Fotos + Daten einpflegen

## Angebotsstrategie
- Früheres Angebot: 3.500 € für Webflow
- Neuer Ansatz: **kein fester Preis** — Verein soll nennen was möglich ist
- Argument: Alternative zu Webflow → direkt auf Strato hostbar, keine Lizenzkosten
- Webflow wird **nicht** schlecht geredet — nur Alternative aufzeigen
- E-Mail-Entwurf fertig in `memory/wtv-email-angebot.md`

## Hosting-Plan (Produktion)
- Domain bleibt: willicher-turnverein.de (aktuell Strato-Baukasten)
- Strato Baukasten → Strato Webhosting wechseln (~4–6 €/Monat, günstiger als Baukasten)
- Fertige HTML/CSS/JS per FTP hochladen
- Keine monatlichen Lizenzkosten für externe Plattformen
- DSGVO-konform (deutsches Rechenzentrum)

## Deploy-Befehl (Hetzner Prototype)
```bash
cd /data/.openclaw/workspace/wtv-prototype && \
find . -name "*.html" | tar -czf /tmp/wtv_html.tar.gz -T - && \
scp -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no /tmp/wtv_html.tar.gz root@167.235.250.10:/tmp/ && \
ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no root@167.235.250.10 \
  "cd /var/www/html/wtv-prototype && tar -xzf /tmp/wtv_html.tar.gz && echo 'deployed'"
```

---

## Alle 18 Seiten

| Seite | Pfad | Status |
|-------|------|--------|
| Homepage | `index.html` | ✅ |
| Sportangebote Übersicht | `sportangebote/index.html` | ✅ |
| Turnen & Breitensport | `sportangebote/turnen/` | ✅ |
| Gesundheitssport | `sportangebote/gesundheit/` | ✅ |
| Fitness & Body Workouts | `sportangebote/fitness/` | ✅ |
| Tanzen & Rhythmus | `sportangebote/tanzen/` | ✅ |
| Basketball | `sportangebote/basketball/` | ✅ |
| Volleyball | `sportangebote/volleyball/` | ✅ |
| Bodyart® | `sportangebote/bodyart/` | ✅ |
| Budo & Kampfsport | `sportangebote/budo/` | ✅ |
| Kids & Teens | `sportangebote/kids/` | ✅ |
| Bewegungstheater & Pantomime | `sportangebote/bewegungstheater/` | ✅ |
| Kurse & Anmeldung | `kurse/` | ✅ |
| News & Termine | `news/` | ✅ |
| Über uns | `ueber-uns/` | ✅ |
| Mitglied werden | `mitglied-werden/` | ✅ |
| Kontakt | `kontakt/` | ✅ |
| Impressum / Datenschutz | `impressum/` | ✅ |

---

## Navigation (7 Hauptpunkte — 3-Klick-konform)

| Punkt | Dropdown-Einträge |
|-------|------------------|
| Startseite | — |
| Sportangebote | Turnen, Gesundheit, Fitness, Bodyart®, Tanzen, Basketball, Volleyball, Budo, Kids & Teens, Bewegungstheater & Pantomime |
| Kurse & Anmeldung | — |
| News & Termine | — |
| Über uns | Geschichte, Vorstand, Jugend, WTV 2030, Integration durch Sport, Willich gemeinsam, Girls Day Projekt |
| Mitglied werden | Beiträge & Formulare, Freie Plätze, Übungsleiter/-in gesucht |
| Kontakt | Öffnungszeiten, Sporthallen, Impressum, Datenschutz |

**Alle 28 Original-Navigationspunkte der alten Strato-Seite sind abgedeckt.**

---

## 3-Klick-Regel — vollständig erfüllt ✅

Jede Seite ist in max. 2 Klicks erreichbar:
- Klick 1: Hauptmenü-Punkt hovern → Dropdown erscheint
- Klick 2: Dropdown-Link → Seite / Anker

---

## Technischer Stack
- Reines HTML / CSS / JavaScript — keine Frameworks, kein jQuery, kein CMS
- Progressive Enhancement: Animationen funktionieren auch ohne JS
- WCAG 2.2 AA konform
- Mobile-first, responsive
- Fonts: Bebas Neue (Headlines), Inter (Body) — Google Fonts
- Icons: Lucide-style SVG, inline, in Vereinsfarben

## Animations-Inventar
- **Hero:** Parallax (JS/rAF), Ken Burns (CSS), Text-Split Wipe-Up, Typewriter Badge, Floating Badge, Grain Textur
- **Nav:** Scroll Progress Bar, Custom Cursor (Desktop), Logo 3D Tilt, Nav Stagger (1x sessionStorage), Sliding Pill Indicator, Transparent→Solid beim Scrollen
- **Cards:** 3D Tilt (Desktop), Gold Overlay on Hover, Scroll Image Zoom
- **Sections:** Scroll-Animationen (.scroll-anim/.hidden), Section Underline Draw, Stat Counter (easeOut)
- **Global:** Pulsing Glow Buttons, Click Glow Ring (280ms Delay), Page Fade-IN
- **Marquee:** Gold Strip (64s, "TURNEN • TANZEN • ...") zwischen Stats und Sports
- **Dropdown:** Scale+Blur+Translate, staggered nth-child Delays
- **About:** Dekoratives "1892" im Hintergrund (6% opacity)
- **Stats:** Glassmorphism Bar (backdrop-filter blur 12px)

## Design-Prinzipien (PFLICHT)
- Icons / Grafiken: **immer in Vereinsfarben, immer minimalistisch** — keine bunten Stock-Icons
- Navy `#1B3A8C` · Gold `#E8B800` · Hellblau `#A8B8D0` · Weiß `#FFFFFF`
- Stil: clean, athletisch, reduziert — weniger ist mehr
- Firmierung nach außen: **Branding Brothers** — kein anderer Name

## Platzhalter (werden nach Kickoff befüllt)
- Überall: "Dieser Bereich wird noch mit Inhalten befüllt."
- Trainingszeiten aller Sportangebote (echte Daten vom WTV)
- Fotos (aktuell Unsplash-Platzhalter)
- Campai-Link / Embed für Kursanmeldung
- Impressum / Datenschutz mit echten Vereinsdaten
- Kontaktformular Backend (z.B. Formspree)

## Offene Punkte
- [ ] E-Mail an Gaby Heinemeyer senden
- [ ] Budget / Preisvorschlag des Vereins abwarten
- [ ] Echte Fotos anfordern
- [ ] Campai-Zugangsdaten / Embed-Typ klären
- [ ] Strato-Paket: Baukauten → Webhosting wechseln
- [ ] CMS-Entscheidung (WordPress empfohlen falls ÖA-Team selbst pflegen soll)
- [ ] Impressum / Datenschutz mit echten Daten füllen
