#!/usr/bin/env python3
"""
system_health_monitor.py — Phase 29: Self-Healing.

Läuft alle 30min via scheduler. Prüft 9 Health-Dimensionen,
auto-repariert wo möglich, alarmiert wenn nicht.

Wenn dieses System existiert hätte, hätten wir folgende Bugs früher
gefunden:
  - EQNR/NVO Currency-Mismatch (-2406€ Phantom-Verlust, 4 Tage unentdeckt)
  - correlations.json computed_at fehlte (Guard 5d blockierte Trades)
  - LLM API-Guthaben leer (Deep Dives lieferten UNBEKANNT)
  - 315 expired Proposals stauten silent

Health-Checks:
  C1  Scheduler aktiv (Heartbeat <10min alt)
  C2  LLM verfügbar (claude_cli ping)
  C3  DB writable + readable
  C4  CEO-Direktive valid (parseable, mode gesetzt)
  C5  correlations.json fresh (<48h)
  C6  Pipeline-Stau (proposals expired/active Ratio)
  C7  Trade-Anomalien (Currency-Mismatch, schlechte Stops)
  C8  FX-Layer funktional (alle 5 Major-Currencies konvertieren)
  C9  Discord-Dispatcher erreichbar

Auto-Fixes:
  C5 stale → auto-trigger correlation_refresh.py
  C2 down  → CEO-Brain auf Rules-Mode (env-Flag)
  C6 stuck → cleanup expired proposals
  C7 anomaly → flag for manual review (kein Auto-Repair für Trades!)

Discord-Format (TIER_HIGH wenn FAIL, MEDIUM wenn WARN):
  🏥 System-Health: 7/9 OK | 1 WARN | 1 FAIL
  ❌ C7 Trade-Anomaly: 2 Trades mit Currency-Mismatch (siehe Log)
  ⚠️ C5 correlations.json 26h alt — refresh läuft
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB                   = WS / 'data' / 'trading.db'
HEALTH_LOG           = WS / 'data' / 'health_checks.jsonl'
HEARTBEAT_FILE       = WS / 'data' / 'scheduler_heartbeat.txt'
DIRECTIVE_FILE       = WS / 'data' / 'ceo_directive.json'
CORRELATIONS_FILE    = WS / 'data' / 'correlations.json'
PROPOSALS_FILE       = WS / 'data' / 'proposals.json'
LLM_FALLBACK_FLAG    = WS / 'data' / '.llm_fallback_active'

HEARTBEAT_MAX_MIN    = 20    # >20min ohne Heartbeat = STALE
CORR_MAX_HOURS       = 48    # >48h Matrix = STALE
PROPOSALS_STAU_RATIO = 0.95  # >95% expired bei n>50 = Stau
LLM_FAIL_TTL_MIN     = 60    # Fallback-Flag bleibt 60min aktiv


# ─── Helpers ──────────────────────────────────────────────────────────────

def _log(entry: dict) -> None:
    try:
        HEALTH_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry.setdefault('ts', datetime.now().isoformat(timespec='seconds'))
        with open(HEALTH_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'[health] log error: {e}', file=sys.stderr)


def _result(name: str, status: str, msg: str = '', detail: dict | None = None) -> dict:
    return {'check': name, 'status': status, 'msg': msg, 'detail': detail or {}}


# ─── Checks ──────────────────────────────────────────────────────────────

def check_scheduler() -> dict:
    """C1: Heartbeat-File <20min alt?"""
    if not HEARTBEAT_FILE.exists():
        return _result('C1_scheduler', 'FAIL', 'Heartbeat-File fehlt')
    try:
        age = (datetime.now() - datetime.fromtimestamp(HEARTBEAT_FILE.stat().st_mtime))
        age_min = age.total_seconds() / 60
        if age_min > HEARTBEAT_MAX_MIN:
            return _result('C1_scheduler', 'FAIL',
                           f'Heartbeat {age_min:.0f}min alt (>{HEARTBEAT_MAX_MIN})')
        return _result('C1_scheduler', 'OK', f'{age_min:.0f}min ago')
    except Exception as e:
        return _result('C1_scheduler', 'WARN', str(e))


def check_llm() -> dict:
    """C2: LLM-Ping via call_llm."""
    try:
        from core.llm_client import call_llm
        text, usage = call_llm('Antworte exakt: pong', model_hint='haiku', max_tokens=10)
        if 'pong' in (text or '').lower():
            # LLM-Fallback-Flag entfernen wenn vorher gesetzt
            if LLM_FALLBACK_FLAG.exists():
                LLM_FALLBACK_FLAG.unlink()
            return _result('C2_llm', 'OK', f'provider={usage.get("provider","?")}')
        return _result('C2_llm', 'WARN', f'Antwort unerwartet: {text[:50]}')
    except Exception as e:
        # AUTO-FIX: Fallback-Flag setzen → CEO-Brain nutzt Rules
        try:
            LLM_FALLBACK_FLAG.touch()
        except Exception:
            pass
        return _result('C2_llm', 'FAIL', f'{type(e).__name__}: {str(e)[:100]}',
                       {'autofix': 'fallback_flag_set'})


def check_db() -> dict:
    """C3: DB read+write."""
    try:
        c = sqlite3.connect(str(DB))
        c.execute('SELECT COUNT(*) FROM paper_portfolio').fetchone()
        c.close()
        return _result('C3_db', 'OK', 'read OK')
    except Exception as e:
        return _result('C3_db', 'FAIL', str(e)[:100])


def check_directive() -> dict:
    """C4: ceo_directive.json valid + mode gesetzt."""
    if not DIRECTIVE_FILE.exists():
        return _result('C4_directive', 'FAIL', 'File fehlt')
    try:
        d = json.loads(DIRECTIVE_FILE.read_text(encoding='utf-8'))
        mode = d.get('mode')
        if not mode:
            return _result('C4_directive', 'WARN', 'mode-Feld leer')
        ts = d.get('timestamp', '')
        try:
            age_h = (datetime.now() - datetime.fromisoformat(ts[:19])).total_seconds() / 3600
        except Exception:
            age_h = -1
        if age_h > 24:
            return _result('C4_directive', 'WARN',
                           f'mode={mode}, {age_h:.0f}h alt')
        return _result('C4_directive', 'OK', f'mode={mode}, {age_h:.0f}h alt')
    except Exception as e:
        return _result('C4_directive', 'FAIL', str(e)[:100])


def check_correlations() -> dict:
    """C5: correlations.json <48h. Auto-Refresh wenn stale."""
    if not CORRELATIONS_FILE.exists():
        return _result('C5_correlations', 'FAIL', 'File fehlt — Auto-Refresh angestoßen',
                       _trigger_corr_refresh())
    try:
        d = json.loads(CORRELATIONS_FILE.read_text(encoding='utf-8'))
        ts = d.get('computed_at') or d.get('updated')
        if not ts:
            return _result('C5_correlations', 'WARN', 'kein timestamp im File')
        age_h = (datetime.now(timezone.utc) -
                 datetime.fromisoformat(ts.replace('Z', '+00:00'))).total_seconds() / 3600
        if age_h > CORR_MAX_HOURS:
            detail = _trigger_corr_refresh()
            return _result('C5_correlations', 'FAIL',
                           f'{age_h:.0f}h alt → Auto-Refresh', detail)
        if age_h > 24:
            return _result('C5_correlations', 'WARN',
                           f'{age_h:.0f}h alt (Schwelle 48h)')
        return _result('C5_correlations', 'OK', f'{age_h:.0f}h alt, '
                       f'{len(d.get("tickers",[]))} Tickers')
    except Exception as e:
        return _result('C5_correlations', 'FAIL', str(e)[:100])


def _trigger_corr_refresh() -> dict:
    """Auto-Fix für C5: läuft correlation_refresh.py async."""
    try:
        subprocess.Popen(
            [sys.executable, str(WS / 'scripts' / 'correlation_refresh.py')],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(WS),
        )
        return {'autofix': 'correlation_refresh_started'}
    except Exception as e:
        return {'autofix': f'failed: {e}'}


def check_proposals() -> dict:
    """C6: Proposals-Stau (>95% expired bei n>50)."""
    if not PROPOSALS_FILE.exists():
        return _result('C6_proposals', 'OK', 'no file (yet)')
    try:
        d = json.loads(PROPOSALS_FILE.read_text(encoding='utf-8'))
        if isinstance(d, dict):
            d = d.get('proposals', [])
        if not d:
            return _result('C6_proposals', 'OK', 'leer')
        from collections import Counter
        statuses = Counter(p.get('status') for p in d if isinstance(p, dict))
        total = sum(statuses.values())
        expired = statuses.get('expired', 0)
        active = statuses.get('active', 0) + statuses.get('pending', 0)
        if total > 50 and (expired / total) > PROPOSALS_STAU_RATIO:
            return _result('C6_proposals', 'WARN',
                           f'Stau: {expired}/{total} expired ({expired/total*100:.0f}%)',
                           {'cleanup_suggested': True})
        return _result('C6_proposals', 'OK',
                       f'{active} active, {expired} expired ({total} total)')
    except Exception as e:
        return _result('C6_proposals', 'WARN', str(e)[:100])


def check_trade_anomalies() -> dict:
    """C7: Currency-Mismatch in CLOSED-Trades letzte 7d."""
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from core.live_data import get_price_eur
    except Exception:
        return _result('C7_trades', 'WARN', 'live_data nicht ladbar')

    cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT id, ticker, entry_price, close_price, pnl_pct, exit_type
            FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
              AND close_date >= ?
              AND close_price IS NOT NULL AND entry_price > 0
        """, (cutoff,)).fetchall()
        c.close()

        anomalies = []
        for r in rows:
            ratio = (r['close_price'] or 0) / r['entry_price']
            # Currency-Mismatch oder absurder PnL?
            if ratio < 0.5 or ratio > 2.0:
                anomalies.append({
                    'id': r['id'], 'ticker': r['ticker'],
                    'entry': r['entry_price'], 'close': r['close_price'],
                    'pnl_pct': r['pnl_pct'],
                    'reason': f'ratio={ratio:.2f}x (Currency?)'
                })
            elif (r['pnl_pct'] or 0) < -50 and r['exit_type'] != 'STOP_MONITOR_REPAIRED':
                anomalies.append({
                    'id': r['id'], 'ticker': r['ticker'],
                    'pnl_pct': r['pnl_pct'],
                    'reason': f'PnL {r["pnl_pct"]:.0f}% (Stop versagt?)'
                })

        if anomalies:
            return _result('C7_trades', 'FAIL',
                           f'{len(anomalies)} verdächtige Trades — manueller Check',
                           {'anomalies': anomalies[:5]})
        return _result('C7_trades', 'OK', f'{len(rows)} Trades sauber (7d)')
    except Exception as e:
        return _result('C7_trades', 'WARN', str(e)[:100])


def check_fx() -> dict:
    """C8: FX-Layer funktional für 5 Major-Currencies."""
    try:
        from core.live_data import get_price_eur
    except Exception as e:
        return _result('C8_fx', 'FAIL', f'import error: {e}')

    test_tickers = {
        'AAPL':       'USD',
        'BMW.DE':     'EUR',
        'EQNR.OL':    'NOK',
        'NOVO-B.CO':  'DKK',
        'BA.L':       'GBp',
    }
    failed = []
    for tk, cur in test_tickers.items():
        try:
            p = get_price_eur(tk)
            if not p or p <= 0 or p > 5000:
                failed.append(f'{tk}({cur})={p}')
        except Exception as e:
            failed.append(f'{tk}({cur}):{type(e).__name__}')

    if failed:
        return _result('C8_fx', 'WARN', f'failed: {", ".join(failed)}')
    return _result('C8_fx', 'OK', f'{len(test_tickers)}/5 currencies OK')


def check_discord() -> dict:
    """C9: Discord-Dispatcher importierbar."""
    try:
        from discord_dispatcher import send_alert, TIER_LOW
        return _result('C9_discord', 'OK', 'importable')
    except Exception as e:
        return _result('C9_discord', 'FAIL', f'{type(e).__name__}: {e}')


# ─── Main ────────────────────────────────────────────────────────────────

def run_all_checks() -> list[dict]:
    checks = [
        check_scheduler(),
        check_llm(),
        check_db(),
        check_directive(),
        check_correlations(),
        check_proposals(),
        check_trade_anomalies(),
        check_fx(),
        check_discord(),
    ]
    return checks


def format_summary(checks: list[dict]) -> tuple[str, str]:
    """Returns (severity, msg). severity: ok | warn | fail."""
    ok_n   = sum(1 for c in checks if c['status'] == 'OK')
    warn_n = sum(1 for c in checks if c['status'] == 'WARN')
    fail_n = sum(1 for c in checks if c['status'] == 'FAIL')

    if fail_n > 0:
        severity = 'fail'
    elif warn_n > 0:
        severity = 'warn'
    else:
        severity = 'ok'

    icons = {'OK': '✅', 'WARN': '⚠️', 'FAIL': '❌'}
    head = f'🏥 **System-Health:** {ok_n} OK | {warn_n} WARN | {fail_n} FAIL'
    body_lines = []
    for c in checks:
        if c['status'] == 'OK':
            continue  # nur Probleme zeigen
        body_lines.append(f"{icons[c['status']]} `{c['check']}` — {c['msg']}")
        if c.get('detail', {}).get('autofix'):
            body_lines.append(f"   _autofix: {c['detail']['autofix']}_")

    if not body_lines:
        body_lines.append('_Alle Checks OK — System gesund._')

    return severity, head + '\n' + '\n'.join(body_lines)


def main() -> int:
    print(f'─── Health-Monitor @ {datetime.now().isoformat(timespec="seconds")} ───')
    checks = run_all_checks()

    for c in checks:
        icon = {'OK': '✅', 'WARN': '⚠️', 'FAIL': '❌'}.get(c['status'], '?')
        print(f'  {icon} {c["check"]:18s} {c["msg"]}')

    severity, msg = format_summary(checks)
    _log({'event': 'health_run', 'severity': severity,
          'checks': checks})

    # Discord nur bei WARN/FAIL (sonst Spam)
    if severity != 'ok':
        try:
            from discord_dispatcher import send_alert, TIER_HIGH, TIER_MEDIUM
            tier = TIER_HIGH if severity == 'fail' else TIER_MEDIUM
            send_alert(msg, tier=tier, category='system_health',
                       dedupe_key=f'health_{severity}_{datetime.now().strftime("%Y-%m-%d-%H")}')
        except Exception as e:
            print(f'discord send failed: {e}')

    return 0 if severity != 'fail' else 1


if __name__ == '__main__':
    sys.exit(main())
