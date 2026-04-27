#!/usr/bin/env python3
"""
ceo_trade_reasoning.py — "Warum hast du Trade XYZ gemacht?"

Holt für einen Ticker (oder Trade-ID) ALLES was zur Decision geführt hat:
  - CEO-Decision (bull_case, bear_case, confidence, reasoning)
  - Mood + Calibration zum Zeitpunkt der Entscheidung
  - Direktive (mode, regime, vix, geo) zum Zeitpunkt
  - Conviction-Score
  - Verdict (Deep Dive)
  - Aktueller Status / Outcome

Wenn Trade noch OPEN: zeigt aktuelles unrealisiertes PnL.
Wenn closed: zeigt Real-Outcome vs damalige Erwartung.

Wird von discord_chat.py aufgerufen.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB             = WS / 'data' / 'trading.db'
DECISIONS_LOG  = WS / 'data' / 'ceo_decisions.jsonl'
VERDICTS_FILE  = WS / 'data' / 'deep_dive_verdicts.json'


def _load_decisions(ticker: str | None = None,
                     trade_id: int | None = None,
                     limit: int = 50) -> list[dict]:
    """Liest letzte N Decisions, optional gefiltert."""
    if not DECISIONS_LOG.exists():
        return []
    out = []
    for ln in DECISIONS_LOG.read_text(encoding='utf-8').strip().split('\n')[-1000:]:
        try:
            d = json.loads(ln)
            if ticker and (d.get('ticker') or '').upper() != ticker.upper():
                continue
            if trade_id and d.get('trade_id') != trade_id:
                continue
            out.append(d)
        except Exception:
            continue
    return out[-limit:]


def _get_trade(ticker: str | None = None, trade_id: int | None = None) -> dict | None:
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    if trade_id:
        row = c.execute(
            "SELECT * FROM paper_portfolio WHERE id = ?", (trade_id,)
        ).fetchone()
    elif ticker:
        # Bevorzuge OPEN, sonst neueste
        row = c.execute(
            "SELECT * FROM paper_portfolio WHERE ticker = ? AND status = 'OPEN' "
            "ORDER BY entry_date DESC LIMIT 1", (ticker,)
        ).fetchone()
        if not row:
            row = c.execute(
                "SELECT * FROM paper_portfolio WHERE ticker = ? "
                "ORDER BY entry_date DESC LIMIT 1", (ticker,)
            ).fetchone()
    else:
        row = None
    c.close()
    return dict(row) if row else None


def _get_current_price(ticker: str) -> float | None:
    try:
        from core.live_data import get_price_eur
        return get_price_eur(ticker)
    except Exception:
        return None


def _get_verdict(ticker: str) -> dict | None:
    try:
        if not VERDICTS_FILE.exists():
            return None
        d = json.loads(VERDICTS_FILE.read_text(encoding='utf-8'))
        v = d.get(ticker)
        return v if isinstance(v, dict) else None
    except Exception:
        return None


def explain_trade(query: str) -> str:
    """
    Hauptfunktion. query = "UNH" oder "trade 76" oder "XOM".
    Returns Discord-tauglichen Markdown-String.
    """
    query = query.strip()
    ticker = None
    trade_id = None

    # Parse: "trade 76" → trade_id=76
    if query.lower().startswith('trade '):
        try:
            trade_id = int(query.split()[1])
        except Exception:
            pass

    # Sonst: ist es ein Ticker?
    # Skip-Liste: häufige Wörter die wie Ticker aussehen aber keine sind
    SKIP_WORDS = {
        'WARUM', 'WIESO', 'HAST', 'TRADE', 'ERKLAR', 'ERKLAER', 'BEGRUND',
        'BEGRUEND', 'DU', 'DAS', 'DEN', 'DIE', 'DER', 'EIN', 'EINE',
        'GEKAUFT', 'KAUF', 'VERKAUF', 'VERKAUFT', 'TRADEST', 'MIR',
        'MICH', 'IST', 'WAR', 'BIST', 'WIE', 'WAS', 'WO', 'WANN',
        'OPEN', 'CLOSED', 'WIN', 'LOSS', 'ME', 'MIT', 'ZU', 'VON',
    }
    if not trade_id:
        # Bevorzuge Tokens mit Punkt/Strich (BMW.DE, EQNR.OL, BA.L) → klar Ticker
        candidates_with_dot = []
        candidates_pure = []
        for tok in query.split():
            tok = tok.strip('?,.!()[]{}"\'\'').upper()
            if not tok or tok in SKIP_WORDS:
                continue
            if not (1 <= len(tok) <= 10):
                continue
            if not tok.replace('.', '').replace('-', '').isalnum():
                continue
            if '.' in tok or '-' in tok:
                candidates_with_dot.append(tok)
            else:
                candidates_pure.append(tok)
        if candidates_with_dot:
            ticker = candidates_with_dot[0]
        elif candidates_pure:
            # Bei pure caps: nur 2-5 char Tickers + DB-Lookup
            for c in candidates_pure:
                if 2 <= len(c) <= 5:
                    # DB Check ob Ticker existiert
                    try:
                        conn = sqlite3.connect(str(DB))
                        row = conn.execute(
                            "SELECT 1 FROM paper_portfolio WHERE ticker = ? LIMIT 1", (c,)
                        ).fetchone()
                        conn.close()
                        if row:
                            ticker = c
                            break
                    except Exception:
                        pass
            if not ticker and candidates_pure:
                # Letzter Fallback: nimm wenigstens irgendeinen
                ticker = candidates_pure[0]

    if not ticker and not trade_id:
        return ('❓ Kein Ticker erkannt. Beispiel: "Warum hast du UNH gekauft?" '
                'oder "Erklär mir Trade 76".')

    trade = _get_trade(ticker=ticker, trade_id=trade_id)
    decisions = _load_decisions(ticker=ticker, trade_id=trade_id)

    if not trade and not decisions:
        return f'❓ Kein Trade oder Decision für {ticker or trade_id} gefunden.'

    lines = []

    # Header
    if trade:
        ticker = trade['ticker']
        status_icon = {'OPEN': '🟢', 'WIN': '✅', 'LOSS': '❌', 'CLOSED': '⚫'}.get(
            trade.get('status'), '?')
        lines.append(f'{status_icon} **{ticker}** ({trade.get("strategy")}) — '
                     f'Trade #{trade["id"]} | Status: {trade.get("status")}')
        lines.append(f'  Entry: {trade.get("entry_price"):.2f} | '
                     f'Stop: {trade.get("stop_price"):.2f} | '
                     f'Target: {trade.get("target_price"):.2f} | '
                     f'Shares: {trade.get("shares"):.2f}')
        lines.append(f'  Eingestiegen: {str(trade.get("entry_date",""))[:16]}')

        # Position-Wert
        pos_eur = (trade.get('entry_price') or 0) * (trade.get('shares') or 0)
        lines.append(f'  Position-Größe: {pos_eur:.0f}€')

        # Outcome wenn closed
        if trade.get('status') in ('WIN', 'LOSS', 'CLOSED'):
            pnl = trade.get('pnl_eur') or 0
            pct = trade.get('pnl_pct') or 0
            lines.append(f'  **Outcome: {pnl:+.0f}€ ({pct:+.1f}%)** | '
                         f'Exit-Type: {trade.get("exit_type") or "—"}')
        else:
            # Live Update
            curr = _get_current_price(ticker)
            if curr and trade.get('entry_price'):
                live_pct = (curr - trade['entry_price']) / trade['entry_price'] * 100
                live_pnl = (curr - trade['entry_price']) * (trade.get('shares') or 0)
                lines.append(f'  **Aktuell: {live_pnl:+.0f}€ ({live_pct:+.1f}%) live**')

    # Original-Reasoning vom Trade-Notes-Field
    if trade and trade.get('notes'):
        notes = trade['notes'][:500]
        lines.append(f'\n**📝 Original-Begründung:**\n_{notes}_')

    # Verdict
    verdict = _get_verdict(ticker) if ticker else None
    if verdict:
        lines.append(f'\n**🔬 Deep Dive Verdict:** {verdict.get("verdict")} '
                     f'(vom {(verdict.get("date") or "?")[:10]})')
        reasoning = verdict.get('reasoning', '')[:300]
        if reasoning:
            lines.append(f'  _{reasoning}_')

    # CEO-Brain Decision (wenn vorhanden)
    if decisions:
        latest = decisions[-1]
        action = latest.get('action', '?')
        confidence = latest.get('confidence')
        bull = latest.get('bull_case', '')
        bear = latest.get('bear_case', '')
        reason = latest.get('reason', '')
        expected = latest.get('expected_pct')
        memory_ref = latest.get('memory_ref') or latest.get('memory_reference', '')

        lines.append(f'\n**🧠 CEO-Brain Decision** ({latest.get("ts","")[:16]}):')
        lines.append(f'  Action: **{action}**'
                     + (f' | Confidence: **{confidence:.2f}**' if confidence else ''))
        if expected:
            lines.append(f'  Expected: {expected:+.1f}%')
        if bull:
            lines.append(f'  ▲ Bull: _{bull[:200]}_')
        if bear:
            lines.append(f'  ▼ Bear: _{bear[:200]}_')
        if reason:
            lines.append(f'  ℹ️ Reasoning: _{reason[:300]}_')
        if memory_ref:
            lines.append(f'  📚 Memory: _{memory_ref[:200]}_')

        # Wenn closed: Vergleich Decision vs Outcome
        if trade and trade.get('status') in ('WIN', 'LOSS', 'CLOSED'):
            actual_pct = trade.get('pnl_pct') or 0
            if expected:
                delta = actual_pct - expected
                verdict_str = ('✅ Erwartung getroffen' if abs(delta) < 3
                               else '❌ Realität wich ab')
                lines.append(f'\n**📊 Erwartung vs Realität:** '
                             f'erwartet {expected:+.1f}%, real {actual_pct:+.1f}% '
                             f'(Δ {delta:+.1f}%) → {verdict_str}')

    # Wenn keine CEO-Decision aber Trade existiert (Pre-Phase-32 Trade)
    elif trade:
        lines.append(f'\n_(Kein CEO-Brain Decision-Log für diesen Trade — Trade '
                     f'wurde vermutlich vor Phase 32a (Decision-Memory) gemacht.)_')

    return '\n'.join(lines)


def main() -> int:
    """CLI: python3 scripts/ceo_trade_reasoning.py UNH"""
    if len(sys.argv) < 2:
        print('Usage: python3 ceo_trade_reasoning.py <TICKER|"trade N">')
        return 1
    query = ' '.join(sys.argv[1:])
    print(explain_trade(query))
    return 0


if __name__ == '__main__':
    sys.exit(main())
