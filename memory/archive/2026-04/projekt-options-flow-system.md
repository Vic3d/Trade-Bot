# Projekt: Options Flow Intelligence System
**Angelegt:** 2026-03-24 | **Status:** 🔵 Planung / Bauphase
**Beteiligte:** Victor (Lead), Albert (Architektur + Umsetzung)

---

## 🎯 Vision

Ungewöhnlicher Options-Flow (hoher Call-Kauf vor Marktereignissen) wird als
**Lead-Indikator** in das bestehende TradeMind-System integriert:

1. **Erkennen** — Scanner detektiert frische OTM-Calls mit hohem Volumen
2. **Validieren** — Automatisch Paper Trade eröffnen, Outcome tracken
3. **Lernen** — Accuracy wächst mit jedem Signal → schlechte Signale werden gefiltert
4. **Handeln** — Erst wenn Signal nachweislich >60% Trefferquote hat: echte Alerts

---

## 🏗️ Architektur — Gesamtbild

```
┌─────────────────────────────────────────────────────────────────┐
│                    OPTIONS FLOW PIPELINE                        │
│                                                                 │
│  [Yahoo Finance]  →  [Flow Scanner]  →  [Signal Evaluator]     │
│  (alle 30 Min)        (Vol/OI Ratio)     (Qualitäts-Filter)    │
│                                                 │               │
│                        ┌────────────────────────┤               │
│                        ↓                        ↓               │
│                  [Paper Trade]          [Discord Alert]         │
│                  (automatisch)          (wenn Accuracy >60%)    │
│                        │                                        │
│                        ↓                                        │
│                  [Paper Monitor]                                │
│                  (24-48h tracking)                              │
│                        │                                        │
│                        ↓                                        │
│                  [Outcome Validator]                            │
│                  (WIN / LOSS / PARTIAL)                         │
│                        │                                        │
│                        ↓                                        │
│                  [lag_knowledge.json]   ←──── Feedback Loop ───┤
│                  (accuracy_pct wächst)                          │
│                        │                                        │
│                        ↓                                        │
│                  [Signal Quality Filter]                        │
│                  (blockiert schwache Signale)                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📦 Komponenten

### Bereits vorhanden ✅
| Datei | Funktion |
|---|---|
| `scripts/options_flow_scanner.py` | Erkennt ungewöhnlichen Call-Flow (Vol/OI) |
| `scripts/paper_trading.py` | Virtuelles Trade-System (LONG/SHORT, Stop, Target) |
| `scripts/paper_monitor.py` | Überwacht Paper Trades gegen Live-Kurse |
| `scripts/signal_tracker.py` | Lead-Lag Signal Tracking + Outcome |
| `data/lag_knowledge.json` | Accuracy-Datenbank pro Signal-Pair |
| `data/signals.json` | Aktive + erledigte Signale |
| Cron: Options Flow (alle 30 Min) | Scan läuft bereits |

### Neu zu bauen 🔨
| Datei | Funktion | Priorität |
|---|---|---|
| `scripts/options_flow_bridge.py` | Verbindet Flow-Scanner → Paper Trade → lag_knowledge | 🔴 P1 |
| `data/lag_knowledge.json` (Erweiterung) | Neue Pairs: OPTIONS_FLOW_OIL, OPTIONS_FLOW_ENERGY | 🔴 P1 |
| `scripts/options_flow_validator.py` | Prüft 24h/48h nach Signal: Hat Underlying sich bewegt? | 🟡 P2 |
| `dashboard/options_flow_tab.html` | Visualisierung im TradeMind Dashboard | 🟢 P3 |

---

## 🔴 Phase 1 — Bridge: Flow → Paper Trade (sofort)

**Datei:** `scripts/options_flow_bridge.py`

**Logik:**
```python
# Wenn Flow-Scanner Alarm auslöst:
if hit["ticker"] in OIL_PROXY_MAP and signal_quality_ok(hit["ticker"]):
    paper_trade = {
        "asset":     OIL_PROXY_MAP[hit["ticker"]],  # z.B. USO → EQNR.OL
        "direction": "LONG",
        "entry":     current_price,
        "stop":      current_price * 0.95,   # 5% Stop
        "target":    current_price * 1.08,   # 8% Ziel = CRV 1.6
        "horizon_h": 48,                     # 48h Bewertungshorizont
        "trigger":   f"OptionsFlow_{hit['ticker']}_{hit['strike']}",
        "source":    "options_flow_scanner"
    }
    create_paper_trade(paper_trade)
    register_signal_in_lag_knowledge(hit)
```

**Proxy-Mapping (Options-Ticker → unser Trading-Instrument):**
```
USO  → EQNR.OL  (Öl-Proxy in Victors Universum)
XOM  → EQNR.OL  (ähnliches Exposure)
OXY  → EQNR.OL
XLE  → EQNR.OL  (Energie-Sektor)
BNO  → EQNR.OL  (Brent-direkt → Equinor)
CVX  → EQNR.OL
```
→ Konsolidiert: alles läuft auf EQNR.OL raus (Victors Haupt-Öl-Vehicle)

---

## 🔴 Phase 1 — lag_knowledge Erweiterung

Neue Pairs in `data/lag_knowledge.json`:

```json
"OPTIONS_FLOW_OIL_SHORT": {
  "lead_ticker": "OPTIONS_FLOW_USO_XOM_OXY",
  "lead_name": "Ungewöhnlicher OTM-Call-Flow (Öl, <7 Tage)",
  "lag_ticker": "EQNR.OL",
  "lag_name": "Equinor ASA",
  "lag_hours": 24,
  "direction": "same",
  "threshold_pct": 1.5,
  "accuracy_pct": null,
  "sample_count": 0,
  "description": "Frische kurzlaufende OTM-Calls → Öl steigt in 24h"
},
"OPTIONS_FLOW_OIL_MEDIUM": {
  "lead_ticker": "OPTIONS_FLOW_XLE_BNO",
  "lead_name": "Ungewöhnlicher OTM-Call-Flow (Energie-ETF, 7-30 Tage)",
  "lag_ticker": "EQNR.OL",
  "lag_name": "Equinor ASA",
  "lag_hours": 48,
  "direction": "same",
  "threshold_pct": 2.0,
  "accuracy_pct": null,
  "sample_count": 0,
  "description": "Mittelfristige Energie-Calls → Öl steigt in 48h"
}
```

---

## 🟡 Phase 2 — Validator (nach 24h/48h)

**Datei:** `scripts/options_flow_validator.py`

**Läuft:** täglich 22:00 CET (nach Xetra-Schluss)

**Logik:**
```
1. Lade alle offenen options-flow-getriggerten Paper Trades
2. Prüfe: Ist Horizont (24h / 48h) abgelaufen?
3. Wenn ja: Hole aktuellen Kurs EQNR.OL
4. Vergleiche: entry_price vs. current_price
   - +1.5% oder mehr → WIN
   - -1.5% oder weniger → LOSS  
   - Dazwischen → NEUTRAL (nicht gewertet)
5. Update lag_knowledge.json: accuracy_pct, sample_count, wins, losses
6. Discord: Zusammenfassung (wenn >3 neue Ergebnisse)
```

---

## 🟡 Phase 2 — Signal Quality Filter

In `options_flow_scanner.py` ergänzen:

```python
def signal_quality_ok(pair_id: str) -> bool:
    """Gibt nur True wenn Signal-Qualität ausreichend ist."""
    knowledge = load_lag_knowledge()
    pair = knowledge["pairs"].get(pair_id)
    if not pair:
        return True  # Neue Signale immer durchlassen (Lernphase)
    
    samples = pair["sample_count"]
    accuracy = pair["accuracy_pct"]
    
    if samples < 10:
        return True   # Noch keine Datenbasis → immer zeigen, Paper Trade erstellen
    if samples >= 10 and accuracy >= 55:
        return True   # Bewährt genug
    return False      # Schlechte Signal-Qualität → blockieren
```

**Konsequenz:**
- Erste 10 Signale: immer alertieren (Lernphase)
- Ab Sample 11: nur noch wenn Accuracy ≥55%
- Discord-Alerts nur bei Accuracy ≥60%

---

## 🟢 Phase 3 — Dashboard Integration

Tab in TradeMind Dashboard: **"Flow Intelligence"**

Zeigt:
- Letzte 10 Options-Flow-Signale (Ticker, Strike, Vol, OI, Zeit)
- Accuracy pro Signal-Typ (Kuchen-Chart: WIN/LOSS/PENDING)
- Aktueller Qualitäts-Score: 🟢 Verlässlich / 🟡 Lernend / 🔴 Gesperrt
- Paper-Trade-Tabelle: alle flow-getriggerten Trades + Outcomes

---

## 📊 Erwartete Lernkurve

```
Sample  0-10:  Lernphase — alle Signale aktiv, kein Filter
Sample 10-20:  Kalibrierung — erste Qualitätsscores sichtbar
Sample 20-50:  Optimierung — schlechte Signal-Typen fallen raus
Sample 50+:    Verlässlich — Accuracy-Baseline für echte Trade-Entscheidungen
```

Bei täglichen Scans (14:00-21:30, 30-Min-Intervall = max. 15 Scans/Tag):
→ 10 Samples nach ca. **3-5 Handelstagen**
→ 20 Samples nach ca. **1-2 Wochen**
→ Erste verlässliche Accuracy-Aussage nach **2-3 Wochen**

---

## 🔗 Integration in Gesamt-Strategie

Wie fließt das in Victors Trading-Entscheidungen?

```
HEUTE (manuell):
  Victor fragt → Albert analysiert → Victor entscheidet

MIT OPTIONS FLOW SYSTEM:
  Options-Flow-Alarm → Albert analysiert Kontext →
  "Flow + Iran-Lage + Tanker-Argument = 3 Bullish-Faktoren" →
  Klare Empfehlung mit Konfidenz-Score

KONFIDENZSYSTEM (geplant):
  Jeder Faktor gibt Punkte:
  + Bullisher Options-Flow    → +2 Punkte
  + Iran-Eskalation           → +2 Punkte
  + Tanker-Engpass            → +1 Punkt
  + Brent >$100               → +1 Punkt
  + EQNR Momentum positiv     → +1 Punkt
  ─────────────────────────────
  GESAMT: 7/10 → "STARKER EINSTIEG"
  
  Schwelle für Alarm: ≥5/10
  Schwelle für "volle Position": ≥7/10
```

---

## 📅 Umsetzungsplan

| Woche | Was | Ergebnis |
|---|---|---|
| KW 13 (diese Woche) | `options_flow_bridge.py` bauen, lag_knowledge erweitern, Cron verbinden | Scanner → Paper Trade läuft automatisch |
| KW 13-14 | Lernphase: System sammelt Daten still im Hintergrund | 10-20 Samples |
| KW 14-15 | `options_flow_validator.py` bauen + Accuracy-Tracking live | Erste Qualitätsaussagen |
| KW 15+ | Signal Quality Filter aktivieren, Dashboard-Tab | Selbst-optimierendes System |

---

## 📝 Offene Fragen

- [ ] Paperclip wieder starten? (signal_tracker.py nutzt localhost:53476) — oder durch direktes signals.json-Writing ersetzen?
- [ ] Konfidenz-Score: Welche weiteren Faktoren soll das System messen?
- [ ] Soll der Bridge auch PUT-Flow tracken? (würde Short-Signale erzeugen)
- [ ] Zielgröße Paper Trade bei Flow-Signal: immer 1000€ virtuell oder dynamisch?
