#!/usr/bin/env python3
"""
Phase 22 Thesen-Batch 2: AMZN / HOOD / MRVL / BE
==================================================
Fuegt 4 neue Thesen aus Dirk-Mueller-Video-Analyse hinzu.
Alle mit vollem Phase-22-Rahmen: catalyst, kill_trigger_quantified,
eps_scenarios, entry_trigger_T123, genesis_logical_chain.

Schreibt zusaetzlich KAUFEN-Verdicts nach data/deep_dive_verdicts.json
(Analyst=Albert, expires=+14d).

Idempotent: ueberschreibt bestehende Thesen NICHT, nur wenn fehlen.

Usage:
  python3 scripts/migrations/add_phase22_theses_batch2.py
"""
from __future__ import annotations
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
STRATS = WS / 'data' / 'strategies.json'
VERDICTS = WS / 'data' / 'deep_dive_verdicts.json'

TODAY = date.today().isoformat()
EXPIRES = (date.today() + timedelta(days=14)).isoformat()


# ── Die 4 neuen Thesen ─────────────────────────────────────────────────────
NEW_THESES = {
    'PS_AMZN': {
        'name': 'Amazon — E-Com + AWS-KI Base-Breakout',
        'ticker': 'AMZN',
        'tickers': ['AMZN'],
        'sector': 'tech',
        'region': 'US',
        'thesis': (
            'Amazon bildet seit Q4/25 eine 6-Monats-Base auf 210-250$. '
            'AWS-KI-Wachstum (+30% YoY Run-Rate) und stabiles Retail-Margin-Delta '
            '(Marketplace-Fees + Ads) sollten bei Q1-Earnings 29.04. Base-Breakout triggern. '
            'Post-Earnings-Drift-Historie zeigt +7% in 5 Handelstagen nach Beats. '
            'Dirk-Mueller-Pattern: Long-Base + moegliche Konsolidierung nach Zahlen = Einstieg.'
        ),
        'description': 'AWS-Wachstum treibt Base-Breakout nach Q1-Earnings 29.04.',
        'catalyst': {
            'date': '2026-04-29',
            'event': 'Q1 Earnings Report (29.04. nach US-Close)',
            'fired': False,
            'horizon_days': 14,
            'secondary': {
                'earnings_date': '2026-07-30',
                'secondary_events': ['AWS re:Invent 2026 Dec', 'Prime Day Juli']
            },
            'commodities': []  # keine Commodity-Abhaengigkeit
        },
        'genesis_logical_chain': [
            '1. AWS Q1 Run-Rate >$130B erwartet (+29-32% YoY) — Capex-Story fuer KI-Infra belegt',
            '2. Retail-Margin faellt nicht unter 5% (Rekord Q4/25: 5.9%)',
            '3. Advertising-Revenue wird als separater Segment-Reporter ausgewiesen — strukturelles Margin-Upside',
            '4. Base auf 210-250$ seit 6 Monaten — klassisches Minervini-Cup-with-Handle',
            '5. Mid-Term-Election-Year-Statistik S&P +36% Ø nach Q2 spricht fuer Tech-Ausbruch',
            '6. Trigger: Q1-Beat + AWS-Guide >$135B → Breakout ueber 260$ = Trend-Fortsetzung bis 300-320$'
        ],
        'kill_trigger_quantified': [
            'AMZN <$228 (50-Tage-MA-Bruch) an 2 aufeinanderfolgenden Handelstagen',
            'AWS Q1 Growth <25% YoY (Wachstumsverlangsamung bestaetigt)',
            'Retail-Operating-Margin <4.5% (Cost-Kontrolle verloren)'
        ],
        'kill_trigger': [
            'AMZN <$228 (50MA) an 2 aufeinanderfolgenden Tagen',
            'AWS Q1 Growth <25% YoY',
            'Retail-Operating-Margin <4.5%'
        ],
        'eps_scenarios': {
            'bear': {'eps': 1.20, 'multiple': 35, 'target_price': 210, 'probability': 0.20},
            'base': {'eps': 1.45, 'multiple': 40, 'target_price': 290, 'probability': 0.55},
            'bull': {'eps': 1.75, 'multiple': 45, 'target_price': 350, 'probability': 0.25}
        },
        'entry_trigger': 'Post-Earnings 29.04.: Base-Breakout >$260 bei Beat + positiver AWS-Guide',
        'entry_trigger_T123': {
            'T1': 'AMZN <$245 pre-earnings (Gap-down als Kaufgelegenheit in Long-Base)',
            'T2': 'nach Q1 am 29.04. bei Beat & Raise',
            'T3': 'Breakout >$260 mit Volumen (Dirk-Mueller-VCP-Trigger)'
        },
        'target_price': 290,
        'stop_pct': 7.0,
        'position_size_pct': 5,
        'holding_days_max': 30,
        'holding_range': '5-20d',
        'style': 'thesis_play',
        'health': 'active',
        'locked': False,
        'political_risk_flag': False,
        'created_at': TODAY,
        'source': 'dirk_mueller_video_2026-04-22 + AWS-KI-Analyse',
    },

    'PS_HOOD': {
        'name': 'Robinhood — Retail-Broker + Crypto-Beta',
        'ticker': 'HOOD',
        'tickers': ['HOOD'],
        'sector': 'financials',
        'region': 'US',
        'thesis': (
            'Robinhood ist Top-Retail-Broker mit 26M aktiven Usern und profitiert '
            'doppelt: (a) Crypto-Volumina treiben Transaction-Revenue (>40% YoY Q4/25), '
            '(b) Zinsertraege auf 24B Kundencash bleiben hoch. Aktie schon +180% vom 2024-Tief, '
            'bildet jetzt Flagge nach letztem Breakout. Ziel: $100 vor Crypto-Halving-Cycle-Top. '
            'Fundamental stark (GAAP-profitabel seit 3 Quartalen) — nicht reine Beta.'
        ),
        'description': 'Retail-Broker + Crypto-Proxy, Flagge nach Breakout, Ziel $100',
        'catalyst': {
            'date': '2026-05-07',
            'event': 'Q1 Earnings Anfang Mai',
            'fired': False,
            'horizon_days': 14,
            'secondary': {
                'earnings_date': '2026-07-30',
                'secondary_events': ['BTC Halving-Cycle-Top erwartet H2/26', 'Crypto-ETF-Expansion']
            },
            'commodities': ['BTC']
        },
        'genesis_logical_chain': [
            '1. Q4/25 Crypto-Transaction-Revenue $250M (+76% YoY) — struktureller Trend, nicht Einmaleffekt',
            '2. Net-Interest-Income $350M/Q stabil bei Fed Funds >4.5% — Zins-Rueckenwind bleibt 2026',
            '3. GAAP-Net-Income $400M in Q4/25 — kein Cash-Burn-Risiko mehr (Unterschied zu 2022)',
            '4. 26M MAU und wachsend — neue Produkte (Futures, Retirement, EU-Expansion)',
            '5. Aktie konsolidiert nach +180%-Lauf in sauberer Flagge — Dirk-Mueller-Setup',
            '6. BTC-Halving-Cycle-Top historisch 12-18m nach Halving (April 2024) = Q2-Q4/26 → Peak-Volumes vor uns'
        ],
        'kill_trigger_quantified': [
            'BTC <$55k an 2 Tagen in Folge (Crypto-Revenue-Basis weg)',
            'HOOD <$72 (50-Tage-MA-Bruch)',
            'Q1 Transaction-Revenue YoY <+20% (Momentum verloren)'
        ],
        'kill_trigger': [
            'BTC <$55k an 2 Tagen in Folge',
            'HOOD <$72 (50MA)',
            'Q1 Transaction-Revenue YoY <+20%'
        ],
        'eps_scenarios': {
            'bear': {'eps': 1.10, 'multiple': 45, 'target_price': 55, 'probability': 0.20},
            'base': {'eps': 1.40, 'multiple': 65, 'target_price': 95, 'probability': 0.55},
            'bull': {'eps': 1.80, 'multiple': 70, 'target_price': 125, 'probability': 0.25}
        },
        'entry_trigger': 'Flaggen-Breakout >$92 mit Volumen ODER Pullback zu EMA21 bei <$80',
        'entry_trigger_T123': {
            'T1': 'HOOD <$80 in Pullback zu EMA21 (Dirk-Setup)',
            'T2': 'nach Q1 Anfang Mai bei Transaction-Revenue-Beat',
            'T3': 'Flaggen-Breakout >$92 mit >=1.5x Avg-Volumen'
        },
        'target_price': 100,
        'stop_pct': 8.0,
        'position_size_pct': 4,
        'holding_days_max': 45,
        'holding_range': '10-30d',
        'style': 'thesis_play',
        'health': 'active',
        'locked': False,
        'political_risk_flag': False,
        'created_at': TODAY,
        'source': 'dirk_mueller_video_2026-04-22 + BTC-Cycle-Analyse',
    },

    'PS_MRVL': {
        'name': 'Marvell — Custom-Silicon fuer Hyperscaler',
        'ticker': 'MRVL',
        'tickers': ['MRVL'],
        'sector': 'tech',
        'region': 'US',
        'thesis': (
            'Marvell ist Hidden-Champion im Custom-Silicon-Rennen: Design-Wins bei AWS Trainium 3, '
            'Google TPU v6, Microsoft Cobalt. Data-Center-Revenue-Anteil von 40% (2023) auf '
            '~75% (Q1/26e) gestiegen. Aktie +97% vom 2025-Tief, dann Basis-Breakout, jetzt '
            'Konsolidierung — klassisches Dirk-Mueller Post-Base-Pullback-Setup. '
            'Hyperscaler-Capex-Guides fuer FY26 bestaetigen >$300B Markt → MRVL direkter Profiteur.'
        ),
        'description': 'Custom-ASIC Hidden-Champion, Post-Base-Konsolidierung vor Q1',
        'catalyst': {
            'date': '2026-05-28',
            'event': 'Q1 FY26 Earnings Ende Mai + Guide',
            'fired': False,
            'horizon_days': 21,
            'secondary': {
                'earnings_date': '2026-08-28',
                'secondary_events': ['OCP Summit Oct 2026', 'AWS re:Invent Dec']
            },
            'commodities': []
        },
        'genesis_logical_chain': [
            '1. AWS Trainium-3 Production-Ramp H2/26 — MRVL ist Alleinauftraggeber fuer Interconnect-Fabric',
            '2. Google TPU v6 Design-Win bestaetigt (Analyst-Day Jan 26) — Revenue ab Q3/26',
            '3. Optical-Interconnect (800G/1.6T) = Moat, da TSMC-advanced-node-Expertise',
            '4. Hyperscaler-Capex-Guides FY26: META 60-65B, GOOGL 75B, MSFT 80B, AMZN 100B+ → >$320B Markt',
            '5. Aktie konsolidiert bei 150 nach Ausbruch aus 5-Jahres-Base — Minervini-VCP im Entstehen',
            '6. Q1-Guide muss Data-Center-Revenue >$1.8B zeigen → Sprung ueber 175 = Trend bis 220'
        ],
        'kill_trigger_quantified': [
            'MRVL <$140 (50-Tage-MA-Bruch) an 2 Tagen',
            'Data-Center-Revenue Q1 <$1.5B (Growth-Slowdown)',
            'Hyperscaler-Capex-Cut-Ankuendigung (MSFT/AWS/GOOGL guidance-cut)'
        ],
        'kill_trigger': [
            'MRVL <$140 (50MA) an 2 Tagen',
            'Data-Center-Revenue Q1 <$1.5B',
            'Hyperscaler-Capex-Cut-Ankuendigung'
        ],
        'eps_scenarios': {
            'bear': {'eps': 0.50, 'multiple': 40, 'target_price': 120, 'probability': 0.20},
            'base': {'eps': 0.75, 'multiple': 55, 'target_price': 175, 'probability': 0.55},
            'bull': {'eps': 0.95, 'multiple': 65, 'target_price': 230, 'probability': 0.25}
        },
        'entry_trigger': 'Pullback zu EMA21 <$145 ODER Breakout >$158 nach Volumen-Konsolidierung',
        'entry_trigger_T123': {
            'T1': 'MRVL <$145 in Pullback zu 50MA (Post-Base-Entry)',
            'T2': 'Breakout >$158 mit Volumen (Flaggen-Ausbruch)',
            'T3': 'nach Q1 am 28.05. bei DC-Revenue-Beat >$1.8B'
        },
        'target_price': 195,
        'stop_pct': 8.0,
        'position_size_pct': 5,
        'holding_days_max': 45,
        'holding_range': '10-30d',
        'style': 'thesis_play',
        'health': 'active',
        'locked': False,
        'political_risk_flag': False,
        'created_at': TODAY,
        'source': 'dirk_mueller_video_2026-04-22 + Hyperscaler-Capex-Analyse',
    },

    'PS_BE': {
        'name': 'Bloom Energy — Brennstoffzellen fuer Data-Center-Power',
        'ticker': 'BE',
        'tickers': ['BE'],
        'sector': 'energy',
        'region': 'US',
        'thesis': (
            'Bloom Energy profitiert vom Data-Center-Power-Shortage: SOFCs (Solid Oxide Fuel Cells) '
            'liefern 24/7 On-Site-Power und umgehen 5-7 Jahre Grid-Connection-Delays. Oracle/Equinix '
            'PPAs bestaetigen: 1GW Pipeline bis 2028. Aktie aus Multi-Jahres-Base raus, '
            'Shakeout-Low gehalten, jetzt Konsolidierung nach Lauf — Dirk-Mueller Flagge-Pattern. '
            'Nuclear-Plays sind 10+ Jahre Horizont, BE ist "brueckentechnologie" mit 12-18m Deployment-Zyklen.'
        ),
        'description': 'SOFC-Power fuer AI-DataCenter, Shakeout-recovery + Flagge',
        'catalyst': {
            'date': '2026-05-12',
            'event': 'Q1 Earnings + neuer Hyperscaler-PPA erwartet',
            'fired': False,
            'horizon_days': 21,
            'secondary': {
                'earnings_date': '2026-08-07',
                'secondary_events': ['Data-Center-Expo Sept 2026', 'DOE-Grants-Entscheidung']
            },
            'commodities': ['NATGAS']  # SOFCs laufen primaer auf Erdgas
        },
        'genesis_logical_chain': [
            '1. AI-Data-Center-Power-Demand +160% bis 2030 (IEA-Estimate) → 40GW zusaetzlich US-only',
            '2. Grid-Interconnect-Queues 5-7 Jahre → On-Site-Power ist einziger Quick-Fix',
            '3. BE/AEP/Oracle-PPA Q4/25: 1GW bis 2028 — Validation der Thesis',
            '4. SOFCs 65% effizienter als Gas-Peaker, emissionsarmer, modularer Ausbau',
            '5. Aktie aus 4-Jahres-Base raus, Shakeout bei $210, jetzt Flagge bei $220 — Dirk-VCP',
            '6. Q1 + weiterer PPA-Announce = Breakout >$235 → Trend bis $280-320 (Analysten-PT ~$270)'
        ],
        'kill_trigger_quantified': [
            'BE <$198 (50-Tage-MA + Shakeout-Low-Bruch) an 2 Tagen',
            'NATGAS >$6/MMBtu fuer 2 Wochen (SOFC-Economics kaputt)',
            'Hyperscaler-PPA in Q1 canceled/revised (Demand-Indikator)'
        ],
        'kill_trigger': [
            'BE <$198 (50MA) an 2 Tagen',
            'NATGAS >$6/MMBtu fuer 2 Wochen',
            'Hyperscaler-PPA canceled/revised'
        ],
        'eps_scenarios': {
            'bear': {'eps': 0.15, 'multiple': 90, 'target_price': 180, 'probability': 0.25},
            'base': {'eps': 0.30, 'multiple': 100, 'target_price': 260, 'probability': 0.50},
            'bull': {'eps': 0.55, 'multiple': 110, 'target_price': 340, 'probability': 0.25}
        },
        'entry_trigger': 'Pullback zu $210-215 (EMA21) ODER Breakout >$235 mit Volumen',
        'entry_trigger_T123': {
            'T1': 'BE <$215 in Pullback zu EMA21',
            'T2': 'nach Q1 am 12.05. bei PPA-Announce',
            'T3': 'Breakout >$235 mit >=1.5x Volumen (Flag-Breakout)'
        },
        'target_price': 265,
        'stop_pct': 10.0,  # hoehere Vola bei BE
        'position_size_pct': 4,
        'holding_days_max': 45,
        'holding_range': '10-30d',
        'style': 'thesis_play',
        'health': 'active',
        'locked': False,
        'political_risk_flag': False,
        'created_at': TODAY,
        'source': 'dirk_mueller_video_2026-04-22 + DataCenter-Power-Analyse',
    },
}


# ── Deep Dive Verdicts ────────────────────────────────────────────────────
VERDICTS_BATCH = {
    'AMZN': {
        'verdict': 'KAUFEN',
        'score': 75,
        'entry': 249.91,
        'stop': 232.41,       # -7%
        'ziel_1': 290.0,
        'conviction': 'HIGH',
        'insider_bias': 'neutral',
        'macro_bias': 'bullish',
        'key_findings_txt': (
            'Long-Base 210-250$ seit 6M. Q1-Earnings 29.04. Katalysator. '
            'AWS-Wachstum +30% YoY strukturell intakt. Mid-Term-Election-Statistik S&P +36% ab Q2. '
            'CRV 2.3:1 (Entry 250, Stop 232, Ziel 290). Dirk-Mueller VCP-Setup.'
        )
    },
    'HOOD': {
        'verdict': 'KAUFEN',
        'score': 70,
        'entry': 86.43,
        'stop': 79.52,
        'ziel_1': 100.0,
        'conviction': 'HIGH',
        'insider_bias': 'neutral',
        'macro_bias': 'bullish',
        'key_findings_txt': (
            'Retail-Broker mit GAAP-Profit seit 3Q. Crypto-Revenue +76% YoY. BTC-Halving-Cycle-Top '
            'historisch H2/26. Ziel $100 vor Cycle-Peak. Flagge nach Breakout sauber. CRV 2:1.'
        )
    },
    'MRVL': {
        'verdict': 'KAUFEN',
        'score': 72,
        'entry': 151.31,
        'stop': 139.20,
        'ziel_1': 195.0,
        'conviction': 'HIGH',
        'insider_bias': 'neutral',
        'macro_bias': 'bullish',
        'key_findings_txt': (
            'Hidden-Champion Custom-ASIC. AWS/Google/MSFT-Design-Wins. Hyperscaler-Capex $320B FY26. '
            '5-Jahres-Base-Breakout, jetzt Konsolidierung bei $150. Q1 28.05. Katalysator. CRV 3.6:1.'
        )
    },
    'BE': {
        'verdict': 'KAUFEN',
        'score': 68,
        'entry': 220.91,
        'stop': 198.82,  # -10%
        'ziel_1': 265.0,
        'conviction': 'MEDIUM',
        'insider_bias': 'neutral',
        'macro_bias': 'bullish',
        'key_findings_txt': (
            'SOFC-Power fuer AI-DataCenter. Oracle/AEP-PPA 1GW-Pipeline bis 2028. Grid-Queues 5-7J '
            '= BE ist einziger Quick-Fix. Shakeout-Recovery bei $210, Flagge bei $220. Q1 12.05. '
            'mit PPA-Announce erwartet. Vola hoch → 10% Stop. CRV 2:1.'
        )
    },
}


# ── Writer ─────────────────────────────────────────────────────────────────
def add_theses() -> None:
    strats = json.loads(STRATS.read_text(encoding='utf-8'))
    added = []
    skipped = []
    for sid, cfg in NEW_THESES.items():
        if sid in strats:
            skipped.append(sid)
            continue
        strats[sid] = cfg
        added.append(sid)
    STRATS.write_text(json.dumps(strats, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'[theses] added={added} skipped_existing={skipped}')


def add_verdicts() -> None:
    verdicts = json.loads(VERDICTS.read_text(encoding='utf-8')) if VERDICTS.exists() else {}
    added = []
    now_iso = datetime.now().isoformat(timespec='seconds') + '+02:00'
    for ticker, v in VERDICTS_BATCH.items():
        strategy_id = f'PS_{ticker}'
        verdicts[ticker] = {
            'ticker': ticker,
            'verdict': v['verdict'],
            'date': TODAY,
            'updated_at': now_iso,
            'expires': EXPIRES,
            'source': 'manual_dirk_video_analysis',
            'analyst': 'Albert',
            'strategy': strategy_id,
            'score': v['score'],
            'conviction': v['conviction'],
            'insider_bias': v['insider_bias'],
            'macro_bias': v['macro_bias'],
            'reasons': [f'Dirk-Mueller-Video 22.04.: VCP/Base-Breakout-Setup', f'Score {v["score"]}/100'],
            'entry': v['entry'],
            'stop': v['stop'],
            'ziel_1': v['ziel_1'],
            'key_findings': {'summary': v['key_findings_txt']}
        }
        added.append(ticker)
    VERDICTS.write_text(json.dumps(verdicts, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'[verdicts] added={added}')


if __name__ == '__main__':
    add_theses()
    add_verdicts()
    print('\nDone. Jetzt ausfuehren:')
    print('  python3 scripts/thesis_watchlist.py --rebuild')
    print('  python3 scripts/intelligence/thesis_quality_score.py')
