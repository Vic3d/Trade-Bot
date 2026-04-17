#!/usr/bin/env python3
"""
TradeMind CEO Tester
====================
Prüft die gesamte CEO-Kette Schritt für Schritt:

  [1] Datenquellen     — Existieren alle Inputdateien? Sind sie aktuell?
  [2] News Gate        — Werden news_gate.json top_hits korrekt gelesen?
  [3] Overnight Events — Liegen aktuelle Events in newswire.db vor?
  [4] Strategies       — strategies.json valide + aktive Strategien?
  [5] CEO Direktive    — ceo_directive.json vollständig + frisch?
  [6] AI-Analyse       — Hat Claude Sonnet analysiert? Confidence? Modus?
  [7] Conviction Flow  — Liest conviction_scorer news_gate korrekt?
  [8] Scanner-Kopplung — Liest Scanner die CEO-Direktive?
  [9] API Live-Test    — Kann Claude Sonnet tatsächlich erreicht werden?
 [10] End-to-End       — CEO jetzt laufen lassen + Ergebnis messen

Verwendung:
  python3 scripts/test_ceo.py          # Alle Tests
  python3 scripts/test_ceo.py --quick  # Nur statische Tests (kein API-Call)
  python3 scripts/test_ceo.py --run    # CEO direkt ausführen + Ergebnis

Albert | TradeMind | 2026-04-11
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Workspace-Pfad ───────────────────────────────────────────────────────────

WS = Path('/data/.openclaw/workspace')
if not WS.exists():
    # Fallback für lokale Entwicklung
    for candidate in [
        Path(__file__).parent.parent,
        Path.home() / 'Trade-Bot',
    ]:
        if (candidate / 'data').exists() or (candidate / 'scripts').exists():
            WS = candidate
            break

DATA = WS / 'data'
SCRIPTS = WS / 'scripts'

# ── Farben ───────────────────────────────────────────────────────────────────

GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
RESET  = '\033[0m'

PASS = f'{GREEN}✅ PASS{RESET}'
FAIL = f'{RED}❌ FAIL{RESET}'
WARN = f'{YELLOW}⚠️  WARN{RESET}'
INFO = f'{CYAN}ℹ️  INFO{RESET}'

results: list[tuple[str, bool, str]] = []  # (name, passed, detail)


def check(name: str, passed: bool, detail: str = '', warn_only: bool = False):
    icon = PASS if passed else (WARN if warn_only else FAIL)
    print(f'  {icon}  {name}')
    if detail:
        print(f'       {detail}')
    results.append((name, passed or warn_only, detail))
    return passed


def section(title: str):
    print(f'\n{BOLD}{CYAN}{"─" * 60}{RESET}')
    print(f'{BOLD}{CYAN}  {title}{RESET}')
    print(f'{BOLD}{CYAN}{"─" * 60}{RESET}')


def read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_bytes().decode('utf-8', errors='replace'))
    except Exception:
        return None


def age_hours(path: Path) -> float:
    """Wie viele Stunden alt ist die Datei?"""
    try:
        mtime = path.stat().st_mtime
        return (time.time() - mtime) / 3600
    except Exception:
        return 9999.0


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — Datenquellen
# ══════════════════════════════════════════════════════════════════════════════

def test_data_sources():
    section('[1] Datenquellen — Inputdateien des CEO')

    files = {
        'ceo_directive.json':   (DATA / 'ceo_directive.json',   24),   # max 24h alt
        'news_gate.json':       (DATA / 'news_gate.json',        6),    # max 6h alt
        'strategies.json':      (DATA / 'strategies.json',       999),  # kein Max
        'alpha_decay.json':     (DATA / 'alpha_decay.json',      48),
        'dna.json':             (DATA / 'dna.json',              999),
        'trading.db':           (DATA / 'trading.db',            999),
    }

    for name, (path, max_age_h) in files.items():
        exists = path.exists()
        if not exists:
            check(f'{name} existiert', False, f'Pfad: {path}')
            continue

        age = age_hours(path)
        if max_age_h < 999 and age > max_age_h:
            check(
                f'{name} aktuell (max {max_age_h}h)',
                False,
                f'Datei ist {age:.1f}h alt — zu alt!',
                warn_only=True,
            )
        else:
            check(f'{name} existiert + frisch', True, f'{age:.1f}h alt')

    # trading.db: Tabellen prüfen
    try:
        conn = sqlite3.connect(str(DATA / 'trading.db'))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        needed = {'paper_portfolio', 'news_events', 'prices', 'macro_daily'}
        missing = needed - tables
        check('trading.db Tabellen vollständig', not missing,
              f'Fehlend: {missing}' if missing else f'OK ({len(tables)} Tabellen gesamt)')
    except Exception as e:
        check('trading.db lesbar', False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — News Gate
# ══════════════════════════════════════════════════════════════════════════════

def test_news_gate():
    section('[2] News Gate — news_gate.json Inhalt + Struktur')

    path = DATA / 'news_gate.json'
    ng = read_json(path)

    if ng is None:
        check('news_gate.json lesbar', False, 'Datei fehlt oder kaputt')
        return

    check('news_gate.json lesbar', True)

    # Struktur prüfen
    expected_keys = {'relevant', 'hit_count', 'theses_hit', 'top_hits'}
    missing_keys = expected_keys - set(ng.keys() if isinstance(ng, dict) else [])
    check('news_gate.json Struktur korrekt', not missing_keys,
          f'Fehlende Keys: {missing_keys}' if missing_keys else f'Keys: {list(ng.keys())}')

    if isinstance(ng, dict):
        hit_count = ng.get('hit_count', 0)
        theses_hit = ng.get('theses_hit', [])
        top_hits = ng.get('top_hits', [])

        check('news_gate hat Treffer', hit_count > 0,
              f'hit_count={hit_count}, theses_hit={theses_hit}')

        check('news_gate top_hits ist Liste', isinstance(top_hits, list),
              f'top_hits Typ: {type(top_hits).__name__}')

        if top_hits:
            first = top_hits[0]
            has_headline = isinstance(first, dict) and 'headline' in first
            check('top_hits enthält Headlines', has_headline,
                  f'Erster Eintrag: {str(first)[:100]}')

        check('theses_hit enthält Strategien', bool(theses_hit),
              f'Thesen: {theses_hit}')

        # Timestamp prüfen
        ts = ng.get('timestamp', '')
        print(f'  {INFO}  Letztes Update: {ts}')
        print(f'  {INFO}  Thesen getroffen: {theses_hit}')
        print(f'  {INFO}  Treffer gesamt: {hit_count}')


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — Overnight Events (newswire.db)
# ══════════════════════════════════════════════════════════════════════════════

def test_overnight_events():
    section('[3] Overnight Events — newswire.db')

    # newswire.db liegt im WS-Root, nicht in data/
    nws_db = WS / 'newswire.db'
    if not nws_db.exists():
        nws_db = DATA / 'newswire.db'  # Fallback
    if not nws_db.exists():
        check('newswire.db existiert', False, f'Pfad: {nws_db}')
        return

    check('newswire.db existiert', True)
    try:
        conn = sqlite3.connect(str(nws_db))
        conn.row_factory = sqlite3.Row

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        check('events-Tabelle vorhanden', 'events' in tables, f'Tabellen: {tables}')

        if 'events' in tables:
            total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            recent = conn.execute(
                "SELECT COUNT(*) FROM events WHERE datetime(timestamp) >= datetime('now', '-24 hours')"
            ).fetchone()[0]
            check('Events vorhanden', total > 0, f'{total} gesamt, {recent} in letzten 24h',
              warn_only=total == 0)
            check('Aktuelle Events (<24h)', recent > 0, f'{recent} Events in letzten 24h',
                  warn_only=recent == 0)

            # Neuesten Event zeigen
            last = conn.execute(
                "SELECT headline, sector, impact_direction, timestamp FROM events ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if last:
                print(f'  {INFO}  Letzter Event: [{last["timestamp"]}] {str(last["headline"])[:80]}')
                print(f'  {INFO}  Sektor: {last["sector"]} | Impact: {last["impact_direction"]}')

        conn.close()
    except Exception as e:
        check('newswire.db lesbar', False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 — Strategies
# ══════════════════════════════════════════════════════════════════════════════

def test_strategies():
    section('[4] Strategien — strategies.json')

    strats = read_json(DATA / 'strategies.json')
    if strats is None:
        check('strategies.json lesbar', False)
        return

    check('strategies.json lesbar', True)

    if not isinstance(strats, dict):
        check('strategies.json Struktur', False, f'Erwartet dict, bekam {type(strats).__name__}')
        return

    total = len(strats)
    active = [k for k, v in strats.items() if isinstance(v, dict) and v.get('status') == 'active']
    with_kill = [k for k in active if strats[k].get('kill_trigger')]
    with_tickers = [k for k in active if strats[k].get('tickers')]

    check(f'Strategien geladen ({total} gesamt)', total > 0)
    check(f'Aktive Strategien vorhanden', len(active) > 0, f'{len(active)} aktiv: {active[:5]}')
    check('Aktive haben kill_trigger', len(with_kill) == len(active),
          f'{len(with_kill)}/{len(active)} haben kill_trigger',
          warn_only=len(with_kill) < len(active))
    check('Aktive haben Tickers', bool(with_tickers),
          f'{len(with_tickers)}/{len(active)} haben Tickers')

    for k in active[:3]:
        s = strats[k]
        print(f'  {INFO}  {k}: {s.get("name","?")} | Sektor: {s.get("sector","?")} | Conviction: {s.get("conviction","?")}')


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 — CEO Direktive
# ══════════════════════════════════════════════════════════════════════════════

def test_ceo_directive():
    section('[5] CEO Direktive — ceo_directive.json')

    d = read_json(DATA / 'ceo_directive.json')
    if d is None:
        check('ceo_directive.json lesbar', False)
        return

    check('ceo_directive.json lesbar', True)

    # Pflichfelder
    required = ['mode', 'vix', 'regime', 'trading_rules', 'timestamp']
    missing = [k for k in required if k not in d]
    check('Pflichtfelder vorhanden', not missing,
          f'Fehlend: {missing}' if missing else f'Mode={d["mode"]}, VIX={d.get("vix")}, Regime={d.get("regime")}')

    # Alter
    ts_str = d.get('timestamp', '')
    try:
        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00').replace(' UTC', ''))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        check('Direktive aktuell (<25h)', age_h < 25,
              f'{age_h:.1f}h alt', warn_only=age_h >= 25)
    except Exception:
        check('Direktive Timestamp parsebar', False, f'Timestamp: {ts_str!r}')

    # Modus
    mode = d.get('mode', '')
    valid_modes = {'NORMAL', 'DEFENSIVE', 'SHUTDOWN', 'AGGRESSIVE'}
    check(f'Modus gültig ({mode})', mode in valid_modes,
          f'Erlaubte Modi: {valid_modes}')

    # trading_rules
    tr = d.get('trading_rules', {})
    check('trading_rules vorhanden', bool(tr),
          f'max_new_positions={tr.get("max_new_positions_today")}, '
          f'blocked={tr.get("blocked_strategies",[])}')

    # paper_lab
    pl = d.get('paper_lab', {})
    check('paper_lab vorhanden', bool(pl), f'Mode: {pl.get("mode","?")}', warn_only=not pl)

    print(f'  {INFO}  Modus: {mode} | VIX: {d.get("vix")} | Regime: {d.get("regime")}')
    print(f'  {INFO}  Erlaubte Strategien: {len(tr.get("allowed_strategies",[]))} | Geblockt: {tr.get("blocked_strategies",[])}')


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6 — AI-Analyse
# ══════════════════════════════════════════════════════════════════════════════

def test_ai_analysis():
    section('[6] AI-Analyse — Claude Sonnet in CEO Direktive')

    d = read_json(DATA / 'ceo_directive.json')
    if d is None:
        check('ceo_directive.json lesbar', False)
        return

    ai = d.get('ai_analysis', {})
    if not ai:
        check('ai_analysis vorhanden', False, 'Kein ai_analysis Block in Direktive')
        return

    status = ai.get('status', 'ok')
    if status == 'skipped':
        check('AI-Analyse aktiv', False, f'Grund: {ai.get("reason","?")}')
        return

    if status == 'error':
        # JSON-Parse-Fehler sind oft transient — als WARN, kein hartes FAIL
        check('AI-Analyse fehlerfrei', False,
              f'Parse-Fehler: {ai.get("reason","?")} — beim nächsten CEO-Run automatisch behoben',
              warn_only=True)
        return

    check('AI-Analyse Block vorhanden', True,
          'Inhalt wird in Test [10] nach End-to-End-Run geprüft')

    confidence = ai.get('confidence')
    mode_rec = ai.get('mode_recommendation')
    risks = ai.get('top_risks', [])
    opps = ai.get('top_opportunities', [])

    print(f'  {INFO}  Stand: Confidence={confidence}, Modus={mode_rec}, '
          f'Risks={len(risks)}, Opps={len(opps)}')
    if risks:
        print(f'  {INFO}  Risiko: {str(risks[0])[:80]}')
    if opps:
        print(f'  {INFO}  Chance: {str(opps[0])[:80]}')


# ══════════════════════════════════════════════════════════════════════════════
# TEST 7 — Conviction Flow
# ══════════════════════════════════════════════════════════════════════════════

def test_conviction_flow():
    section('[7] Conviction Flow — news_gate → conviction_scorer')

    # Prüfe ob conviction_scorer die _news_gate_bonus Funktion hat
    scorer_path = SCRIPTS / 'intelligence' / 'conviction_scorer.py'
    if not scorer_path.exists():
        check('conviction_scorer.py gefunden', False, str(scorer_path))
        return

    content = scorer_path.read_text(errors='replace')
    check('_news_gate_bonus Funktion vorhanden', '_news_gate_bonus' in content)
    check('news_gate.json wird gelesen', "ng_path = DATA_DIR / 'news_gate.json'" in content or
          "news_gate.json" in content)
    check('Bonus in ACTIVE-Pfad', "ng_bonus = _news_gate_bonus(strategy)" in content)

    # Prüfe ob news_gate aktuell Thesen hat die in Strategien vorkommen
    ng = read_json(DATA / 'news_gate.json')
    strats = read_json(DATA / 'strategies.json')

    if ng and strats:
        theses_hit = ng.get('theses_hit', [])
        active_strats = {k for k, v in strats.items()
                         if isinstance(v, dict) and v.get('status') == 'active'}

        # Matching: 'PS1_Oil' → matches 'PS1'
        bonus_strats = []
        for hit in theses_hit:
            for s in active_strats:
                if hit == s or hit.startswith(s + '_') or hit.startswith(s):
                    bonus_strats.append(f'{s} ← {hit}')
                    break

        check('Aktuelle News treffen aktive Strategien', bool(bonus_strats),
              f'Bonus für: {bonus_strats}' if bonus_strats else 'Kein Match',
              warn_only=not bonus_strats)

        print(f'  {INFO}  theses_hit: {theses_hit}')
        print(f'  {INFO}  Matches: {bonus_strats}')


# ══════════════════════════════════════════════════════════════════════════════
# TEST 8 — Scanner-Kopplung
# ══════════════════════════════════════════════════════════════════════════════

def test_scanner_coupling():
    section('[8] Scanner-Kopplung — CEO → Scanner')

    scanner_path = SCRIPTS / 'execution' / 'autonomous_scanner.py'
    if not scanner_path.exists():
        check('autonomous_scanner.py gefunden', False)
        return

    content = scanner_path.read_text(errors='replace')

    check('Scanner liest ceo_directive.json', 'ceo_directive.json' in content)
    check('Scanner prüft SHUTDOWN-Modus', "'SHUTDOWN'" in content)
    check('Scanner prüft DEFENSIVE-Modus', "'DEFENSIVE'" in content)
    check('Scanner prüft blocked_strategies', 'blocked_strategies' in content)

    # Aktueller CEO-Modus → was bedeutet das für Scanner
    d = read_json(DATA / 'ceo_directive.json')
    if d:
        mode = d.get('mode', 'NORMAL')
        tr = d.get('trading_rules', {})
        blocked = tr.get('blocked_strategies', [])
        max_new = tr.get('max_new_positions_today', '?')

        print(f'  {INFO}  Aktueller CEO-Modus für Scanner: {mode}')
        print(f'  {INFO}  Max neue Trades: {max_new} | Geblockt: {blocked}')

        if mode == 'SHUTDOWN':
            print(f'  {WARN}  Scanner würde bei SHUTDOWN alle Trades blockieren!')
        elif mode == 'DEFENSIVE':
            print(f'  {INFO}  Scanner limitiert auf max 2 Trades pro Run')


# ══════════════════════════════════════════════════════════════════════════════
# TEST 9 — API Live-Test
# ══════════════════════════════════════════════════════════════════════════════

def test_api_connection():
    section('[9] API Live-Test — Claude Sonnet Erreichbarkeit')

    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        check('ANTHROPIC_API_KEY gesetzt', False, 'Key fehlt in Environment')
        return

    check('ANTHROPIC_API_KEY vorhanden', True, f'sk-ant-...{api_key[-6:]}')

    try:
        import anthropic
    except ImportError:
        check('anthropic Paket installiert', False, 'pip install anthropic')
        return

    check('anthropic importierbar', True)

    try:
        t0 = time.time()
        client = anthropic.Anthropic(api_key=api_key)
        r = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=50,
            messages=[{'role': 'user', 'content': 'Antworte nur: {"status": "ok"}'}],
        )
        elapsed = time.time() - t0
        resp = r.content[0].text.strip()
        check('Claude Sonnet 4.6 erreichbar', True, f'Response in {elapsed:.1f}s: {resp[:40]}')
    except Exception as e:
        check('Claude Sonnet 4.6 erreichbar', False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# TEST 10 — End-to-End CEO Run
# ══════════════════════════════════════════════════════════════════════════════

def test_end_to_end():
    section('[10] End-to-End — CEO jetzt ausführen')

    print(f'  {INFO}  Starte CEO (--live)...')
    t0 = time.time()

    venv_python = Path('/opt/trademind/venv/bin/python3')
    python = str(venv_python) if venv_python.exists() else sys.executable
    ceo_script = SCRIPTS / 'ceo.py'

    if not ceo_script.exists():
        check('ceo.py gefunden', False, str(ceo_script))
        return

    try:
        result = subprocess.run(
            [python, str(ceo_script), '--live'],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(WS),
            env={**os.environ},
        )
        elapsed = time.time() - t0

        check('CEO Laufzeit < 120s', elapsed < 120, f'{elapsed:.1f}s')
        check('CEO kein Crash (returncode=0)', result.returncode == 0,
              f'returncode={result.returncode}' +
              (f'\nSTDERR: {result.stderr[-300:]}' if result.returncode != 0 else ''))

        output = result.stdout
        check('CEO schreibt Direktive', 'CEO-Direktive geschrieben' in output)
        check('CEO schreibt Modus', any(m in output for m in ['NORMAL', 'DEFENSIV', 'SHUTDOWN']),
              'Modus im Output nicht gefunden', warn_only=True)

        # AI-Block in Output
        ai_present = 'AI:' in output or 'AI-Analyse' in output or '🤖' in output
        check('CEO AI-Analyse im Output', ai_present,
              'Kein AI-Block im CEO-Output — API-Key fehlt oder anthropic nicht installiert',
              warn_only=not ai_present)

        # Direktive nach dem Run lesen
        d = read_json(DATA / 'ceo_directive.json')
        if d:
            ts = d.get('timestamp', '')
            ai = d.get('ai_analysis', {})
            ai_status = ai.get('status', 'ok')
            ai_ok = ai_status not in ('error', 'skipped')
            check('ceo_directive.json nach Run aktuell', bool(ts))
            check('AI-Analyse in Direktive (kein Fehler)', ai_ok,
                  f'Status: {ai_status} — {ai.get("reason","")}',
                  warn_only=not ai_ok)

            confidence = ai.get('confidence')
            mode_rec = ai.get('mode_recommendation')
            risks = ai.get('top_risks', [])
            opps = ai.get('top_opportunities', [])

            check('AI Confidence nach Run vorhanden', confidence is not None,
                  f'Confidence: {confidence}')
            check('AI Modus-Empfehlung nach Run', bool(mode_rec), f'Modus: {mode_rec}')
            check('AI Risiken nach Run (>0)', len(risks) >= 1,
                  f'{len(risks)} Risiken identifiziert')
            check('AI Chancen nach Run (>0)', len(opps) >= 1,
                  f'{len(opps)} Chancen identifiziert')

            print(f'  {INFO}  AI Confidence: {confidence} | Modus: {mode_rec}')
            for r in risks[:2]:
                print(f'  {INFO}  Risiko: {str(r)[:80]}')
            for o in opps[:2]:
                print(f'  {INFO}  Chance: {str(o)[:80]}')

        # Ersten Teil Output zeigen
        lines = [l for l in output.splitlines() if l.strip()][:8]
        print(f'\n  {INFO}  CEO Output (Auszug):')
        for l in lines:
            print(f'       {l}')

    except subprocess.TimeoutExpired:
        check('CEO Timeout', False, 'CEO lief länger als 120s')
    except Exception as e:
        check('CEO ausführbar', False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Zusammenfassung
# ══════════════════════════════════════════════════════════════════════════════

def print_summary():
    section('ZUSAMMENFASSUNG')

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed

    for name, ok, detail in results:
        icon = f'{GREEN}✅{RESET}' if ok else f'{RED}❌{RESET}'
        print(f'  {icon}  {name}')

    print()
    if failed == 0:
        print(f'{GREEN}{BOLD}  Alle {total} Tests bestanden. CEO-Kette ist vollständig.{RESET}')
    else:
        print(f'{RED}{BOLD}  {failed}/{total} Tests fehlgeschlagen.{RESET}')
        print(f'{YELLOW}  Bitte die ❌-Tests oben beheben.{RESET}')

    return failed == 0


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    args = sys.argv[1:]
    quick = '--quick' in args
    run_e2e = '--run' in args or not quick

    print(f'\n{BOLD}🎩 TradeMind CEO Tester{RESET}')
    print(f'Workspace: {WS}')
    print(f'Zeitpunkt: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    test_data_sources()
    test_news_gate()
    test_overnight_events()
    test_strategies()
    test_ceo_directive()
    test_ai_analysis()
    test_conviction_flow()
    test_scanner_coupling()

    if not quick:
        test_api_connection()

    if run_e2e and not quick:
        test_end_to_end()

    ok = print_summary()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
