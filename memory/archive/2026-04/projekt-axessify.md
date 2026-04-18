# Projekt: Axessify

**Status: ARCHIVIERT — 25.02.2026**
**Beteiligte:** Victor (Backend/Server), Vincent (Frontend/Website), Schmobro (Strategie/Doku)

---

## Einstellung (25.02.2026)

Entscheidung von Victor: Axessify wird nicht weiterverfolgt.

**Gründe:**
- Konkurrenz zu groß
- Kein klarer USP
- Laufende Kosten nicht deckbar, Gewinne unwahrscheinlich

---

## Was wurde archiviert

| Was | Wo |
|---|---|
| Vollarchiv (Code + DB + Backups) | `/root/axessify-archive-20260225.tar.gz` (Hetzner, 2,2 GB) |
| PostgreSQL-Dump | `/opt/axessify-archive-db-20260225.sql` (Hetzner) |
| /opt-Ordner | `/opt/axessify-dashboard`, `/opt/axessify-backups`, `/opt/axessify-training-data` |

## Was abgeschaltet wurde

- PM2-Prozess `axessify-dashboard` gestoppt + gelöscht
- Stripe + zahlender Kunde: von Victor erledigt

## Noch offen

- [ ] GitHub-Repo archivieren (read-only stellen) — Victor oder Albert
- [ ] Domain axessify.de: behalten oder kündigen? — Victor entscheidet
- [ ] /opt/axessify-* Ordner auf Server: aufräumen wenn Archiv gesichert ist?

---

## Projektgeschichte

- **Tech-Stack:** Next.js 16, React, TypeScript, Drizzle ORM, PostgreSQL, Stripe, PM2
- **Server:** 167.235.250.10 (Hetzner)
- **Domain:** axessify.de / dashboard.axessify.de
- **Ziel war:** WCAG-Scanner + Accessibility-Widget (BFSG-Konformität)
- **Sicherheitsvorfall:** 22.02.2026 — Server hätte neu aufgesetzt werden müssen
- **1 zahlender Kunde** hatte das Produkt genutzt
- **Strategiewechsel** 24.02.2026: Weg vom KI-Pivot, zurück zum Kern — aber zu spät
