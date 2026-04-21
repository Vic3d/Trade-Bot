# Thesis-basierter Trading-Workflow
**Einzige Art von Strategie die wir verfolgen — seit Phase 22 (21.04.2026)**

> *"Nur solche Strategien haben Erfolg. Die muessen sauber ausgearbeitet werden, und dann muss man traden."* — Victor

## Warum dieses Dokument existiert

Case Study STLD (Steel Dynamics): Strategie PS_STLD hatte eine saubere Makro-These (Trump Liberation Day + Section 232 = US-Stahl-Tariff-Hebel). Das System hat sie nach 3 fruehen Verlust-Trades am 31.03. gelockt — **3 Tage bevor der Hauptkatalysator (02.04.) gefeuert hat**. Ergebnis: STLD +22% in 3 Wochen, System nicht dabei. Victor war manuell drin.

Diese Sorte "Katalysator-These" ist die einzige mit messbar positivem Edge in unserem Learning Loop. Momentum-Chasing, Day-Trading, Auto-Rotation — alles geblockt/suspended (WR 25-43%). **Thesen-Plays PS1, PS11, PS17, PS18: 56-100% WR.**

## Die 6-Schritt-Pflicht vor jeder These

Eine These ist NICHT traderisch bis alle 6 Schritte dokumentiert sind in `data/strategies.json`:

### 1. Makro-Katalysator benennen
Ein konkretes, datierbares Ereignis. Nicht "Trump mag keine Importe" sondern **"Section 232 25%-Stahlzoelle am 12.03. implementiert, Liberation Day Universal-Tariffs am 02.04."**

Feld: `catalyst.date` + `catalyst.event`

### 2. Logische Kette (5-6 Schritte)
Von Katalysator → Profit. Jeder Schritt muss falsifizierbar sein:
- Trump setzt Zoelle durch
- US-Importe sinken
- US-Inlandspreise steigen (Operating Leverage)
- US-Produzenten (STLD, NUE, CLF) profitieren ueberproportional
- Q1-Earnings bestaetigen → Konsens-Revision → Multiple-Expansion

Feld: `genesis.logical_chain` + `genesis.analysis_steps`

### 3. Kill-Trigger (konkret, quantifiziert)
Unter welcher Bedingung begraben wir die These sofort?
- "Tariff-Rollback-Meldung aus Weissem Haus" (politisch)
- "STLD dauerhaft unter $155" (preislich)
- "HRC-Preis unter $900" (fundamental)

Feld: `kill_trigger` + `negation`

### 4. Kommoditaets-/Fundament-Treiber
Was ist das tatsaechliche **Preissignal** im Markt das die These validiert?
STLD: **HRC Hot-Rolled-Coil Spot** — jeder +$100/Ton = +$5-6 EPS. Das ist der harte Hebel.
PS1: **Brent Crude** — Iran-Spannungen → Oelpreis → Exxon/TotalEnergies-Margen.
PS3: **EU Defense-Budgets** — NATO 2%-Commitments → Rheinmetall/BAE Auftragsbuecher.

Feld: `catalyst.commodities` → queryable gegen `commodity_prices` SQL-Tabelle.

### 5. EPS/Bewertung-Szenarien (3 Cases)
Ohne Bull/Base/Bear-Szenarien KEINE These.
PS_STLD: conservative $9.70 / bull $12.55 / peak $15.97 EPS + implied KGV → Kursziele.

Feld: `eps_scenarios`

### 6. Horizont + Entry-Trigger
Nicht "irgendwann" sondern **"T1: 30.03. US-Open bei stabilem Kurs, T2: nach April-2-Ankuendigung, T3: nach Q1 Earnings mid-April"**.
Katalysator-Horizon in Tagen: PS_STLD 60d, PS1 90d, PS3 120d.

Feld: `entry_trigger` + `catalyst.horizon_days`

## Das neue Lock-Verhalten (Phase 22)

Eine Strategie kann **raw_locked=true** sein, aber das System handelt sie trotzdem wenn der Katalysator noch pending oder frisch ist:

| Catalyst-State | Bedeutung | Lock-Override |
|---|---|---|
| **PENDING** | date > today, noch nicht gefeuert | ✅ Lock bypass — These hatte keine Chance |
| **PENDING_SECONDARY** | Earnings o.Ae. in <14d | ✅ Lock bypass — Hauptevent noch voraus |
| **FRESH** | fired vor ≤14 Tagen | ✅ Lock bypass — These braucht Zeit |
| **MATURE** | 14-horizon_days nach fire | ❌ Lock steht — These hatte Runway |
| **STALE** | > horizon_days | ❌ Lock steht — These abgelaufen |

API: `intelligence.catalyst_utils.is_effectively_locked(strategy)` → `(bool, reason)`

Die 3 Lock-Enforcement-Punkte in `ceo.py`, `entry_gate.py`, `strategy_validator.py` rufen jetzt alle diese Funktion auf.

## Post-Catalyst Re-Evaluation (Auto-Job)

Taeglich 08:00 CET laeuft `scripts/intelligence/catalyst_reeval.py`:

1. **Auto-Fire:** Katalysator-Datum <= today → setze `fired=True, fired_date=today`
2. **Queue Deep Dive:** 7-9 Tage nach Fire → automatische LLM-Neubewertung
3. **Alert Expiry:** horizon_days + 7 ueberschritten → Discord-Alert "Thesis expired"

Ergebnis: Strategien werden aktiv ueberprueft sobald ihre These messbare Daten hat, nicht erst beim naechsten Bauchgefuehl.

## Commodity-Prices als First-Class Datasource

Neue Tabelle `commodity_prices (commodity, date, price, unit, source)`.

Seeded mit:
- HRC_STEEL: $680 (Jan) → $1050 (Apr)
- BRENT_OIL: $78 (Feb) → $120 (Apr)
- ISM_MANUFACTURING: 49.2 (Apr)

Deep Dive kann diese Daten joinen statt LLM "keine Fundamentaldaten verfuegbar" auszuspucken.

## Der saubere Trade-Flow

```
News-Event → Thesis Discovery → 6-Schritt-Ausarbeitung → strategies.json
  ↓
Katalysator fired → FRESH-Status 14 Tage Schutz
  ↓
Entry-Trigger erreicht → Deep Dive LLM (mit Commodity-Daten)
  ↓
KAUFEN-Verdict < 14d alt → Paper Trade Engine Guards 0-6 → Entry
  ↓
7 Tage nach Fire → Auto-Re-Eval (queue fuer LLM)
  ↓
Bei Target/Stop/Kill-Trigger → Exit + Postmortem
```

## Was wir NICHT mehr machen

- ❌ Strategie locken nach 3 Trades ohne Katalysator-Check
- ❌ Deep Dive ohne Commodity-/Fundament-Daten
- ❌ Momentum-Entries ohne Makro-These
- ❌ "Watchlist durchscannen" statt News-Funnel
- ❌ Day Trading (alle DT1-DT9 bleiben suspended)

## Victor's Grundsatz

> *"Deep Dive vor jedem Trade. Thesen-basiert. Keine Momentum-Chasing. Stop-Loss ist heilig."*

Jede neue Strategie muss diesen Workflow durchlaufen — sonst wird sie nicht getradet.
