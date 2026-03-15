# Lernplattform — Projektplan

**Start:** 15.03.2026
**Repo:** `lernbot/` (bestehendes Repo, erweitern)
**Live:** https://lern-bot.vercel.app
**GitHub:** git@github.com:Vic3d/Lern-Bot.git

---

## Phase 1: PDF-Reader fertig machen (v1.0)
- [ ] PDF-Extraktion validieren (v0.9.5 Bug-Check)
- [ ] Kapitel-Navigation robust machen
- [ ] Reader UX polieren (Mobile, Loading States, Error Handling)
- [ ] Version 1.0 taggen + deployen

## Phase 2: Backend einbauen
- [ ] Supabase Projekt anlegen (Free Tier)
- [ ] DB-Schema: users, documents, chapters, events
- [ ] Auth (Magic Link — zero friction)
- [ ] Migration: localStorage → Supabase (Hybrid: offline-first, sync wenn online)
- [ ] Event-Logging: jede Interaktion tracken (chapter_read, quiz_answer, time_spent)

## Phase 3: Quiz + Active Recall
- [ ] Claude API Route: Kapitel-Text → 3-5 Fragen generieren (Freitext + MC)
- [ ] Fragen cachen (pro Kapitel einmal generieren, in DB speichern)
- [ ] Quiz-UI nach jedem Kapitel (Pop-up oder eigene Seite)
- [ ] Claude bewertet Freitext-Antworten → Feedback
- [ ] Ergebnisse in Events loggen

## Phase 4: Spaced Repetition
- [ ] SM-2 Algorithmus implementieren (oder vereinfachte Version)
- [ ] Review-Queue: "Diese 5 Fragen sind heute fällig"
- [ ] Dashboard: Retention-Kurve visualisieren
- [ ] Push-Benachrichtigung (optional, später)

## Phase 5: Erklär-Modus
- [ ] "Erklär anders" Button pro Kapitel/Absatz
- [ ] Claude API: Kapitel-Kontext + "erkläre als Analogie / Schritt-für-Schritt / Beispiel"
- [ ] Verschiedene Erklär-Stile (visuell, praktisch, formal)
- [ ] Feedback: "Hat dir das geholfen?" → Event loggen

## Phase 6: Schwächen-Detektor + Profil
- [ ] Events aggregieren → Stärken/Schwächen pro Themengebiet
- [ ] Profil-Dashboard: Radar-Chart, Fortschritt, Empfehlungen
- [ ] "Fokus-Modus": nur schwache Kapitel wiederholen
- [ ] Lernzeit-Optimierung: "Heute 35 Min empfohlen"

## Phase 7: Job-Risiko + Diagnostik (NextJob-Integration)
- [ ] Job-Risiko-Check (Free, kein Account nötig)
- [ ] Diagnostik-Aufgaben (Mini-Tasks statt Fragebögen)
- [ ] Profil erweitern: Berufliche Stärken + Werte
- [ ] Job-Matching (DB mit AI-Resistance-Scores)

---

## Tech-Stack
- **Framework:** Next.js 14 (App Router) — bleibt
- **DB:** Supabase (PostgreSQL + Auth + Realtime)
- **AI:** Claude API (Quiz-Gen, Freitext-Bewertung, Erklärungen)
- **TTS:** Web Speech API (kostenlos) + OpenAI TTS (optional)
- **Hosting:** Vercel (Free Tier)
- **Kosten:** ~$5-10/Monat (Claude API)

## Architektur-Entscheidungen
- **Offline-first:** localStorage als Cache, Supabase als Source of Truth
- **Event-Sourcing-lite:** Jede Interaktion = Event in DB → daraus alles berechnen
- **Generativ:** Quiz-Fragen + Erklärungen von Claude, gecacht in DB
- **Adaptiv:** System passt sich an User-Performance an (Schwierigkeitsgrad, Timing, Stil)
