#!/usr/bin/env python3
"""
Auto Deep Dive Runner — Phase 7.14 (Scheduled Autonomy)
=========================================================
Faehrt Auto-Deep-Dive fuer eine priorisierte Watchlist.

Scope-Modi:
  full      — Offene Positionen (force refresh) + Entry-Kandidaten (skip-logik)
  open-only — Nur offene Positionen (force refresh) — fuer intraday Hold-Checks

Watchlist-Prioritaeten (full mode):
  1. Offene Positionen          — IMMER, force=True (Leichen im Keller finden)
  2. Aktive Strategien          — ohne frisches Verdict (status != SUSPENDED)
  3. Watchlist aus strategies.json (status=watching/experimental)

Budget:
  MAX_TICKERS_PER_RUN = 20 (hart)
  MAX_COST_USD = 10.0   (Stopp wenn Cost-Schaetzung ueberschritten)

Exit-Trigger:
  Fuer offene Positionen: NICHT_KAUFEN + confidence >= 75
    -> Exit-Signal in data/auto_dd_exit_signals.jsonl
    -> paper_exit_manager.py liest die Signale im naechsten Zyklus

Output:
  data/auto_dd_runs.jsonl      — pro Run: tickers, usage, verdicts, Kosten
  data/auto_dd_exit_signals.jsonl — Exit-Signale fuer paper_exit_manager

CLI:
  python3 scripts/auto_deep_dive_runner.py            # full mode
  python3 scripts/auto_deep_dive_runner.py open-only  # nur offene Positionen
  python3 scripts/auto_deep_dive_runner.py --dry      # keine API-Calls, nur Plan
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
VERDICTS = WS / 'data' / 'deep_dive_verdicts.json'
RUNS_LOG = WS / 'data' / 'auto_dd_runs.jsonl'
EXIT_SIGNALS = WS / 'data' / 'auto_dd_exit_signals.jsonl'
STRATS_JSON = WS / 'data' / 'strategies.json'

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'intelligence'))

MAX_TICKERS_PER_RUN = 20
MAX_COST_USD = 10.0
HOLD_EXIT_CONFIDENCE_THRESHOLD = 75  # NICHT_KAUFEN + conf>=75 -> Auto-Exit


# ────────────────────────────────────────────────────────────────────────────
# Watchlist-Bau
# ────────────────────────────────────────────────────────────────────────────


def get_open_positions() -> list[dict]:
    """Alle offenen Positionen inkl. archived_pre_reset (die sind real kapitalgebunden)."""
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, ticker, strategy, entry_price, entry_date, shares, stop_price, target_price
        FROM paper_portfolio
        WHERE status='OPEN'
        ORDER BY entry_date DESC
    """).fetchall()
    conn.close()

    out = []
    for r in rows:
        try:
            entry_dt = datetime.fromisoformat(str(r['entry_date'])[:19])
            days_held = (datetime.now() - entry_dt).days
        except Exception:
            days_held = 0
        out.append({
            'ticker': r['ticker'],
            'strategy': r['strategy'],
            'entry_price': r['entry_price'],
            'stop_price': r['stop_price'],
            'target_price': r['target_price'],
            'shares': r['shares'],
            'days_held': days_held,
            'position_id': r['id'],
        })
    return out


def get_active_strategies_tickers() -> list[tuple[str, str]]:
    """Tickers aus aktiven Strategien. Returns: [(ticker, strategy_id), ...]"""
    out: list[tuple[str, str]] = []
    try:
        strats = json.loads(STRATS_JSON.read_text(encoding='utf-8'))
    except Exception:
        return out
    if not isinstance(strats, dict):
        return out

    for sid, s in strats.items():
        if not isinstance(s, dict):
            continue
        status = s.get('status', '')
        if status in ('SUSPENDED', 'blocked'):
            continue
        if status not in ('active', 'experimental', 'watching'):
            continue
        for ticker in s.get('tickers', []):
            out.append((ticker.upper(), sid))
    # Dedup
    seen = set()
    dedup = []
    for t, sid in out:
        if t not in seen:
            seen.add(t)
            dedup.append((t, sid))
    return dedup


def load_verdicts_map() -> dict:
    try:
        return json.loads(VERDICTS.read_text(encoding='utf-8'))
    except Exception:
        return {}


def should_skip_entry_candidate(ticker: str, verdicts: dict) -> tuple[bool, str]:
    """Skip-Logik fuer Entry-Kandidaten (NICHT offene Positionen)."""
    v = verdicts.get(ticker.upper())
    if not v:
        return (False, 'no_verdict')
    try:
        ts = v.get('timestamp', '')
        last = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - last).days
    except Exception:
        return (False, 'stale_timestamp')

    verdict = (v.get('verdict') or '').upper()
    if verdict == 'KAUFEN' and age_days < 3:
        return (True, f'fresh_kaufen_{age_days}d')
    if verdict == 'WARTEN' and age_days < 7:
        return (True, f'fresh_warten_{age_days}d')
    if verdict == 'NICHT_KAUFEN' and age_days < 14:
        return (True, f'fresh_nicht_kaufen_{age_days}d')
    return (False, f'stale_{age_days}d')


def build_watchlist(scope: str) -> list[dict]:
    """
    Returns: liste von {ticker, mode, priority, reason, position_ctx?}
    """
    watchlist: list[dict] = []
    seen: set[str] = set()

    # Priority 1: Offene Positionen — IMMER, force refresh
    for pos in get_open_positions():
        t = pos['ticker'].upper()
        if t in seen:
            continue
        watchlist.append({
            'ticker': t,
            'mode': 'hold',
            'priority': 1,
            'reason': 'open_position',
            'position_ctx': {
                'entry_price': pos['entry_price'],
                'strategy': pos['strategy'],
                'days_held': pos['days_held'],
                'position_id': pos['position_id'],
            },
            'force': True,  # keine Skip-Logik fuer offene Positionen
        })
        seen.add(t)

    if scope == 'open-only':
        return watchlist[:MAX_TICKERS_PER_RUN]

    # Priority 1.5: Discovery-Kandidaten (candidate_tickers.json, status=pending, top-priority)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / 'discovery'))
        from candidates import get_pending_candidates, load_candidates
        cand_data = load_candidates()
        for t in get_pending_candidates(max_count=8):
            t_up = t.upper()
            if t_up in seen:
                continue
            entry = cand_data.get(t_up, {})
            source_types = sorted({s.get('type', '?') for s in entry.get('sources', [])})
            watchlist.append({
                'ticker': t_up,
                'mode': 'entry',
                'priority': 1.5,
                'reason': f"discovery_candidate:{','.join(source_types)}:prio={entry.get('priority', 0.0)}",
                'position_ctx': None,
                'force': True,  # pending candidates immer durchziehen (sind noch nie analysiert)
            })
            seen.add(t_up)
            if len(watchlist) >= MAX_TICKERS_PER_RUN:
                return watchlist[:MAX_TICKERS_PER_RUN]
    except Exception as e:
        print(f'[runner] discovery-candidates error: {e}')

    # Priority 2+3: Entry-Kandidaten aus aktiven Strategien
    verdicts = load_verdicts_map()
    for ticker, sid in get_active_strategies_tickers():
        t = ticker.upper()
        if t in seen:
            continue
        skip, reason = should_skip_entry_candidate(t, verdicts)
        if skip:
            continue
        watchlist.append({
            'ticker': t,
            'mode': 'entry',
            'priority': 2,
            'reason': f'active_strategy:{sid}:{reason}',
            'position_ctx': None,
            'force': False,
        })
        seen.add(t)
        if len(watchlist) >= MAX_TICKERS_PER_RUN:
            break

    return watchlist[:MAX_TICKERS_PER_RUN]


# ────────────────────────────────────────────────────────────────────────────
# Exit-Signal-Handling
# ────────────────────────────────────────────────────────────────────────────


def _write_exit_signal(ticker: str, position_id: int, verdict: dict, reasoning: str) -> None:
    """Schreibe Exit-Signal in JSONL. paper_exit_manager liest es im naechsten Zyklus."""
    try:
        rec = {
            'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'ticker': ticker,
            'position_id': position_id,
            'source': 'AUTO_DD_HOLD_CHECK',
            'verdict': verdict.get('verdict'),
            'confidence': verdict.get('confidence'),
            'reasoning': reasoning[:300],
            'key_risks': verdict.get('key_risks', [])[:3],
            'action': 'EXIT',
            'reason_code': 'AUTO_DD_INVALIDATED',
            'consumed': False,  # paper_exit_manager setzt das auf True nach Verarbeitung
        }
        EXIT_SIGNALS.parent.mkdir(parents=True, exist_ok=True)
        with open(EXIT_SIGNALS, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"[runner] Exit-Signal schreiben fehlgeschlagen: {e}")


def _queue_discord_alert(message: str) -> None:
    """Schreibe Alert in die Alert-Queue."""
    alert_queue = WS / 'memory' / 'alert-queue.json'
    try:
        queue = []
        if alert_queue.exists():
            try:
                queue = json.loads(alert_queue.read_text(encoding='utf-8'))
            except Exception:
                queue = []
        queue.append({
            'message': message,
            'target': '452053147620343808',
            'ts': datetime.now(timezone.utc).isoformat(),
        })
        alert_queue.write_text(json.dumps(queue, indent=2))
    except Exception as e:
        print(f"[runner] Alert-Queue schreiben fehlgeschlagen: {e}")


# ────────────────────────────────────────────────────────────────────────────
# Main Runner
# ────────────────────────────────────────────────────────────────────────────


def run_batch(scope: str = 'full', dry: bool = False) -> dict:
    start = datetime.now(timezone.utc)
    watchlist = build_watchlist(scope)

    if dry:
        print(f"[runner] DRY-RUN scope={scope}")
        print(f"[runner] Watchlist ({len(watchlist)} Tickers):")
        for e in watchlist:
            force_tag = ' [FORCE]' if e['force'] else ''
            print(f"  {e['priority']}. {e['ticker']:10} mode={e['mode']:6} reason={e['reason']}{force_tag}")
        return {'dry': True, 'count': len(watchlist)}

    from auto_deep_dive import run as dd_run

    results = {
        'ts_start': start.isoformat(timespec='seconds'),
        'scope': scope,
        'watchlist_size': len(watchlist),
        'verdicts_by_type': {'KAUFEN': 0, 'WARTEN': 0, 'NICHT_KAUFEN': 0, 'ERROR': 0, 'SKIPPED': 0},
        'calls_made': 0,
        'calls_skipped': 0,
        'total_cost_usd': 0.0,
        'exit_signals': [],
        'per_ticker': [],
    }

    for entry in watchlist:
        ticker = entry['ticker']
        mode = entry['mode']

        # Budget-Cap
        if results['total_cost_usd'] >= MAX_COST_USD:
            print(f"[runner] Budget-Cap {MAX_COST_USD}$ erreicht — Stopp bei {ticker}")
            _queue_discord_alert(
                f"⚠️ Auto-DD Budget-Cap erreicht ({MAX_COST_USD}$) — "
                f"{results['calls_made']} Tickers fertig, Rest uebersprungen"
            )
            break

        try:
            result = dd_run(
                ticker,
                force=entry['force'],
                mode=mode,
                position_ctx=entry.get('position_ctx'),
            )
        except Exception as e:
            print(f"[runner] {ticker}: Exception: {e}")
            results['verdicts_by_type']['ERROR'] += 1
            results['per_ticker'].append({'ticker': ticker, 'status': 'error', 'error': str(e)})
            continue

        status = result.get('status')
        if status == 'skipped':
            results['calls_skipped'] += 1
            results['verdicts_by_type']['SKIPPED'] += 1
            results['per_ticker'].append({
                'ticker': ticker,
                'status': 'skipped',
                'reason': result.get('reason'),
            })
            continue

        if status == 'error':
            results['verdicts_by_type']['ERROR'] += 1
            results['per_ticker'].append({
                'ticker': ticker,
                'status': 'error',
                'error': result.get('error'),
            })
            continue

        # Ok — Call wurde gemacht
        results['calls_made'] += 1
        usage = result.get('usage', {})
        cost = usage.get('cost_usd_est', 0.0)
        results['total_cost_usd'] += cost

        raw_verdict = (result.get('raw_verdict') or '').upper()
        if raw_verdict in results['verdicts_by_type']:
            results['verdicts_by_type'][raw_verdict] += 1

        results['per_ticker'].append({
            'ticker': ticker,
            'status': 'ok',
            'mode': mode,
            'verdict': result.get('verdict'),
            'raw_verdict': raw_verdict,
            'confidence': result.get('confidence'),
            'warnings': len(result.get('warnings', [])),
            'cost_usd': round(cost, 4),
        })

        # ── Discovery-Candidate status-update (Priority 1.5) ──────────
        if entry.get('priority') == 1.5:
            try:
                from candidates import mark_status as _mark_cand
                _mark_cand(ticker, 'analyzing', note=f'DD {raw_verdict} conf={result.get("confidence")}')
            except Exception:
                pass

        # ── Exit-Trigger: Hold-Check + NICHT_KAUFEN + conf>=75 ────────
        if mode == 'hold' and raw_verdict == 'NICHT_KAUFEN':
            conf = int(result.get('confidence') or 0)
            reasoning = result.get('reasoning', '')
            pos_ctx = entry.get('position_ctx') or {}
            pos_id = pos_ctx.get('position_id')

            if conf >= HOLD_EXIT_CONFIDENCE_THRESHOLD:
                # Auto-Exit
                _write_exit_signal(ticker, pos_id, {
                    'verdict': raw_verdict,
                    'confidence': conf,
                    'key_risks': result.get('key_risks', []),
                }, reasoning)
                results['exit_signals'].append({
                    'ticker': ticker,
                    'position_id': pos_id,
                    'confidence': conf,
                    'action': 'EXIT',
                })
                _queue_discord_alert(
                    f"🚨 AUTO-DD Exit-Signal: **{ticker}**\n"
                    f"Verdict: NICHT_KAUFEN (conf={conf})\n"
                    f"Grund: {reasoning[:200]}\n"
                    f"→ Position wird im naechsten Exit-Zyklus geschlossen."
                )
            elif conf >= 60:
                # Warnung ohne Auto-Exit
                _queue_discord_alert(
                    f"⚠️ AUTO-DD Warnung: **{ticker}**\n"
                    f"NICHT_KAUFEN mit Confidence {conf} (< {HOLD_EXIT_CONFIDENCE_THRESHOLD} fuer Auto-Exit)\n"
                    f"Grund: {reasoning[:200]}\n"
                    f"→ Manuell pruefen."
                )

    results['ts_end'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    results['duration_sec'] = round(
        (datetime.fromisoformat(results['ts_end']) - datetime.fromisoformat(results['ts_start'])).total_seconds(), 1
    )

    # Log schreiben
    try:
        RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(RUNS_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(results, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"[runner] Runs-Log schreiben fehlgeschlagen: {e}")

    # Summary print
    print(f"\n═══ Auto-DD Runner Summary ({scope}) ═══")
    print(f"  Watchlist:      {results['watchlist_size']} Tickers")
    print(f"  API-Calls:      {results['calls_made']}  (skipped: {results['calls_skipped']})")
    print(f"  Verdicts:       KAUFEN={results['verdicts_by_type']['KAUFEN']}  "
          f"WARTEN={results['verdicts_by_type']['WARTEN']}  "
          f"NICHT_KAUFEN={results['verdicts_by_type']['NICHT_KAUFEN']}  "
          f"ERROR={results['verdicts_by_type']['ERROR']}")
    print(f"  Exit-Signale:   {len(results['exit_signals'])}")
    print(f"  Kosten-Schaetz: {results['total_cost_usd']:.2f} USD")
    print(f"  Dauer:          {results['duration_sec']}s")

    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scope', nargs='?', default='full', choices=['full', 'open-only'],
                    help='full: offene Positionen + Entry-Kandidaten; open-only: nur offene')
    ap.add_argument('--dry', action='store_true', help='Nur Plan ausgeben, keine API-Calls')
    args = ap.parse_args()

    results = run_batch(scope=args.scope, dry=args.dry)
    # Exit 0 bei Erfolg, 2 bei kompletten Fehlern
    if not args.dry and results.get('watchlist_size', 0) > 0 and results.get('calls_made', 0) == 0:
        # Kein einziger Call gelungen — Problem
        sys.exit(2)
    sys.exit(0)


if __name__ == '__main__':
    main()
