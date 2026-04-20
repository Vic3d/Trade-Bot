#!/usr/bin/env python3
"""
Verdicts → Proposals Generator (Phase 25 — Victor 2026-04-20)
=============================================================

Missing link in der autonomen Pipeline:
  Auto Deep Dive schreibt KAUFEN-Verdicts nach `data/deep_dive_verdicts.json`
  — aber nichts übersetzt diese in ausführbare Proposals.
  Dieses Skript schließt die Lücke.

Aufgabe:
  1. Lade `deep_dive_verdicts.json`, filtere `verdict == 'KAUFEN'` und
     Alter ≤ 7 Tage.
  2. Für jeden Kandidaten: berechne Entry (aktueller Preis),
     Stop (max von -7% und EMA50-Support), Target (+CRV-Multiple).
  3. Skip wenn:
     - Position bereits OPEN in paper_portfolio
     - Proposal mit status='active' existiert bereits
     - Keine Strategie zuordenbar
  4. Schreibe neue Proposals in `data/proposals.json` (append, mit dedupe).

Läuft als Pipeline-Step 2.5 zwischen Auto Deep Dive und Proposal Executor.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
log = logging.getLogger('verdicts_to_proposals')

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))

try:
    from atomic_json import atomic_write_json
except ImportError:
    def atomic_write_json(p, data, ensure_ascii=True):  # type: ignore
        p.write_text(json.dumps(data, indent=2, ensure_ascii=ensure_ascii), encoding='utf-8')

DATA = WS / 'data'
DB = DATA / 'trading.db'
VERDICTS_FILE = DATA / 'deep_dive_verdicts.json'
PROPOSALS_FILE = DATA / 'proposals.json'
STRATEGIES_FILE = DATA / 'strategies.json'

MAX_VERDICT_AGE_DAYS = 7
DEFAULT_STOP_PCT = 0.07       # 7% unter Entry
DEFAULT_CRV_MULTIPLE = 2.5    # Target = Entry + 2.5×Risk
MIN_POSITION_EUR = 500
MAX_POSITION_EUR = 1500


# ── Helpers ───────────────────────────────────────────────────────────

def _load(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        log.warning(f'load {p.name}: {e}')
    return default


def _save(p: Path, data) -> None:
    try:
        atomic_write_json(p, data, ensure_ascii=False)
    except Exception as e:
        log.warning(f'save {p.name}: {e}')


def _latest_price(ticker: str) -> float | None:
    try:
        c = sqlite3.connect(str(DB))
        row = c.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        c.close()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _ema50(ticker: str) -> float | None:
    try:
        c = sqlite3.connect(str(DB))
        rows = c.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 50",
            (ticker,),
        ).fetchall()
        c.close()
        closes = [float(r[0]) for r in rows if r[0] is not None]
        if len(closes) < 20:
            return None
        # simple average as EMA50 proxy — ausreichend für Support-Level
        return sum(closes) / len(closes)
    except Exception:
        return None


def _ticker_is_open(ticker: str) -> bool:
    try:
        c = sqlite3.connect(str(DB))
        row = c.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE UPPER(ticker)=UPPER(?) AND status='OPEN'",
            (ticker,),
        ).fetchone()
        c.close()
        return bool(row and row[0] > 0)
    except Exception:
        return False


def _find_strategy_for_ticker(ticker: str) -> str | None:
    """Sucht aktive Strategie in strategies.json. Fallback: 'PT'."""
    strats = _load(STRATEGIES_FILE, {})
    for sid, cfg in strats.items():
        if not isinstance(cfg, dict):
            continue
        status = str(cfg.get('status', 'active')).lower()
        if status not in ('active', 'alert', 'watching'):
            continue
        # ticker oder tickers Feld
        t_single = str(cfg.get('ticker', '')).upper()
        t_list = [str(t).upper() for t in cfg.get('tickers', [])]
        if t_single == ticker.upper() or ticker.upper() in t_list:
            return sid
    return None


def _verdict_is_fresh(v: dict) -> tuple[bool, int]:
    """Prüft ob Verdict innerhalb MAX_VERDICT_AGE_DAYS. Gibt (fresh, age_days)."""
    date_str = v.get('date') or v.get('updated_at', '')[:10]
    if not date_str:
        return False, -1
    try:
        d = datetime.fromisoformat(date_str[:10])
        age = (datetime.now() - d).days
        return age <= MAX_VERDICT_AGE_DAYS, age
    except Exception:
        return False, -1


def _build_proposal(ticker: str, verdict: dict, strategy: str) -> dict | None:
    """Baut Proposal-Entry mit Entry/Stop/Target."""
    # Entry-Preis: aus Verdict wenn vorhanden, sonst aktueller Kurs
    entry = float(verdict.get('entry') or 0)
    if entry <= 0:
        entry = _latest_price(ticker) or 0
    if entry <= 0:
        log.warning(f'  {ticker}: no price — skip')
        return None

    # Stop: max von -7% und EMA50-Support (nur wenn EMA unter Entry)
    stop_pct = entry * (1 - DEFAULT_STOP_PCT)
    ema = _ema50(ticker)
    if ema and ema < entry and ema > stop_pct:
        # EMA50 als engerer Stop wenn er über -7% liegt
        stop = round(ema * 0.995, 2)  # knapp unter EMA als Support
    else:
        stop = round(stop_pct, 2)

    # Verdict kann expliziten stop haben
    if verdict.get('stop'):
        try:
            stop = float(verdict['stop'])
        except Exception:
            pass

    risk = abs(entry - stop)
    target = round(entry + DEFAULT_CRV_MULTIPLE * risk, 2)
    if verdict.get('ziel_1') or verdict.get('target'):
        try:
            target = float(verdict.get('ziel_1') or verdict.get('target'))
        except Exception:
            pass

    # Position-Größe: Standard 1000€, skaliert mit Conviction/Score
    score = verdict.get('score') or verdict.get('conviction') or 50
    try:
        score = float(score)
    except Exception:
        score = 50
    # 500€ @ score 30, 1500€ @ score 80+
    pos_eur = max(MIN_POSITION_EUR, min(MAX_POSITION_EUR, (score - 20) * 20))
    shares = int(pos_eur / entry) if entry > 0 else 0

    crv = round((target - entry) / risk, 2) if risk > 0 else 0

    now = datetime.now(_BERLIN)
    proposal_id = f'AUTO_{ticker.replace(".", "_")}_{now.strftime("%Y%m%d_%H%M")}'

    return {
        'id': proposal_id,
        'ticker': ticker.upper(),
        'strategy': strategy,
        'direction': 'LONG',
        'entry_price': round(entry, 2),
        'stop': stop,
        'target': target,
        'target_1': target,
        'crv': crv,
        'shares': shares,
        'position_eur': round(pos_eur, 2),
        'risk_eur': round(risk * shares, 2),
        'conviction': score,
        'recommendation': 'BUY',
        'thesis': (verdict.get('reasons') or verdict.get('key_findings') or ['Auto Deep Dive KAUFEN'])[:1][0]
                  if isinstance(verdict.get('reasons'), list) else str(verdict.get('reasons', 'Auto Deep Dive KAUFEN'))[:200],
        'trigger': None,  # no trigger → executor führt direkt aus
        'status': 'active',
        'created_at': now.isoformat(timespec='seconds'),
        'source': 'verdicts_to_proposals',
        'verdict_source': verdict.get('source', 'auto_deepdive'),
        'verdict_date': verdict.get('date', ''),
    }


def _existing_active_proposal(proposals: list, ticker: str) -> bool:
    for p in proposals:
        if not isinstance(p, dict):
            continue
        if (p.get('ticker', '').upper() == ticker.upper()
                and p.get('status', 'active') in ('active', 'pending')):
            return True
    return False


# ── Main ──────────────────────────────────────────────────────────────

def run() -> dict:
    verdicts = _load(VERDICTS_FILE, {})
    proposals = _load(PROPOSALS_FILE, [])
    if not isinstance(proposals, list):
        proposals = []

    stats = {
        'verdicts_total': len(verdicts),
        'kaufen_candidates': 0,
        'generated': 0,
        'skipped_stale': 0,
        'skipped_open': 0,
        'skipped_duplicate': 0,
        'skipped_no_price': 0,
        'skipped_no_strategy': 0,
    }

    new_proposals = []

    for ticker, v in verdicts.items():
        if not isinstance(v, dict):
            continue
        if v.get('verdict') != 'KAUFEN':
            continue
        stats['kaufen_candidates'] += 1

        fresh, age = _verdict_is_fresh(v)
        if not fresh:
            log.info(f'  {ticker}: skip — verdict {age}d old (max {MAX_VERDICT_AGE_DAYS})')
            stats['skipped_stale'] += 1
            continue

        if _ticker_is_open(ticker):
            log.info(f'  {ticker}: skip — already OPEN')
            stats['skipped_open'] += 1
            continue

        if _existing_active_proposal(proposals, ticker):
            log.info(f'  {ticker}: skip — active proposal exists')
            stats['skipped_duplicate'] += 1
            continue

        strategy = v.get('strategy') or _find_strategy_for_ticker(ticker)
        if not strategy:
            # Fallback: generische Strategie basierend auf Quelle
            strategy = 'PT'  # Paper Thesis Swing — am breitesten erlaubt
            log.info(f'  {ticker}: kein strategy-match → fallback PT')

        proposal = _build_proposal(ticker, v, strategy)
        if proposal is None:
            stats['skipped_no_price'] += 1
            continue

        new_proposals.append(proposal)
        stats['generated'] += 1
        log.info(
            f'  ✅ {ticker} [{strategy}] entry={proposal["entry_price"]} '
            f'stop={proposal["stop"]} target={proposal["target"]} '
            f'CRV={proposal["crv"]}:1 pos={proposal["position_eur"]}€'
        )

    if new_proposals:
        proposals.extend(new_proposals)
        _save(PROPOSALS_FILE, proposals)
        log.info(f'✅ {len(new_proposals)} neue Proposals geschrieben')
    else:
        log.info('Keine neuen Proposals generiert')

    return stats


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    stats = run()
    print('\n── Verdicts → Proposals Summary ──')
    for k, v in stats.items():
        print(f'  {k:25} {v}')


if __name__ == '__main__':
    main()
