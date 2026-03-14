# Projekt: WerkstattOS

## Basics
- **Produkt:** WhatsApp-native Betriebssoftware für KFZ-Werkstätten
- **Beteiligte:** Victor (Backend), Vincent (Frontend/Design)
- **Status:** Konzeptphase — Whitepaper erstellt, MVP noch nicht gestartet
- **Datum gestartet:** 27.02.2026

## Idee
KFZ-Werkstätten in Deutschland (~28.000 freie Betriebe) sind stark unterdigitalisiert.
Kernprobleme: No-Shows, Telefon-Overhead, keine Kundenbindung, Papier-Aufträge.
Lösung: WhatsApp-native SaaS-Plattform die den gesamten Kommunikationsflow automatisiert.

## Positionierung
- Zielgruppe: Freie Werkstätten mit 1–8 Mitarbeitern
- Preis: €99–199/Monat
- Abgrenzung: Günstiger + einfacher als Enterprise-Software (Autosoft etc.), spezialisierter als generische Tools

## Features (priorisiert)
1. WhatsApp-Terminbestätigung + Erinnerung (No-Show Killer) ← MVP-Kern
2. Fahrzeugstatus "Fertig"-Button per WhatsApp (Telefon-Killer) ← MVP-Kern
3. Google Reviews Automation nach Abholung ← MVP-Kern
4. Digitale Auftragserfassung + Fotos
5. TÜV/Service-Erinnerungen (Umsatz-Booster)
6. Dashboard + Auslastungsübersicht

## Markt
- TAM: ~99 Mio. € ARR (DACH)
- SAM: ~50 Mio. € ARR (DE, freie Werkstätten)
- SOM (Jahr 3): ~2,5 Mio. € ARR (5% Marktanteil)

## Geschäftsmodell
- SaaS-Abo (€99/€149/€199 pro Monat)
- Breakeven bei ~30–40 Kunden
- LTV/CAC ~60–110x

## Tech-Stack
- Backend: Node.js
- DB: PostgreSQL
- WhatsApp: Meta WhatsApp Business API
- Hosting: Hetzner (Deutschland, DSGVO)
- Analytics: PostHog

## Dokumente
- Whitepaper: /data/.openclaw/workspace/werkstattos-whitepaper.md

## Nächste Schritte
1. [ ] Landingpage bauen (1-pager, Mock-up, E-Mail-Sammlung)
2. [ ] 10 Werkstätten direkt kontaktieren (Validierung)
3. [ ] MVP definieren (nur die 3 Kernfeatures)
4. [ ] 3 Beta-Kunden gewinnen (kostenlos, gegen Feedback)
5. [ ] Produktname final entscheiden (WerkstattOS oder anders?)

## Offene Fragen
- Direktverbindung zur Meta WhatsApp API oder über Superchat?
- Investoren ansprechen oder bootstrapped starten?
- Vincent Nachnamen für Whitepaper eintragen
