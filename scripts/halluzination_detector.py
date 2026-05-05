#!/usr/bin/env python3
"""
halluzination_detector.py — Phase 44ac: LLM-Output gegen DB cross-checken.

Komplementaer zu fact_audit (das nur banned phrases sucht). Hier wird
extrahiert WAS der LLM behauptet + verifiziert ob es stimmt:

  - "EQNR.OL ist offen" → check DB: ist EQNR.OL wirklich in OPEN-positions?
  - "PS_DEAD ist active"  → check strategies.json: ist PS_DEAD wirklich active?
  - "heute Montag"        → check date: ist heute wirklich Montag?

Returns: HalluzinationReport mit liste verifizierter Verstoesse.

Usage in call_llm-Wrapper:
  hr = check_halluzinations(text, context='ceo_action_log')
  if hr.has_violations: log_violation(text, hr.violations)
"""
from __future__ import annotations
import json, os, re, sqlite3, sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'halluzination_log.jsonl'


@dataclass
class HalluzinationReport:
    has_violations: bool = False
    violations: list = field(default_factory=list)


# Phrasen die "Position offen" implizieren
POSITION_CLAIM_PATTERNS = [
    r'\b([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\s+(?:hat\s+)?(?:ein|einen)?\s*Stop\s+(?:bei|von|auf)\b',
    r'\b([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\s+(?:Position|ist)\s+(?:offen|open)\b',
    r'(?:offene|open)\s+Position\s+([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\b',
    r'\bschliesse[n]?\s+([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\b',
]

# Phrasen die "Strategy active" implizieren
STRATEGY_ACTIVE_PATTERNS = [
    r'\bstrategy\s+(PS\d+|S\d+|PT|PM|PS_[A-Z]+)\s+(?:ist|is)\s+active\b',
    r'\b(PS\d+|S\d+|PT|PM|PS_[A-Z]+)\s+steht\s+auf\s+(?:active|allowed)\b',
]

# Phase 45l (PS5-Bug Fix): Status-Behauptungen cross-checken gegen
# strategies.json. Fängt 'PS5 ist retired', 'PS5 wurde paused', etc.
STRATEGY_STATUS_PATTERNS = [
    # "PS5 ist retired", "PS5 wurde paused", "PS5 retired", "PS5-Retire"
    r'\b(PS_?[A-Z0-9_]+|S\d+|DT\d+|PT|PM|AR-[A-Z]+)\b'
    r'(?:\s+(?:ist|wurde|war|wird|war\s+jetzt))?\s*[-:]?\s*'
    r'(retired|retire|paused|pause|watching|stopp(?:ed)?|deaktiviert|killed|gekillt)',
]

# Tokens die definitiv KEINE Tickers sind (deutsche/englische Stop-Worte
# die regex-mäßig wie Tickers aussehen). Verhindert "MIT", "DER" etc.
TICKER_BLACKLIST = {
    'MIT', 'DER', 'DIE', 'DAS', 'DEN', 'DEM', 'DES',
    'EIN', 'EINE', 'EINEN', 'EINER', 'EINEM',
    'UND', 'ODER', 'ABER', 'IST', 'WAR', 'SIND',
    'AN', 'IN', 'ON', 'AT', 'BY', 'TO', 'OF', 'IF', 'IT', 'AS', 'IS', 'BE',
    'CEO', 'CFO', 'CTO', 'API', 'SQL', 'CSV', 'JSON', 'HTML',
    'OK', 'NOK', 'JA', 'NEIN', 'YES', 'NO',
    'NEW', 'OLD', 'BIG', 'SMALL',
}

# Datum-Behauptungen
DAY_NAMES = {'montag','dienstag','mittwoch','donnerstag','freitag','samstag','sonntag',
             'monday','tuesday','wednesday','thursday','friday','saturday','sunday'}


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _open_position_tickers() -> set[str]:
    if not DB.exists(): return set()
    try:
        c = sqlite3.connect(str(DB))
        rows = c.execute("SELECT ticker FROM paper_portfolio WHERE status='OPEN'").fetchall()
        c.close()
        return {r[0].upper() for r in rows}
    except Exception:
        return set()


def _active_strategy_ids() -> set[str]:
    sf = WS / 'data' / 'strategies.json'
    if not sf.exists(): return set()
    try:
        d = json.loads(sf.read_text(encoding='utf-8'))
        return {sid for sid, v in d.items()
                if isinstance(v, dict) and v.get('status') == 'active'}
    except Exception:
        return set()


def _strategy_statuses() -> dict[str, str]:
    """Phase 45l: Vollstaendige Status-Map fuer Cross-Check.
    Returns: {SID: 'active'|'retired'|'paused'|'watching'|...}"""
    sf = WS / 'data' / 'strategies.json'
    if not sf.exists(): return {}
    try:
        d = json.loads(sf.read_text(encoding='utf-8'))
        return {sid: (v.get('status') or 'unknown')
                for sid, v in d.items() if isinstance(v, dict)}
    except Exception:
        return {}


def _today_weekday_de() -> str:
    try:
        from zoneinfo import ZoneInfo
        bt = datetime.now(ZoneInfo('Europe/Berlin'))
    except Exception:
        bt = datetime.now()
    return ['montag','dienstag','mittwoch','donnerstag','freitag','samstag','sonntag'][bt.weekday()]


def check_halluzinations(text: str, context: str = 'llm') -> HalluzinationReport:
    """Hauptfunktion: extrahiert Claims + verifiziert."""
    if not text: return HalluzinationReport()
    report = HalluzinationReport()

    open_tickers = _open_position_tickers()
    active_strats = _active_strategy_ids()
    today_de = _today_weekday_de()

    # 1. Position-Claims
    seen_position_claims = set()
    for pat in POSITION_CLAIM_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ticker = m.group(1).upper()
            # Phase 45l: Blacklist gegen False-Positives wie "MIT", "DER", "AN"
            if ticker in TICKER_BLACKLIST: continue
            if len(ticker) < 2: continue
            if ticker in seen_position_claims: continue
            seen_position_claims.add(ticker)
            if ticker not in open_tickers:
                report.violations.append({
                    'kind': 'position_not_open',
                    'claim': f'Text behauptet {ticker} sei offen',
                    'truth': f'Open positions: {sorted(open_tickers) or "KEINE"}',
                    'snippet': text[max(0,m.start()-30):m.end()+30],
                })

    # 2. Strategy-active-Claims
    for pat in STRATEGY_ACTIVE_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            sid = m.group(1).upper()
            if sid not in active_strats:
                report.violations.append({
                    'kind': 'strategy_not_active',
                    'claim': f'Text behauptet {sid} sei active',
                    'truth': f'Active strategies: {sorted(active_strats) or "(none)"}',
                    'snippet': text[max(0,m.start()-30):m.end()+30],
                })

    # 2b. Phase 45l: Strategy-Status-Behauptungen cross-check
    # Faengt 'PS5 ist retired', 'PS5-Retire', 'PS_NVO wurde paused', etc.
    statuses = _strategy_statuses()
    seen_status_claims = set()
    for pat in STRATEGY_STATUS_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            sid = m.group(1).upper()
            claimed_status_raw = m.group(2).lower()
            # Normalisiere claimed status
            status_map = {
                'retired': 'retired', 'retire': 'retired',
                'paused': 'paused', 'pause': 'paused',
                'watching': 'watching',
                'stopped': 'paused', 'stopp': 'paused',
                'deaktiviert': 'retired', 'killed': 'retired', 'gekillt': 'retired',
            }
            claimed_status = status_map.get(claimed_status_raw, claimed_status_raw)
            key = (sid, claimed_status)
            if key in seen_status_claims: continue
            seen_status_claims.add(key)
            actual = statuses.get(sid)
            if actual is None:
                continue  # Unbekannte SID — separate Klasse, ignorieren
            if actual != claimed_status:
                report.violations.append({
                    'kind': 'strategy_status_mismatch',
                    'claim': f'Text behauptet {sid} sei {claimed_status}',
                    'truth': f'{sid} ist tatsaechlich: {actual}',
                    'snippet': text[max(0,m.start()-30):m.end()+30],
                })

    # 3. Datums-Claims (nur wenn explizit "heute X" steht)
    for day in DAY_NAMES:
        m = re.search(r'\b(?:heute|today)\s+(?:ist\s+)?(' + day + r')\b', text, re.IGNORECASE)
        if m:
            claimed = m.group(1).lower()
            # English → German
            day_map = {'monday':'montag','tuesday':'dienstag','wednesday':'mittwoch',
                       'thursday':'donnerstag','friday':'freitag','saturday':'samstag','sunday':'sonntag'}
            claimed_de = day_map.get(claimed, claimed)
            if claimed_de != today_de:
                report.violations.append({
                    'kind': 'wrong_weekday',
                    'claim': f'Text behauptet heute sei {claimed}',
                    'truth': f'Heute ist {today_de.capitalize()}',
                    'snippet': text[max(0,m.start()-30):m.end()+30],
                })

    report.has_violations = len(report.violations) > 0

    if report.has_violations:
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'ts': _now(), 'context': context,
                    'n_violations': len(report.violations),
                    'violations': report.violations[:5],
                    'text_preview': text[:300],
                }, ensure_ascii=False) + '\n')
        except Exception: pass

    return report


def main() -> int:
    """CLI: scan a file or stdin."""
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding='utf-8')
    else:
        text = sys.stdin.read()
    r = check_halluzinations(text, context='cli')
    if r.has_violations:
        print(f'⚠️ {len(r.violations)} HALLUZINATIONEN GEFUNDEN:')
        for v in r.violations:
            print(f"  · [{v['kind']}] {v['claim']}")
            print(f"    Wahrheit: {v['truth']}")
            print(f"    Snippet:  ...{v['snippet']}...")
    else:
        print('✅ Keine Halluzinationen erkannt.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
