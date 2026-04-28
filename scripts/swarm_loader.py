#!/usr/bin/env python3
"""
swarm_loader.py — Phase 40d: YAML-basierte Swarm-Presets.

Statt hardcoded Bull/Bear/Risk-Personas in ceo_intelligence.py sind die
jetzt in data/swarm_presets/*.yaml definiert. Neue Personas/Teams ohne
Code-Change möglich.

Usage:
    from swarm_loader import load_preset, run_swarm_decision

    preset = load_preset('trading_decision')
    result = run_swarm_decision(preset, context, proposals)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
PRESETS_DIR = WS / 'data' / 'swarm_presets'

sys.path.insert(0, str(WS / 'scripts'))


def _load_yaml(path: Path) -> dict:
    """Naive YAML-Parser (kein PyYAML-Dependency).
    Funktioniert für unsere simplen Presets."""
    text = path.read_text(encoding='utf-8')
    # Sehr einfacher YAML-Parser nur für unsere Struktur
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        # Fallback: extreme minimal parsing — nur für lesen
        return _parse_simple_yaml(text)


def _parse_simple_yaml(text: str) -> dict:
    """Minimal YAML-Parser für unsere konkreten Preset-Files.
    Kennt: top-level keys, list of dicts, multi-line | strings."""
    result = {}
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line or line.startswith('#'):
            i += 1
            continue
        if not line.startswith(' ') and ':' in line:
            key, _, val = line.partition(':')
            key = key.strip()
            val = val.strip()
            if val:
                result[key] = val
            else:
                # Look ahead — list or nested dict?
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and lines[j].lstrip().startswith('-'):
                    # List of dicts
                    items, end = _parse_list(lines, j)
                    result[key] = items
                    i = end
                    continue
                else:
                    # Nested dict
                    nested, end = _parse_dict(lines, j, indent=2)
                    result[key] = nested
                    i = end
                    continue
        i += 1
    return result


def _parse_list(lines: list, start: int) -> tuple[list, int]:
    items = []
    i = start
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue
        stripped = line.lstrip()
        if stripped.startswith('-'):
            item_dict = {}
            # Parse first key-value of item
            content = stripped[1:].strip()
            if ':' in content:
                k, _, v = content.partition(':')
                if v.strip():
                    item_dict[k.strip()] = v.strip()
                else:
                    item_dict[k.strip()] = ''
            items.append(item_dict)
            # Look for additional keys at deeper indent
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    i += 1
                    continue
                if nxt.lstrip().startswith('-') or (nxt and not nxt.startswith('  ')):
                    break
                k_stripped = nxt.lstrip()
                if ':' in k_stripped:
                    k, _, v = k_stripped.partition(':')
                    k = k.strip()
                    v = v.strip()
                    if v == '|' or not v:
                        # Multi-line string
                        ml_lines = []
                        i += 1
                        base_indent = None
                        while i < len(lines):
                            cont = lines[i]
                            if not cont.strip():
                                ml_lines.append('')
                                i += 1
                                continue
                            curr_indent = len(cont) - len(cont.lstrip())
                            if base_indent is None:
                                base_indent = curr_indent
                            if curr_indent < base_indent:
                                break
                            ml_lines.append(cont[base_indent:])
                            i += 1
                        item_dict[k] = '\n'.join(ml_lines).rstrip()
                    elif v.startswith('[') and v.endswith(']'):
                        item_dict[k] = [x.strip() for x in v[1:-1].split(',') if x.strip()]
                    elif v in ('true', 'false'):
                        item_dict[k] = (v == 'true')
                    else:
                        try:
                            item_dict[k] = int(v)
                        except ValueError:
                            try:
                                item_dict[k] = float(v)
                            except ValueError:
                                item_dict[k] = v
                    i += 1
                else:
                    i += 1
        else:
            break
    return items, i


def _parse_dict(lines: list, start: int, indent: int = 2) -> tuple[dict, int]:
    result = {}
    i = start
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue
        if not line.startswith(' ' * indent):
            break
        stripped = line.lstrip()
        if ':' in stripped:
            k, _, v = stripped.partition(':')
            result[k.strip()] = v.strip()
        i += 1
    return result, i


def list_presets() -> list[str]:
    if not PRESETS_DIR.exists():
        return []
    return [f.stem for f in PRESETS_DIR.glob('*.yaml')]


def load_preset(name: str) -> dict | None:
    path = PRESETS_DIR / f'{name}.yaml'
    if not path.exists():
        return None
    try:
        return _load_yaml(path)
    except Exception as e:
        print(f'[swarm_loader] error loading {name}: {e}', file=sys.stderr)
        return None


def run_swarm_decision(preset: dict, context: str,
                        synthesizer_extra_prompt: str = '') -> dict:
    """Führt parallel_then_synthesize Pattern aus.
    Returns: {agent_responses: {id: text}, synthesis: text}"""
    from core.llm_client import call_llm

    orchestration = preset.get('orchestration', {})
    parallel_ids = orchestration.get('parallel_agents', [])
    synth_id = orchestration.get('synthesizer_agent', '')
    agents_by_id = {a['id']: a for a in preset.get('agents', [])
                     if isinstance(a, dict)}

    # Phase 1: parallel runs (sequential exec, but conceptually parallel)
    agent_responses = {}
    for aid in parallel_ids:
        agent = agents_by_id.get(aid)
        if not agent:
            continue
        prompt = f"{agent.get('system_prompt', '')}\n\n=== KONTEXT ===\n{context}"
        try:
            text, _ = call_llm(prompt, model_hint='sonnet',
                                max_tokens=int(agent.get('max_tokens', 1500)))
            agent_responses[aid] = text or ''
        except Exception as e:
            agent_responses[aid] = f'[ERROR: {e}]'

    # Phase 2: synthesizer
    synth_agent = agents_by_id.get(synth_id, {})
    inputs_text = '\n\n'.join(
        f"=== {aid.upper()} INPUT ===\n{txt[:2500]}"
        for aid, txt in agent_responses.items()
    )
    synth_prompt = (
        f"{synth_agent.get('system_prompt', '')}\n\n{inputs_text}\n\n"
        f"=== KONTEXT ===\n{context}\n\n{synthesizer_extra_prompt}"
    )
    try:
        synth_text, _ = call_llm(synth_prompt, model_hint='sonnet',
                                  max_tokens=int(synth_agent.get('max_tokens', 2000)))
    except Exception as e:
        synth_text = f'[SYNTHESIZER ERROR: {e}]'

    return {
        'preset_name': preset.get('name', 'unknown'),
        'agent_responses': agent_responses,
        'synthesis': synth_text or '',
    }


if __name__ == '__main__':
    presets = list_presets()
    print(f'Available presets: {presets}')
    for name in presets:
        p = load_preset(name)
        if p:
            print(f'  {name}: {len(p.get("agents", []))} agents')
