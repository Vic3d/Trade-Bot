# Morgen-Deploy-Checklist — Josh Dashboard (21.03.2026)

**Erstellt:** 20.03.2026 19:22 CET
**Grund:** Vercel-Limit (100 Deployments/Tag) erschöpft — Reset um 02:00 CET

---

## Status: Bereit zum Deploy ✅

Alle Commits sind auf GitHub, Code ist sauber.

**Letzter Commit:** `ce48d2c` (main Branch)
**Letzte deployment:** `67605a2` (Sprint 1 Geocoder)
**Wartet auf Deploy:**
- `7c0521a` — OSRM Matrix, ORS VRP, Straßendistanzen
- `15131f4` — Notfall-Priorisierung Bug-Fix (TRA-219)
- `3d28b27` — empty commit (kann ignoriert werden)
- `ce48d2c` — lazy-load ors.js Fix + version 2.1.0

---

## Schritt 1: Vercel Deploy

Morgen früh einfach: **Vercel Dashboard → Deployments → Redeploy** (letzten Commit)

ODER: Neuen kleinen Commit pushen → auto-deploy sollte wieder funktionieren.

Deploy-Erfolg prüfen:
```
curl https://sanit-r.vercel.app | grep 'content="2.1.0"'
```
→ Wenn `content="2.1.0"` erscheint: ✅ neu deployed

---

## Schritt 2: ORS_API_KEY in Vercel setzen

1. Vercel Dashboard → Project → Settings → Environment Variables
2. `ORS_API_KEY` = (aus `.env.local` im josh-dashboard Verzeichnis)
3. Environment: Production ✅
4. Save → dann nochmal Redeploy

**Was das bringt:** Echter VRP-Solver (Vroom) für Routenplanung statt OSRM Trip.
ETAs pro Stop, Zeitfenster, Kapazitäten — das Niveau professioneller Tourenplaner.

---

## Schritt 3: Funktions-Tests nach Deploy

```bash
# 1. Version prüfen
curl https://sanit-r.vercel.app | grep version

# 2. Matrix API (neu)
curl -X POST https://sanit-r.vercel.app/api/matrix \
  -H "Content-Type: application/json" \
  -d '{"orders":[{"id":"t1","coords":[8.394,51.923]}]}'
# Erwarte: {"matrix":{"t1":{...}},"cached":false}

# 3. Route mit Notfall (Bug-Fix)
# Notfall muss Stop 1 sein, nicht am Ende
```

---

## Was heute fertig wurde (Sprint 1+2)

### Sprint 1 — Geocoding
- `api/_lib/geocoder.js`: Nominatim Street-Level Geocoding
- PLZ-Zentrum (±2-3km) → echte Hausadresse (±30m)
- Cache + Rate-Limit (1 req/s) + 15s Timeout + PLZ-Fallback
- Google Maps: `optimize:true` entfernt → Reihenfolge konsistent mit OSRM

### Sprint 2 — Routing
- `api/matrix.js`: OSRM Table API — echte Fahrstrecken statt Luftlinie
  - 4 Techs × N Aufträge in einem Call
  - Lazy-Loading im Frontend (Route-Tab öffnen)
- `api/_lib/ors.js`: OpenRouteService VRP Solver
  - Directions + Optimization (Vroom, Zeitfenster, Kapazitäten, ETAs)
  - ORS → OSRM → Nearest Neighbor Fallback-Kette
- `estimateJobDuration()`: Auftragsdauer nach Gewerk
  - Notfall: 2h | Bad/Installation: 3h | Heizung: 45min | Standard: 1h
- **Bug-Fix TRA-219**: Notfälle aus OSRM-Pool → manuell vorne
  - Vorher: OSRM ignorierte emergency flag → Notfall landete am Ende
  - Nachher: Notfälle immer Stop 1..N garantiert

---

## Offene Issues nach Deploy

- TRA-218: WhatsApp direkt an Monteur aus Route-Tab (nächster Sprint)
- TRA-220: OSRM-Geometry als Polylinie auf Karte (nach ORS-Key)
- TRA-221: Ausreißer 1-Click umzuweisen (nach Matrix-Deploy)
- TRA-222: Geschätzte Auftragsdauer live im UI anzeigen (Backend fertig)
- TRA-223: Alle 4 Monteure gleichzeitig auf Karte

---

## Notes
- Vercel Free: 100 Deployments/Tag — heute verbraucht durch Sprint 1+2+Fixes
- ORS API Key: funktioniert ✅ (heute 19:20 CET getestet)
- GITHUB_TOKEN für Kanban Pipeline: noch nicht in Vercel gesetzt
