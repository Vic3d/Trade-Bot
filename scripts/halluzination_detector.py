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
    r'\bstrategy\s+(PS\d+|S\d+|PT|PM|PS_[A-Z0-9_]+)\s+(?:ist|is)\s+active\b',
    r'\b(PS\d+|S\d+|PT|PM|PS_[A-Z0-9_]+)\s+steht\s+auf\s+(?:active|allowed)\b',
    # Phase 45l: "PS_NVO ist active" Pattern (war Lücke im Smoke-Test)
    r'\b(PS\d+|S\d+|DT\d+|PS_[A-Z0-9_]+)\s+(?:ist|wurde|war)\s+active\b',
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


def _live_numbers() -> dict:
    """Phase 45l: Live-Zahlen aus DB fuer Cross-Check.
    Returns dict mit cash, sharpe_lifetime, sharpe_30d, win_rate_30d.
    Werte koennen None sein wenn nicht verfuegbar."""
    out = {'cash_eur': None, 'sharpe_lifetime': None, 'sharpe_30d': None,
           'win_rate_30d_pct': None}
    if DB.exists():
        try:
            c = sqlite3.connect(str(DB))
            row = c.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()
            if row: out['cash_eur'] = float(row[0])
            row = c.execute(
                "SELECT COUNT(*) n, "
                " SUM(CASE WHEN pnl_eur>0 THEN 1 ELSE 0 END) wins "
                "FROM paper_portfolio WHERE close_date >= date('now','-30 days') "
                "AND pnl_eur IS NOT NULL"
            ).fetchone()
            if row and row[0]:
                out['win_rate_30d_pct'] = round(100.0 * row[1] / row[0], 1)
            c.close()
        except Exception: pass
    qf = WS / 'data' / 'quant_metrics.json'
    if qf.exists():
        try:
            q = json.loads(qf.read_text(encoding='utf-8'))
            at = q.get('all_time') or {}
            out['sharpe_lifetime'] = at.get('sharpe')
            l30 = q.get('last_30d') or {}
            out['sharpe_30d'] = l30.get('sharpe')
        except Exception: pass
    return out


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
            if actual is None or actual == 'unknown':
                continue  # Unbekannte SID — separate Klasse, ignorieren
            if actual != claimed_status:
                report.violations.append({
                    'kind': 'strategy_status_mismatch',
                    'claim': f'Text behauptet {sid} sei {claimed_status}',
                    'truth': f'{sid} ist tatsaechlich: {actual}',
                    'snippet': text[max(0,m.start()-30):m.end()+30],
                })

    # 2d. Phase 45y (C1): Kausal-Aussagen brauchen Inline-Tag.
    # Wenn Text Mechanik-Erklaerung enthaelt (z.B. "war Gap-Down",
    # "Slippage", "ist typisch fuer") MUSS ein [✓ DB:...] oder
    # [✓ truth-block] in der Naehe stehen, sonst WARN.
    CAUSAL_PATTERNS = [
        r'\b(?:gap[-\s]?down|gap[-\s]?up)\b',
        r'\bslippage\b',
        r'\bmarkt[-\s]risiko\b',
        r'\bphantom[-\s]?(tick|preis)\b',
        r'\bist\s+(typisch|klassisch)\s+f(ue|ü)r\b',
        r'\b(weil|because)\s+(?!.*\[✓)',  # "weil ..." ohne nachfolgenden Tag
    ]
    TAG_PATTERN = r'\[(?:✓|⚠|\?)\s*[A-Za-z:_]+'
    for pat in CAUSAL_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            # Suche [✓ ...] oder [⚠ ...] in den naechsten 200 Zeichen
            ctx_window = text[m.end():m.end()+200]
            has_tag = bool(re.search(TAG_PATTERN, ctx_window))
            if not has_tag:
                report.violations.append({
                    'kind': 'causal_claim_without_db_tag',
                    'claim': f'Kausale Aussage ohne Daten-Tag: "{m.group(0)}"',
                    'truth': 'Kausale Behauptungen brauchen [✓ DB:query] oder [✓ truth-block] inline',
                    'snippet': text[max(0,m.start()-30):m.end()+50],
                })
                break  # ein Treffer pro Pattern reicht

    # 2c. Phase 45l: Number-Cross-Check
    # Cash-Behauptungen (Toleranz 1.5%)
    nums = _live_numbers()
    if nums.get('cash_eur') is not None:
        live_cash = nums['cash_eur']
        # Patterns: "Cash 29.685", "Cash bei 29.685€", "29.685 EUR Cash"
        for m in re.finditer(
            r'(?:cash|guthaben|bestand)\s*(?:bei|von|von\s+)?\s*([\d.,]+)\s*(?:€|eur)?',
            text, re.IGNORECASE
        ):
            try:
                claimed = float(m.group(1).replace('.', '').replace(',', '.'))
                # Heuristik: wenn unter 1000 vermutlich nicht Cash sondern Position
                if claimed < 1000: continue
                if abs(claimed - live_cash) / max(live_cash, 1) > 0.015:
                    report.violations.append({
                        'kind': 'wrong_cash',
                        'claim': f'Text behauptet Cash {claimed:.0f} EUR',
                        'truth': f'Cash live: {live_cash:.0f} EUR',
                        'snippet': text[max(0,m.start()-30):m.end()+30],
                    })
                    break
            except Exception: continue

    # Sharpe-Behauptungen (Toleranz 0.15)
    for label, key in [('sharpe lifetime|sharpe all', 'sharpe_lifetime'),
                       ('sharpe 30d|sharpe letzte 30', 'sharpe_30d')]:
        if nums.get(key) is None: continue
        live = float(nums[key])
        for m in re.finditer(
            rf'(?:{label})\s*(?:bei|von|=)?\s*(-?\d+[.,]?\d*)',
            text, re.IGNORECASE
        ):
            try:
                claimed = float(m.group(1).replace(',', '.'))
                if abs(claimed - live) > 0.15:
                    report.violations.append({
                        'kind': 'wrong_number',
                        'claim': f'Text behauptet {key} = {claimed:.2f}',
                        'truth': f'{key} live: {live:.2f}',
                        'snippet': text[max(0,m.start()-30):m.end()+30],
                    })
            except Exception: continue

    # WR-30d (Toleranz 3pp)
    if nums.get('win_rate_30d_pct') is not None:
        live_wr = nums['win_rate_30d_pct']
        for m in re.finditer(
            r'(?:WR|win[- ]?rate)\s+(?:30d|letzte\s+30)\s*(?:bei|von|=)?\s*(\d+[.,]?\d*)\s*%?',
            text, re.IGNORECASE
        ):
            try:
                claimed = float(m.group(1).replace(',', '.'))
                if abs(claimed - live_wr) > 3.0:
                    report.violations.append({
                        'kind': 'wrong_number',
                        'claim': f'Text behauptet WR 30d = {claimed:.1f}%',
                        'truth': f'WR 30d live: {live_wr:.1f}%',
                        'snippet': text[max(0,m.start()-30):m.end()+30],
                    })
            except Exception: continue

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
