# TradeMind × MiroFish — Vollausbau-Plan
## "Albert mit echtem Schwarmbewusstsein"

Stand: April 2026 | Status: ZUKUNFTSPLAN (wenn Ressourcen vorhanden)

---

## Vision

Albert handelt heute thesis-getrieben mit einem leichten Crowd-Reaction-Layer (1 Claude-Call).
Dieser Plan beschreibt den Schritt zur echten Swarm-Intelligence:
Albert spawnt vor jedem größeren Trade 50–200 digitale Marktteilnehmer, lässt sie interagieren,
und extrahiert emergentes Marktverhalten — bevor es passiert.

---

## Phase A — Infrastruktur-Upgrade (Voraussetzung)

### Was wir brauchen
| Ressource | Jetzt (CX22) | Ziel |
|---|---|---|
| RAM | 4 GB | 16–32 GB |
| CPU | 2 vCores | 8 vCores |
| VPS-Kosten | 4,50 €/Mo | ~30–50 €/Mo (Hetzner CX52/CCX33) |
| LLM-Kosten | ~5–20 €/Mo | ~100–300 €/Mo (Swarm-Calls) |
| Storage | 40 GB | 160 GB (Graph-DB) |

### Hetzner-Empfehlung wenn bereit
- **Hetzner CCX33**: 8 vCPU, 32 GB RAM, 240 GB NVMe → ~54 €/Mo
- Alternativ: CX52 (16 GB RAM) für ~28 €/Mo als Zwischenstufe

---

## Phase B — Lokales LLM als Swarm-Backbone

Statt Claude API für jeden der 50–200 Agenten → zu teuer.
Lösung: **Lokales LLM via Ollama** für Swarm-Agenten, Claude nur für finale Synthese.

```
Swarm-Agenten (50–200x):    Ollama lokales Modell (z.B. Llama 3.1 8B)
Synthese & Entscheidung:    Claude Haiku (günstig) oder Opus (für wichtige Thesen)
```

### Setup
```bash
# Ollama Installation auf VPS
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.1:8b          # ~5 GB, schnell
ollama pull mistral-nemo:12b     # ~7 GB, besser für Finanzkontext
```

**Kostenvergleich:**
- Jetzt (leicht): ~0,002 € pro Conviction-Check (1x Haiku-Call)
- Vollausbau mit Claude: ~0,50 € pro Trade (200 Agenten × Haiku)
- Vollausbau mit Ollama: ~0,00 € pro Trade (lokal) + 1x Haiku für Synthese

---

## Phase C — Agent-Typen (erweitertes Persona-System)

Statt 4 Personas (aktuell) → 8 spezialisierte Agent-Typen:

| Agent-Typ | Anzahl | Verhalten | Gewichtung |
|---|---|---|---|
| Retail Momentum | 30% | FOMO-getrieben, kauft Breakouts | 20% |
| Retail Value | 10% | kauft "günstig", hält lange | 10% |
| Institutional Long | 20% | fundamentalgetrieben, quartalsweise | 25% |
| Hedge Fund | 15% | short-term, mean-reversion | 20% |
| Algo Momentum | 10% | rein technisch, EMA/RSI-getrieben | 15% |
| Contrarian | 5% | fadet crowded trades | 5% |
| News Trader | 5% | reagiert auf Headlines in Echtzeit | 3% |
| Market Maker | 5% | liquidity provider, fade extremes | 2% |

---

## Phase D — Graph-Memory (Zep Cloud oder lokal)

Aktuell: kein Agent-Memory (jeder Call ist stateless).
Vollausbau: Agenten erinnern sich an vergangene Thesen.

```
"Retail-Agent #47 hat PS17 (Energy Transition) 3x erfolgreich getradet
→ erhöhtes Vertrauen in ähnliche Thesen"
```

**Optionen:**
1. **Zep Cloud** (managed): ~20 €/Mo, einfachste Integration
2. **ChromaDB lokal**: kostenlos, vector store für Agent-Memory
3. **SQLite mit Embedding**: einfachste Option, auf unserem Stack aufbauend

**Empfehlung**: ChromaDB wenn wir auf CCX33 upgraden.

---

## Phase E — Scenario-Injection (live Makro-Events)

Vollausbau: Albert "injiziert" live Makro-Events in den Swarm, bevor er tradet.

```python
# Beispiel-Flow
event = "Fed erhöht Zinsen um 25bps, unerwartet hawkish Statement"
swarm_result = run_swarm_simulation(
    event=event,
    thesis="S2",          # EU Defense
    n_agents=100,
    duration_steps=50     # 50 Interaktionsrunden
)
# Swarm: 73% bullish für EU Defense (Fed-Stärke = USD-Stärke = EUR-Schwäche = EU-Defense unabhängig)
# Albert: erhöht Position-Size für S2-Trades
```

---

## Phase F — Polymarket-Integration als Validierung

Polymarket-Preise als Ground-Truth für Crowd-Sentiment nutzen:
- Wenn Swarm-Simulation und Polymarket-Konsens übereinstimmen → höchste Conviction
- Wenn sie divergieren → Albert wartet auf Auflösung

```python
# Polymarket API (kostenlos, public)
polymarket_sentiment = fetch_polymarket_odds("EU defense spending increase 2026")
swarm_sentiment = run_swarm(thesis="S2")
if abs(polymarket_sentiment - swarm_sentiment) > 20:
    # Divergenz — warte auf Auflösung, kleinere Position
```

---

## Umsetzungs-Reihenfolge wenn bereit

```
1. VPS-Upgrade auf Hetzner CX52 (16 GB RAM) → ~28 €/Mo
   → Ollama läuft, lokales LLM verfügbar

2. thesis_discovery.py: Ollama statt Claude für Thesis-Generierung
   → spart ~10 €/Mo API-Kosten

3. crowd_reaction.py: 4 Personas → 8 Personas via Ollama
   → vollständigeres Bild, null Mehrkosten

4. Agent-Memory mit ChromaDB
   → Agenten "lernen" welche Thesen historisch gut/schlecht waren

5. Polymarket-Integration als Validierungs-Layer

6. Vollständiger Swarm: 50–200 Agenten, Interaction-Loops, Emergenz-Report
```

---

## Kosten-Nutzen bei Vollausbau

| Szenario | Monatliche Kosten | Erwarteter Nutzen |
|---|---|---|
| Jetzt (leicht) | ~20 €/Mo (VPS + API) | Conviction-Verbesserung ~10-15% |
| Stufe 1 (CX52 + Ollama) | ~35 €/Mo | Conviction ~20-25% besser |
| Vollausbau (CCX33 + Swarm) | ~80–100 €/Mo | Conviction ~30-40% besser, Crowd-Timing |

**Break-even**: Wenn Albert durch bessere Conviction 1-2 schlechte Trades/Monat vermeidet,
rechtfertigt das bereits den Vollausbau (1 schlechter Trade ≈ 200–500 € Opp.Cost).

---

## Notizen

- MiroFish-Repo: https://github.com/666ghj/MiroFish (Open Source, MIT-Lizenz)
- Offline-Fork (Ollama): https://github.com/nikmcfly/MiroFish-Offline
- OASIS Framework (Basis): https://github.com/camel-ai/oasis
- Dieser Plan wurde April 2026 erstellt, Review empfohlen wenn VPS-Upgrade ansteht
