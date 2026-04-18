#!/usr/bin/env python3
"""
Autonomous Pipeline Orchestrator — Phase 13
============================================

Binds the full autonomy chain into ONE process:

  1. News → Thesis Discovery         (intelligence/thesis_discovery.py)
  2. Watchlist → Auto Deep Dive      (intelligence/auto_deepdive.py)
  3. Verdict KAUFEN → Proposal Exec  (proposal_executor.py)
  4. Open positions → Watchdog       (position_watchdog.py)

Called from scheduler 3x daily (11:00 / 15:00 / 19:00 CET Mo-Fr).
Each step is a subprocess — failure in one does not kill the chain.

Mode gate: data/autonomy_config.json { "mode": "SHADOW" | "LIVE" | "OFF" }
  OFF    → no-op
  SHADOW → run pipeline, executor shadow-only (Phase 17)
  LIVE   → run pipeline, executor trades (Phase 18)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger('autonomous_pipeline')

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
SCRIPTS = WS / 'scripts'
DATA = WS / 'data'
CONFIG = DATA / 'autonomy_config.json'
RUN_LOG = DATA / 'autonomous_pipeline_runs.json'


def _load(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default


def _save(p: Path, data) -> None:
    try:
        p.write_text(json.dumps(data, indent=2), encoding='utf-8')
    except Exception:
        pass


def _mode() -> str:
    cfg = _load(CONFIG, {})
    return str(cfg.get('mode', 'SHADOW')).upper()


def _run_step(name: str, script: str, args: list[str] | None = None) -> dict:
    args = args or []
    path = SCRIPTS / script
    if not path.exists():
        log.warning(f'{name}: script missing — {script}')
        return {'step': name, 'ok': False, 'error': 'script missing'}

    log.info(f'▶️  {name}')
    try:
        result = subprocess.run(
            ['python3', str(path)] + args,
            capture_output=True,
            text=True,
            timeout=1200,
            cwd=str(WS),
        )
        ok = result.returncode == 0
        tail = (result.stdout or result.stderr or '').strip().splitlines()[-5:]
        if not ok:
            log.warning(f'{name}: rc={result.returncode}')
        return {'step': name, 'ok': ok, 'rc': result.returncode, 'tail': tail}
    except subprocess.TimeoutExpired:
        return {'step': name, 'ok': False, 'error': 'timeout'}
    except Exception as e:
        return {'step': name, 'ok': False, 'error': str(e)}


def run() -> dict:
    mode = _mode()
    log.info(f'Pipeline start: mode={mode}')

    run_entry = {
        'started_at': datetime.now().isoformat(timespec='seconds'),
        'mode': mode,
        'steps': [],
    }

    if mode == 'OFF':
        run_entry['steps'].append({'step': 'skipped', 'ok': True, 'reason': 'OFF'})
        _append_run(run_entry)
        log.info('OFF — skipping pipeline')
        return run_entry

    run_entry['steps'].append(_run_step(
        'Thesis Discovery', 'intelligence/thesis_discovery.py'
    ))
    run_entry['steps'].append(_run_step(
        'Auto Deep Dive', 'intelligence/auto_deepdive.py'
    ))
    run_entry['steps'].append(_run_step(
        'Proposal Executor', 'proposal_executor.py'
    ))
    run_entry['steps'].append(_run_step(
        'Position Watchdog', 'position_watchdog.py'
    ))

    run_entry['finished_at'] = datetime.now().isoformat(timespec='seconds')
    _append_run(run_entry)

    ok_count = sum(1 for s in run_entry['steps'] if s.get('ok'))
    log.info(f'Pipeline done: {ok_count}/{len(run_entry["steps"])} steps OK')
    return run_entry


def _append_run(entry: dict) -> None:
    hist = _load(RUN_LOG, [])
    hist.append(entry)
    _save(RUN_LOG, hist[-100:])


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    r = run()
    ok = sum(1 for s in r['steps'] if s.get('ok'))
    print(f'\nAutonomous Pipeline ({r["mode"]}): {ok}/{len(r["steps"])} ok')


if __name__ == '__main__':
    main()
