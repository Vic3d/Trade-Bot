# Projekt: Overnight-Research-System
**Status:** ✅ Produktiv (2026-03-30)
**Erstellt:** 2026-03-30
**Letztes Update:** 2026-03-30 08:00 MEZ

---

## Was ist das?

Automatisches 3-Stufen-System das nachts News sammelt, filtert und morgens ein Briefing erzeugt.

## Dateien

| Datei | Beschreibung |
|-------|-------------|
| `scripts/overnight_collector.py` | Haupt-Collector: Pipeline → News → overnight_events |
| `scripts/morning_brief_generator.py` | Briefing-Generator: overnight_events → Briefing-Text |
| `scripts/source_ranker.py` | Source-Tier-Ranking (1=Primär, 2=Finanz, 3=Andere) |
| `scripts/entity_extractor.py` | Claude Haiku Entity Extraction |
| `data/trading.db` → `overnight_events` | Strukturierte Event-Datenbank |

## DB-Schema (overnight_events)

```sql
event_id TEXT UNIQUE          -- sha256(headline[:60])[:16]
timestamp TEXT                -- Original-Timestamp aus news_events
headline TEXT                 -- Artikel-Headline
source TEXT                   -- Quell-Name
source_tier INTEGER           -- 1/2/3 (Tier-1 = Reuters/Liveuamap)
entities TEXT                 -- JSON: Claude Haiku Extraktion
strategies_affected TEXT      -- JSON: ["S1", "S2", ...]
impact_direction TEXT         -- bullish_oil | bearish_oil | bullish_defense | ...
novelty_score REAL            -- 0.5-0.90 (1.0 = frisch + hochwertig)
already_known_since TEXT      -- Timestamp wenn Duplikat
briefing_date TEXT            -- YYYY-MM-DD
included_in_briefing INTEGER  -- 0/1
```

## Cron-Jobs

| ID | Name | Schedule | Payload |
|----|------|----------|---------|
| `4ad6c006-c1d2-4fb0-81cf-987ad5dcf241` | Nacht-Collector | 00:00, 02:00, 04:00, 06:00 MEZ | overnight_collector.py |
| `24c0523d-de29-4d9f-afef-62bc883d81f6` | 🌅 Nacht-Briefing | 07:00 MEZ täglich | morning_brief_generator.py → Discord |

## Flow

```
00:00/02:00/04:00/06:00
  → overnight_collector.py
    → news_pipeline.py (frische News in news_events)
    → Letzte 30min aus news_events lesen
    → sha256 event_id + Novelty-Check (24h)
    → Keyword-Matching (IMPACT_RULES + Tier-2 + Tier-3)
    → Source-Ranking (1/2/3)
    → optional: Haiku entity extraction (novelty=1.0 + tier<=2)
    → INSERT OR IGNORE in overnight_events

07:00
  → morning_brief_generator.py
    → overnight_events (heute, novelty>=0.5, sortiert nach Tier)
    → Yahoo Finance: Brent + VIX + EUR/USD
    → state-snapshot.md: Positionen + Alerts
    → night-geo-log.md: optional
    → Formatiertes Briefing → Discord
```

## IMPACT_RULES

| Pattern | Strategies | Direction |
|---------|-----------|-----------|
| Iran + attack/strike/missile | S1 | bullish_oil (0.85) |
| Iran + ceasefire/deal/peace | S1 | bearish_oil (0.80) |
| Hormuz + blocked/mines | S1 | bullish_oil (0.90) |
| tanker/Tanker | S1, S8 | watchlist (0.65) |
| Cuba/Kuba | S9 | watchlist_S9 (0.80) |
| Trump + sanction | S1, S9 | geopolitical_watchlist (0.60) |
| NATO + defense + Rüstung | S2 | bullish_defense (0.70) |
| Fed + cut + Zinssenkung | S3 | bullish_tech (0.75) |
| silver/Silber | S4 | bullish_metals (0.70) |
| oil/kerosin | S10, S11 | bearish_airlines (0.70) |

## Bekannte Issues / Verbesserungen

- "Allgemein"-Gruppe: Events die nur Tier-3 Meta matchen aber keiner Strategie — OK so
- Entity Extractor (Haiku): wird nur bei top Events aufgerufen (novelty=1.0, tier<=2)
- Kuba/Karibik (S9) matched auch auf Taiwan-Nachrichten wenn "Cuba" nicht vorkommt aber S9_Kuba keyword-set "Caribbean" enthält — prüfen
- Deduplication funktioniert: event_id SHA256 über letzten 24h

## Testergebnisse (2026-03-30)

- overnight_collector.py: ✅ 14 neue Events gespeichert (5x Tier-1, 9x Tier-2/3)
- morning_brief_generator.py: ✅ Briefing generiert mit echten Marktdaten (Brent $107.72, VIX 31.05, EUR/USD 1.15)
- Cron 4ad6c006: ✅ Updated
- Cron 24c0523d: ✅ Updated
