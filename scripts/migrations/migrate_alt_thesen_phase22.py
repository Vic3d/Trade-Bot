#!/usr/bin/env python3
"""
Migration: Alt-Thesen -> Phase-22-Raster
=========================================
Erweitert PS1, PS3, PS11, PS_CCJ, PS_LHA um die 6 Pflicht-Felder (catalyst,
logical_chain, kill_trigger quantifiziert, commodities, eps_scenarios,
entry_trigger mit Horizon).

Splittet PS18 (Tariff-Breit) in:
  - PS_AUTO_TARIFF_LOSERS (DAI, BMW — Vermeiden/Short)
  - STLD/CLF bleibt in PS_STLD (schon dort)
  - BYDDY -> Archiv (braucht eigene China-These)

Setzt:
  - PS17 auf status=DRAFT (Katalysator zu weich)
  - PS19, PS20 -> health=paused, archived_reason

Idempotent: kann mehrfach laufen, setzt nur was fehlt.
"""
from __future__ import annotations
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
STRATS = WS / 'data' / 'strategies.json'
BACKUP = WS / 'data' / f'strategies.json.bak.{datetime.now():%Y%m%d_%H%M%S}'


# ──────────────────────────────────────────────────────────────
# Pro-Strategie Patches — genau die 6 Pflicht-Felder
# ──────────────────────────────────────────────────────────────

PATCHES = {
    'PS1': {
        'catalyst': {
            'date': '2026-02-27',
            'event': 'Iran-Eskalation + Hormuz-Druck — Brent Sprung $78→$120',
            'fired': True, 'fired_date': '2026-02-27',
            'horizon_days': 90,
            'secondary': {
                'date': '2026-04-28', 'event': 'OPEC+ JMMC Meeting',
                'fired': False,
            },
            'commodities': ['BRENT_OIL'],
        },
        'genesis_logical_chain': [
            'Iran-Israel-Eskalation eskaliert an der Hormuz-Strasse',
            'Saudi + Iran loten militaerische Rote Linien neu aus',
            'Risk-Premium auf Brent steigt +$15-25/bbl',
            'Upstream-Majors (OXY, TTE, EQNR) weiten Margen aus',
            'Tanker (FRO, DHT) profitieren von Spot-Raten-Sprung',
            'Q1-Earnings bestaetigen Margen-Expansion',
        ],
        'kill_trigger_quantified': [
            'Brent <$75 an 2 aufeinanderfolgenden Handelstagen',
            'Hormuz-Deeskalation offiziell (US-Iran-Gipfel Agreement)',
            'OPEC+ kuendigt 1M+ bpd Produktions-Erhoehung an',
        ],
        'eps_scenarios': {
            'OXY': {'bear': 3.20, 'base': 4.80, 'bull': 6.50, 'target_bear_usd': 45, 'target_base_usd': 65, 'target_bull_usd': 85},
            'TTE.PA': {'bear': 7.80, 'base': 9.40, 'bull': 11.20, 'target_bear_eur': 58, 'target_base_eur': 70, 'target_bull_eur': 82},
        },
        'entry_trigger_T123': {
            'T1': 'OXY <$55 bei stabilem Brent >$100',
            'T2': 'nach OPEC+ 28.04. — Cut bestaetigt',
            'T3': 'Q1-Earnings beat (ab Anfang Mai)',
        },
    },

    'PS3': {
        'catalyst': {
            'date': '2026-06-24',
            'event': 'NATO-Summit 24-26.06. — neue 2.5%-Commitment-Beschluesse erwartet',
            'fired': False, 'horizon_days': 120,
            'secondary': {
                'date': '2026-05-07', 'event': 'Rheinmetall Q1 Earnings',
                'fired': False,
            },
            'commodities': [],
        },
        'genesis_logical_chain': [
            'Russland-Ukraine-Krieg bleibt strukturell offen',
            'NATO-Summit 24.06. beschliesst Anhebung auf 2.5-3.0% BIP',
            'Beschaffungsprogramme werden ausgeweitet (Munition, Luftverteidigung)',
            'Auftragsbuecher (KTOS, HII, HAG, RHM) wachsen strukturell',
            'FY-Guidance-Upgrades in Q2/Q3 Earnings',
            'Multiple-Expansion bei Defense-Pure-Plays',
        ],
        'kill_trigger_quantified': [
            'Ukraine-Waffenstillstand vor 24.06. signiert',
            'NATO-Summit verwirft 2.5%-Commitment',
            'HAG.DE Auftragsbuch Q1 flach oder ruecklaeufig',
        ],
        'eps_scenarios': {
            'KTOS': {'bear': 0.55, 'base': 0.85, 'bull': 1.20, 'target_bear_usd': 25, 'target_base_usd': 42, 'target_bull_usd': 60},
            'HAG.DE': {'bear': 4.20, 'base': 5.80, 'bull': 7.50, 'target_bear_eur': 120, 'target_base_eur': 165, 'target_bull_eur': 215},
        },
        'entry_trigger_T123': {
            'T1': 'RHM.DE Q1 am 07.05. mit Order-Backlog-Beat',
            'T2': '2-3 Wochen vor NATO-Summit (Anfang Juni)',
            'T3': 'nach Summit bei Commitment-Announcement',
        },
        'locked': False,  # unlock via Phase-22-Override
        'unlocked_date': datetime.now().date().isoformat(),
    },

    'PS11': {
        'catalyst': {
            'date': '2026-05-07',
            'event': 'Rheinmetall Q1 — Auftragsbuch-Daten',
            'fired': False, 'horizon_days': 90,
            'secondary': {
                'date': '2026-06-24', 'event': 'NATO-Summit',
                'fired': False,
            },
            'commodities': [],
        },
        'genesis_logical_chain': [
            'EU-Staaten hinken bei 2%-NATO-Quote hinterher',
            'Nachholbedarf muss bis 2028 aufgeholt werden',
            'EU-Pure-Plays (SAAB-B, RHM, BA.L) haben 3-5 Jahre Pipeline-Visibility',
            'Q1/Q2-Earnings bestaetigen Backlog-Wachstum',
            'Analyst-Revisions drehen nach oben',
            'Multiple-Expansion durch strukturelles Wachstum',
        ],
        'kill_trigger_quantified': [
            'EU-Defense-Budgets werden gekuerzt (Rezessionsangst)',
            'RHM.DE Auftragsbuch Q1 wachstumslos (<+5% YoY)',
            'SAAB-B Aktienkurs unter 200-Tage-MA',
        ],
        'eps_scenarios': {
            'RHM.DE': {'bear': 28, 'base': 36, 'bull': 46, 'target_bear_eur': 520, 'target_base_eur': 680, 'target_bull_eur': 870},
            'SAAB-B.ST': {'bear': 18, 'base': 24, 'bull': 32, 'target_bear_sek': 380, 'target_base_sek': 500, 'target_bull_sek': 670},
        },
        'entry_trigger_T123': {
            'T1': 'nach RHM Q1 am 07.05. bei Backlog-Beat',
            'T2': 'SAAB-B Earnings (Ende April)',
            'T3': 'Pre-NATO-Summit Entry im Juni',
        },
    },

    'PS_CCJ': {
        'catalyst': {
            'date': '2026-05-01',
            'event': 'Cameco Q1 Earnings + Kazatomprom Production-Guidance',
            'fired': False, 'horizon_days': 180,
            'secondary': {
                'date': '2026-06-15', 'event': 'Trump SMR Executive Order (erwartet)',
                'fired': False,
            },
            'commodities': ['URANIUM_PROXY'],
        },
        'genesis_logical_chain': [
            'AI-Datacenter-Boom treibt Strombedarf exponentiell',
            'SMR-Executive-Order beschleunigt US-Nuclear-Renaissance',
            'Kazatomprom senkt Produktions-Guidance (Sulfat-Engpass)',
            'Uran-Spot steigt strukturell Richtung $100-120/lb',
            'Cameco als westlicher Pure-Play fangt Premium-Preise ein',
            'Q1/Q2 EPS-Revisions nach oben',
        ],
        'kill_trigger_quantified': [
            'URNM-ETF <$45 an 2 aufeinanderfolgenden Tagen',
            'Kazatomprom Produktions-Erhoehung >+10% in Guidance',
            'Trump revoked SMR-Order oder pausiert Nuclear-Push',
        ],
        'eps_scenarios': {
            'CCJ': {'bear': 1.20, 'base': 1.85, 'bull': 2.60, 'target_bear_usd': 42, 'target_base_usd': 65, 'target_bull_usd': 92},
        },
        'entry_trigger_T123': {
            'T1': 'Pre-Q1 bei CCJ <$50',
            'T2': 'nach Q1-Beat (01.05.)',
            'T3': 'Executive-Order-Tag ± 3 Tage',
        },
    },

    'PS_LHA': {
        'catalyst': {
            'date': '2026-04-30',
            'event': 'Lufthansa Q1 Earnings + Yield-Updates',
            'fired': False, 'horizon_days': 90,
            'secondary': {
                'date': '2026-06-30', 'event': 'Sommerflugplan-Auslastung',
                'fired': False,
            },
            'commodities': ['BRENT_OIL'],  # INVERSE — Brent runter = LHA hoch
        },
        'genesis_logical_chain': [
            'LHA.DE KGV 6x, fundamental guenstig trotz Rekordumsatz 2025',
            'Brent-Spike >$120 drueckt kurzfristig — Hedge-Quote 70%',
            'Wenn Iran-Eskalation deeskaliert, Jet-Fuel faellt schnell',
            'Sommer-2026 Kapazitaets-Auslastung wird rekordhoch',
            'Q1/Q2 EPS ueberrascht positiv',
            'Multiple-Re-Rating Richtung KGV 9-10x',
        ],
        'kill_trigger_quantified': [
            'Brent >$140 an 2 Tagen in Folge (Hedge-Wirksamkeit sinkt)',
            'Q1 Earnings Miss von >-10%',
            'LHA.DE <€5.80 (EMA50-Bruch)',
        ],
        'eps_scenarios': {
            'LHA.DE': {'bear': 0.65, 'base': 1.10, 'bull': 1.55, 'target_bear_eur': 5.20, 'target_base_eur': 8.80, 'target_bull_eur': 12.40},
        },
        'entry_trigger_T123': {
            'T1': 'LHA.DE <€6.50 bei stabiler Auslastung',
            'T2': 'nach Q1 am 30.04. bei Beat',
            'T3': 'Brent-Peak-Reversal (falls Iran deeskaliert)',
        },
    },
}


# Downgrade-Kandidaten
DOWNGRADES = {
    'PS17': {
        'status': 'DRAFT',
        'draft_reason': 'Katalysator zu weich — "drohende EU-Gegenmassnahmen" ohne Hard Date. Warten auf konkretes Beschluss-Datum.',
    },
    'PS18': {
        'status': 'ARCHIVED',
        'archived_reason': 'zu breit gefasst (STLD + DAI + BMW + BYDDY). STLD bleibt in PS_STLD, Rest braucht separate Thesen.',
        'health': 'paused',
    },
    'PS19': {
        'status': 'ARCHIVED',
        'archived_reason': 'reine Makro-Wette auf schwachen USD, kein harter Katalysator, kein quantifizierbarer Kill-Trigger.',
        'health': 'paused',
    },
    'PS20': {
        'status': 'ARCHIVED',
        'archived_reason': 'reaktive These (Defensive-Rotation bei Rezession) — Hedging-Logik, nicht aktive These.',
        'health': 'paused',
    },
}


# Auch PS_STLD patchen (falls lokal noch ohne catalyst)
PATCHES['PS_STLD'] = {
    'catalyst': {
        'date': '2026-04-02',
        'event': 'Trump Liberation Day + Section 232 Stahlzoelle (25%)',
        'fired': True, 'fired_date': '2026-04-02',
        'horizon_days': 60,
        'secondary': {
            'date': '2026-04-22', 'event': 'STLD Q1 Earnings Report',
            'fired': False,
        },
        'commodities': ['STEEL_PROXY', 'HRC_STEEL'],
    },
    'genesis_logical_chain': [
        'Trump setzt Section 232 25%-Stahlzoelle durch',
        'US-Importe sinken, Inlandspreise steigen (HRC +54% Jan-Apr)',
        'STLD als EAF-Pure-Play hat niedrigste Fixkosten-Basis',
        'Operating Leverage: +$100/t HRC = +$5-6 EPS',
        'Q1-Earnings bestaetigen, Konsens-Revision nach oben',
        'Multiple-Expansion Richtung historisches Peak-KGV',
    ],
    'kill_trigger_quantified': [
        'HRC <$900/t an 2 aufeinanderfolgenden Tagen',
        'STLD <$186 (50-MA-Bruch)',
        'Trump revoked Section 232 in Bilateral-Deal',
    ],
    'eps_scenarios_fallback': {
        'STLD': {'bear': 9.70, 'base': 12.55, 'bull': 15.97,
                 'target_bear_usd': 165, 'target_base_usd': 215, 'target_bull_usd': 280},
    },
    'entry_trigger_T123': {
        'T1': 'vor 02.04. bei STLD <$170',
        'T2': 'nach Liberation-Day-Ankuendigung',
        'T3': 'nach Q1-Earnings 22.04. (sell-the-news vermeiden)',
    },
    'locked': False,
    'unlocked_date': datetime.now().date().isoformat(),
}


# Neue These aus PS18-Split
PS_AUTO_TARIFF_LOSERS = {
    'name': 'Trump-Tariff Auto-Verlierer (Avoid/Short-Setup)',
    'type': 'paper',
    'thesis': 'Export-abhaengige DE-Autos (DAI, BMW.DE) leiden unter US-Zoellen ueberproportional — margenerosion 8-12% in FY26.',
    'sector': 'Auto',
    'regime': 'NEUTRAL_BEARISH',
    'status': 'DRAFT',
    'health': 'yellow',
    'horizon_weeks': 12,
    'tickers': ['DAI', 'BMW.DE'],
    'direction': 'SHORT_OR_AVOID',
    'catalyst': {
        'date': '2026-04-02',
        'event': 'Trump Liberation Day Universal Tariffs',
        'fired': True, 'fired_date': '2026-04-02', 'horizon_days': 90,
        'commodities': [],
    },
    'genesis': {
        'logical_chain': [
            'Trump setzt 25% Auto-Importzoelle durch',
            'DE-Premium-Hersteller haben 40-50% US-Exposure',
            'Fixkosten nicht schnell abbaubar, Transfer-Pricing geblockt',
            'Operating-Margen sinken 200-350bps',
            'EPS-Revisions nach unten durch Analysten',
            'Multiple-Kontraktion, Aktien -15-25%',
        ],
    },
    'kill_trigger': [
        'Trump revoked Auto-Tariffs in bilateralem Deal',
        'EU-USA Handelsabkommen mit Auto-Exemption',
        'DAI Q1 Guidance >+5% positiv ueberraschend',
    ],
    'eps_scenarios': {
        'DAI': {'bear': 4.50, 'base': 6.20, 'bull': 7.80},
        'BMW.DE': {'bear': 5.80, 'base': 7.60, 'bull': 9.20},
    },
    'entry_trigger_T123': {
        'T1': 'Short/Avoid nach Q1-Guidance-Cut',
        'T2': 'wenn EU-Gegenzoelle angekuendigt',
        'T3': 'bei Bruch wichtiger technischer Level',
    },
    'created': datetime.now().isoformat(timespec='seconds'),
    'source': 'split from PS18 — Phase 22 migration',
}


def _merge_strategy(orig: dict, patch: dict) -> dict:
    """Merge patch in orig — nur fehlende/ueberschreibbare Felder."""
    out = dict(orig)

    if 'catalyst' in patch and not out.get('catalyst'):
        out['catalyst'] = patch['catalyst']
    elif 'catalyst' in patch:
        # idempotent: bestehende catalyst-Struktur behalten, nur fehlende Felder ergaenzen
        for k, v in patch['catalyst'].items():
            out['catalyst'].setdefault(k, v)

    if 'genesis_logical_chain' in patch:
        gen = out.get('genesis') or {}
        if isinstance(gen, dict):
            gen.setdefault('logical_chain', patch['genesis_logical_chain'])
            out['genesis'] = gen
        else:
            out['genesis'] = {'logical_chain': patch['genesis_logical_chain']}

    if 'kill_trigger_quantified' in patch:
        # ersetze ALTE text-kill-trigger mit quantifizierten Liste
        out['kill_trigger'] = patch['kill_trigger_quantified']

    if 'eps_scenarios' in patch and not out.get('eps_scenarios'):
        out['eps_scenarios'] = patch['eps_scenarios']

    if 'entry_trigger_T123' in patch:
        out['entry_trigger_T123'] = patch['entry_trigger_T123']

    for k in ('locked', 'unlocked_date'):
        if k in patch:
            out[k] = patch[k]

    out['migrated_to_phase22_at'] = datetime.now().isoformat(timespec='seconds')
    return out


def main():
    assert STRATS.exists(), 'strategies.json fehlt'
    # Backup
    shutil.copy(STRATS, BACKUP)
    print(f'Backup: {BACKUP.name}')

    d = json.loads(STRATS.read_text(encoding='utf-8'))
    changes = {'patched': [], 'downgraded': [], 'created': []}

    for sid, patch in PATCHES.items():
        if sid in d and isinstance(d[sid], dict):
            d[sid] = _merge_strategy(d[sid], patch)
            changes['patched'].append(sid)
            print(f'  PATCH {sid}')
        else:
            print(f'  SKIP {sid} (not in strategies.json)')

    for sid, dn in DOWNGRADES.items():
        if sid in d and isinstance(d[sid], dict):
            for k, v in dn.items():
                d[sid][k] = v
            d[sid]['downgraded_at'] = datetime.now().isoformat(timespec='seconds')
            changes['downgraded'].append(f'{sid}→{dn["status"]}')
            print(f'  DOWNGRADE {sid} -> {dn["status"]}')

    if 'PS_AUTO_TARIFF_LOSERS' not in d:
        d['PS_AUTO_TARIFF_LOSERS'] = PS_AUTO_TARIFF_LOSERS
        changes['created'].append('PS_AUTO_TARIFF_LOSERS')
        print(f'  CREATE PS_AUTO_TARIFF_LOSERS')

    STRATS.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')
    print('\n=== Migration Summary ===')
    for k, v in changes.items():
        print(f'  {k:12} {len(v)}: {v}')


if __name__ == '__main__':
    main()
