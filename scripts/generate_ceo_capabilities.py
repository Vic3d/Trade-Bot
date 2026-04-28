#!/usr/bin/env python3
"""
generate_ceo_capabilities.py — Phase 40z: CEO weiß was er kann.

Erzeugt memory/ceo-capabilities.md — eine lebendige Übersicht aller
aktiven Phasen, Tools, Decision-Pfade. Wird täglich 23:55 aktualisiert
und im CEO-Brain Pre-Fetch eingebaut, damit CEO seinen eigenen
Werkzeugkasten kennt.

CEO sieht: "Du hast Tool X, Anti-Pattern-Block Y, Mood-Detection Z..."
und kann seine Decisions besser begründen.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
OUT = WS / 'memory' / 'ceo-capabilities.md'


PHASE_REGISTRY = [
    ('21',  'Korrelations-Engine', 'portfolio_risk.py', '7 statistische Risk-Funktionen + Sektor-Cap'),
    ('23',  'Risk-based Position-Sizing', 'execution/risk_based_sizing.py', 'Erichsen-Formel: position = funds × risk%/(entry-stop)'),
    ('24',  'Repo-Stress Frühwarnung', 'macro/net_liquidity_tracker.py', 'SOFR-IORB-Spread → Trade-Block bei Crisis'),
    ('25',  'Skipped-Trades Review', 'weekly_skipped_review.py', 'Wöchentlich: welche Trades hätten Geld gemacht aber wurden geblockt'),
    ('26',  'Theme-Map erweitert', 'strategy_discovery.py', '22 Themen (power_grid, india_growth, quantum, etc.)'),
    ('27',  'Differenzierungs-Audit', 'intelligence/differentiation_audit.py', 'Crowded-Trade Detection → Sizing-Halving'),
    ('28a', 'CEO-Brain', 'ceo_brain.py', 'Zentrale Entscheidung alle 30min im Trading-Fenster'),
    ('28b', 'Shadow-Trades', 'shadow_trades.py', 'Counterfactual aller Setups → Trend-Tracking'),
    ('29',  'Self-Healing Health-Monitor', 'system_health_monitor.py', '10 Checks alle 30min + Auto-Repair (price_monitor restart, etc.)'),
    ('30b', 'Parameter-Auto-Tuner', 'parameter_auto_tuner.py', 'Wöchentlich: optimale Stop/CRV/Hold pro Strategie aus 60d Daten'),
    ('31',  'Goal-Function', 'goal_function.py', 'Utility = pnl + sharpe×1000 - drawdown×200 - concentration'),
    ('31b', 'Goal-Auto-Adjust', 'goal_auto_adjust.py', 'RL-light: Trend-Decline → CRV/Pos%/Sektor% verschärfen'),
    ('32a', 'Decision-Memory', 'ceo_intelligence.py', 'CEO sieht eigene letzten 20 Decisions + Outcomes'),
    ('32b', 'Chain-of-Thought', 'ceo_intelligence.py', 'Strukturiertes Output-Schema mit bull_case/bear_case/confidence'),
    ('32c', 'Lessons-DB', 'ceo_reflection.py', 'Daily 23:15: Mismatches → LLM extrahiert Patterns'),
    ('32d', 'Tool-Use Pre-Fetch', 'ceo_tools.py', 'Pre-fetched: sector_exposure, news, history pro Ticker'),
    ('32e', 'Multi-Agent', 'ceo_intelligence.py', 'Bull/Bear/Risk/Synthesizer (jetzt YAML in Phase 40d)'),
    ('33a', 'Calibration-Loop', 'ceo_consciousness.py', 'Brier-Score + Bias-Correction der Confidence-Schätzungen'),
    ('33b', 'Portfolio-Planning', 'ceo_consciousness.py', 'Top-N Selection statt isolierter Decisions'),
    ('33c', 'Memory-Hierarchy', 'ceo_consciousness.py', 'Permanent vs 60d Lessons (wichtige bleiben)'),
    ('33d', 'World-Model + Calendar', 'calendar_service.py', 'Earnings/Fed/Holidays Aware'),
    ('33e', 'Mood/Tilt-Detection', 'ceo_consciousness.py', '3 Loss in Folge → size×0.5'),
    ('33f', 'Hypothesis-Generator', 'ceo_consciousness.py', 'Underrepresented Sektoren → Discovery-Hint'),
    ('34a', 'Narrative Self', 'ceo_narrative_self.py', 'Lebendiges Identity-Doc — wer bin ich, was lerne ich'),
    ('34d', 'Dream-Phase', 'ceo_dream.py', 'Nachts 02:00 strategische Konsolidierung über 7d'),
    ('35',  'Self-Improvement', 'ceo_self_improvement.py', 'Sa 23:00 wöchentlich: CEO schlägt eigene Code-Verbesserungen vor'),
    ('36',  'Calendar-Service', 'calendar_service.py', 'Datum, Markt-Status, Fed-Meetings, Earnings'),
    ('37',  'Tool-Calling-Loop', 'ceo_tools.py', '8 Tools: get_correlation, web_search, find_similar_setups, ...'),
    ('38',  'Pattern-Learning', 'ceo_pattern_learning.py', 'Heatmap + Anti-Pattern-Detection'),
    ('38b', 'Anti-Pattern Hard-Block', 'ceo_brain.py', 'Critical-Match → action zwangsweise WATCH'),
    ('39',  'Strategy-Lifecycle', 'strategy_lifecycle.py', 'ACTIVE→PROBATION→SUSPENDED→RETIRED mit Re-Test'),
    ('40a', 'Shadow-Account v2', 'shadow_account_v2.py', 'User-Journal → KMeans → if-then Rules'),
    ('40b', 'Backtest MC + Walk-Forward', 'backtest_validator.py', 'Monte Carlo + Bootstrap CI + Walk-Forward'),
    ('40c', 'Context-Compression', 'context_compression.py', '5 Layer: microcompact, collapse, auto-summary, ...'),
    ('40d', 'YAML Swarm-Presets', 'swarm_loader.py', 'data/swarm_presets/*.yaml — neue Personas ohne Code'),
    ('40e', 'MCP-Server', 'trademind_mcp_server.py', 'TradeMind als MCP-Tool nutzbar in Claude Desktop'),
    ('40f', 'Pine-Script-Export', 'pine_exporter.py', 'Strategy → TradingView v6 Pine Script'),
    ('40g', 'Multi-Provider LLM', 'core/llm_client.py', 'CLI → Anthropic → DeepSeek → OpenAI Fallback-Chain'),
]


def get_active_features() -> dict:
    """Erkennt welche Files tatsächlich existieren + sind nicht-leer."""
    actives = []
    for phase, name, file_path, desc in PHASE_REGISTRY:
        full_path = WS / 'scripts' / file_path
        if full_path.exists() and full_path.stat().st_size > 100:
            actives.append({
                'phase': phase, 'name': name,
                'file': file_path, 'desc': desc,
                'lines': sum(1 for _ in open(full_path, encoding='utf-8', errors='ignore')),
            })
    return actives


def get_runtime_state() -> dict:
    """Aktuelle Live-State-Files."""
    state = {}
    for label, fname in [
        ('Lifecycle', 'data/strategies.json'),
        ('Anti-Patterns', 'data/ceo_anti_patterns.json'),
        ('Calibration', 'data/ceo_calibration.json'),
        ('Mood', 'data/ceo_mood.json'),
        ('Goal-Scores', 'data/goal_scores.jsonl'),
        ('Decisions', 'data/ceo_decisions.jsonl'),
        ('Lessons', 'data/ceo_lessons.jsonl'),
        ('Permanent-Lessons', 'data/ceo_permanent_lessons.jsonl'),
        ('Dream-Insights', 'data/ceo_strategic_insights.jsonl'),
        ('Identity-Doc', 'memory/ceo-identity.md'),
    ]:
        p = WS / fname
        if p.exists():
            sz = p.stat().st_size
            mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
            state[label] = {'size_bytes': sz, 'last_modified': mtime}
    return state


def generate_capabilities_doc() -> str:
    actives = get_active_features()
    runtime = get_runtime_state()
    today = datetime.now().strftime('%Y-%m-%d %H:%M')

    lines = [
        f'# CEO-Capabilities — Was du kannst',
        f'*Aktualisiert: {today} | Auto-generated von generate_ceo_capabilities.py*',
        '',
        f'## Übersicht',
        f'Du hast **{len(actives)} aktive Features** über **{max(int(a["phase"].rstrip("abcdefghz")) for a in actives if a["phase"].rstrip("abcdefghz").isdigit())} Phasen** verteilt.',
        '',
        '## Aktive Features (sortiert nach Phase)',
        '',
    ]

    # Group nach Phase-Hauptnummer
    by_main_phase = {}
    for a in actives:
        try:
            main = int(''.join(c for c in a['phase'] if c.isdigit()))
        except ValueError:
            main = 99
        by_main_phase.setdefault(main, []).append(a)

    for main_p in sorted(by_main_phase.keys()):
        lines.append(f'### Phase {main_p}')
        for a in by_main_phase[main_p]:
            lines.append(f"- **{a['phase']}** {a['name']} (`{a['file']}`, {a['lines']}L)")
            lines.append(f"  {a['desc']}")
        lines.append('')

    lines.append('## Aktueller Runtime-State')
    lines.append('')
    for label, info in runtime.items():
        lines.append(f"- **{label}**: {info['size_bytes']:,} bytes, last update {info['last_modified']}")
    lines.append('')

    lines.append('## Decision-Pfade (Reihenfolge in CEO-Brain)')
    lines.append('')
    lines.append('1. **Tool-Loop** (Phase 37) — adaptiv mit Pre-Fetched-Daten')
    lines.append('2. **Multi-Agent** (Phase 32e via YAML 40d) — Bull/Bear/Risk/Synthesizer')
    lines.append('3. **Legacy Single-Pass** — Notfall-Pfad')
    lines.append('4. **Rules-Engine** — wenn LLM down')
    lines.append('')
    lines.append('## Sizing-Multiplier-Stack (alle multiplikativ)')
    lines.append('')
    lines.append('```')
    lines.append('final_size = base_size')
    lines.append('           × calibration_adj      (Phase 33a)')
    lines.append('           × hour_multiplier      (Phase 38b — best/worst hour)')
    lines.append('           × mood_multiplier      (Phase 33e — tilt)')
    lines.append('           × crowded_halving      (Phase 27)')
    lines.append('           × lifecycle_multiplier (Phase 39 — probation halves)')
    lines.append('```')
    lines.append('')

    lines.append('## LLM-Provider-Chain (Phase 40g)')
    lines.append('')
    lines.append('1. claude_cli (OAuth-Subscription, 0€)')
    lines.append('2. anthropic (API, kostet)')
    lines.append('3. deepseek (sehr günstig: $0.27/$1.10 per MTok)')
    lines.append('4. openai (Fallback)')
    lines.append('')

    lines.append('## Was du NICHT kannst (Tier-3 — bleibt bei Victor)')
    lines.append('')
    lines.append('- Real-Money-Trading (nur Paper-Mode)')
    lines.append('- Selbst Code modifizieren (Self-Improvement schlägt nur vor)')
    lines.append('- Strategie-Suspension ohne Pattern-Trigger (außer manuell)')
    lines.append('- Stop-Loss-Mechanismus ändern (Hard-Safety)')
    lines.append('')

    return '\n'.join(lines)


def main() -> int:
    doc = generate_capabilities_doc()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding='utf-8')
    print(f'Generated → {OUT}')
    print(f'Size: {len(doc)} chars')
    print('---')
    print(doc[:2000])
    return 0


if __name__ == '__main__':
    sys.exit(main())
