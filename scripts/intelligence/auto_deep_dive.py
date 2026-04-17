#!/usr/bin/env python3
"""
Auto Deep Dive — Phase 7.13 (echte Autonomie)
================================================
Albert macht Deep Dives selbst via Claude API — kein Victor noetig.

Trigger:
  - Scanner findet Tier-A-Signal
  - Thesis-Monitor eroeffnet neue Thesis
  - Explizit via CLI: python3 auto_deep_dive.py TICKER

Pipeline:
  1) Sammle Fakten (Preis, EMA50/200, RSI, 52W-Range, Volume, Sektor,
     News-Headlines der letzten 7 Tage) aus der DB + live-Quellen
  2) Baue strikt faktenbasierten Prompt (memory/deepdive-protokoll.md
     ist die Leitlinie)
  3) Claude API Call (opus oder sonnet via ANTHROPIC_MODEL env)
  4) Anti-Halluzinations-Check: Claude-Output wird gegen die Fakten
     geprueft. Wenn Claude schreibt "EMA50 steigend" aber Fakt sagt
     fallend -> Verdict wird auf WARTEN degradiert mit reason=FACTS_MISMATCH
  5) Verdict + Confidence + Reasoning speichern in
     data/deep_dive_verdicts.json mit source: "AUTO_CLAUDE"

Output-Struktur pro Ticker in deep_dive_verdicts.json:
{
  "TICKER": {
    "verdict": "KAUFEN" | "WARTEN" | "NICHT_KAUFEN",
    "confidence": 0-100,
    "source": "AUTO_CLAUDE",
    "model": "claude-sonnet-4-5",
    "timestamp": "2026-04-17T..",
    "facts": {...},
    "reasoning": "...",
    "mismatch_warnings": [...]
  }
}

CLI:
  python3 scripts/intelligence/auto_deep_dive.py AAPL
  python3 scripts/intelligence/auto_deep_dive.py AAPL --force  # auch wenn <14d fresh
  python3 scripts/intelligence/auto_deep_dive.py AAPL --dry    # prompt ausgeben, kein API-Call

ENV:
  ANTHROPIC_API_KEY  (pflicht)
  ANTHROPIC_MODEL    (optional, default claude-sonnet-4-5)
  AUTO_DD_MAX_TOKENS (optional, default 2500)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
VERDICTS = WS / 'data' / 'deep_dive_verdicts.json'
PROTOCOL = WS / 'memory' / 'deepdive-protokoll.md'

sys.path.insert(0, str(WS / 'scripts'))

# ────────────────────────────────────────────────────────────────────────────
# Fakten-Sammlung
# ────────────────────────────────────────────────────────────────────────────


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c


def _get_price_data(ticker: str) -> dict:
    """Preis, 20/50/200 SMA, RSI, 52W-Range aus DB."""
    out: dict = {'ticker': ticker, 'facts_ok': False}
    try:
        c = _conn()
        # Letzte 260 Tage für 200-SMA + 52W-Range
        rows = c.execute(
            "SELECT date, close, high, low, volume FROM prices "
            "WHERE ticker=? ORDER BY date DESC LIMIT 260",
            (ticker.upper(),),
        ).fetchall()
        c.close()
        if len(rows) < 60:
            out['error'] = f'Zu wenig Preis-Daten ({len(rows)} Tage)'
            return out

        closes = [float(r['close']) for r in rows]
        highs = [float(r['high'] or r['close']) for r in rows]
        lows = [float(r['low'] or r['close']) for r in rows]
        latest = closes[0]

        def sma(n: int) -> float | None:
            if len(closes) < n:
                return None
            return sum(closes[:n]) / n

        # RSI(14) — Wilders approximation
        def rsi14() -> float | None:
            if len(closes) < 15:
                return None
            gains, losses = 0.0, 0.0
            # closes[0] is latest; diffs oldest→newest ist umgekehrt
            for i in range(1, 15):
                diff = closes[i - 1] - closes[i]
                if diff > 0:
                    gains += diff
                else:
                    losses -= diff
            avg_g, avg_l = gains / 14, losses / 14
            if avg_l == 0:
                return 100.0
            rs = avg_g / avg_l
            return 100 - (100 / (1 + rs))

        w52_high = max(highs[:260]) if highs else latest
        w52_low = min(lows[:260]) if lows else latest
        ma50 = sma(50)
        ma200 = sma(200)
        ma20 = sma(20)

        # 3M-Trend = Performance vs 63d ago
        trend_3m = None
        if len(closes) >= 63:
            trend_3m = (latest - closes[62]) / closes[62] * 100

        out.update({
            'facts_ok': True,
            'latest_price': round(latest, 4),
            'ma20': round(ma20, 4) if ma20 else None,
            'ma50': round(ma50, 4) if ma50 else None,
            'ma200': round(ma200, 4) if ma200 else None,
            'rsi14': round(rsi14() or 0, 1) if rsi14() else None,
            'high_52w': round(w52_high, 4),
            'low_52w': round(w52_low, 4),
            'pct_from_52w_high': round((latest - w52_high) / w52_high * 100, 2),
            'pct_from_52w_low': round((latest - w52_low) / w52_low * 100, 2),
            'trend_3m_pct': round(trend_3m, 2) if trend_3m is not None else None,
            'price_date_latest': rows[0]['date'],
            'n_days_data': len(rows),
        })
        # Derived flags
        if ma50 and ma200:
            out['above_ma50'] = latest > ma50
            out['above_ma200'] = latest > ma200
            out['ma50_above_ma200'] = ma50 > ma200  # golden cross state
        return out
    except Exception as e:
        out['error'] = str(e)[:200]
        return out


def _get_sector(ticker: str) -> str:
    try:
        from portfolio_risk import get_sector
        return get_sector(ticker)
    except Exception:
        return 'unknown'


def _get_recent_news(ticker: str, days: int = 7) -> list[dict]:
    """News-Headlines aus DB (wenn vorhanden)."""
    try:
        c = _conn()
        # Best effort - news table schema variiert
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = c.execute(
            "SELECT title, COALESCE(source,'?') as source, "
            "COALESCE(published_date, published, date) as pub "
            "FROM news WHERE "
            "(tickers LIKE ? OR title LIKE ? OR ticker = ?) "
            "AND COALESCE(published_date, published, date) >= ? "
            "ORDER BY COALESCE(published_date, published, date) DESC LIMIT 8",
            (f'%{ticker}%', f'%{ticker}%', ticker, cutoff),
        ).fetchall()
        c.close()
        return [{'title': r['title'], 'source': r['source'], 'pub': r['pub']} for r in rows]
    except Exception:
        return []


def _get_regime() -> dict:
    try:
        c = _conn()
        r = c.execute(
            "SELECT date, regime, vix FROM regime_history ORDER BY date DESC LIMIT 1"
        ).fetchone()
        c.close()
        if r:
            return {'regime': r['regime'], 'vix': r['vix'], 'date': r['date']}
    except Exception:
        pass
    return {}


def collect_facts(ticker: str) -> dict:
    """Alle Fakten die im Prompt landen — KEINE Meinungen."""
    return {
        'ticker': ticker.upper(),
        'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'price': _get_price_data(ticker),
        'sector': _get_sector(ticker),
        'regime': _get_regime(),
        'news_recent': _get_recent_news(ticker),
    }


# ────────────────────────────────────────────────────────────────────────────
# Prompt-Bau
# ────────────────────────────────────────────────────────────────────────────


def build_prompt(facts: dict, mode: str = 'entry', position_ctx: dict | None = None) -> str:
    """
    mode='entry' — standard Entry-Frage (KAUFEN/WARTEN/NICHT_KAUFEN)
    mode='hold'  — Hold-Check fuer offene Position. Gleiches Schema, aber
                   Claude weiss: wir haben die Aktie schon. NICHT_KAUFEN = Exit-Signal.
    """
    p = facts['price']
    if not p.get('facts_ok'):
        raise ValueError(f"Keine Fakten fuer {facts['ticker']}: {p.get('error')}")

    news_block = ''
    if facts['news_recent']:
        lines = [f"- [{n['pub'][:10]}] ({n['source']}) {n['title']}" for n in facts['news_recent'][:6]]
        news_block = '\n'.join(lines)
    else:
        news_block = '(keine News in DB gefunden — Vorsicht, Katalysator-Frische nicht validiert)'

    regime = facts['regime']
    regime_block = (
        f"Markt-Regime: {regime.get('regime', '?')} | VIX: {regime.get('vix', '?')} "
        f"(Stand: {regime.get('date', '?')})"
        if regime else 'Markt-Regime: unbekannt'
    )

    # Mode-spezifischer Kontext-Block
    mode_header = ''
    if mode == 'hold' and position_ctx:
        entry_p = position_ctx.get('entry_price')
        curr_p = p.get('latest_price')
        try:
            pnl_pct = ((curr_p - entry_p) / entry_p) * 100 if entry_p and curr_p else None
        except Exception:
            pnl_pct = None
        days_held = position_ctx.get('days_held', '?')
        mode_header = f"""
### HOLD-CHECK MODUS — Position ist bereits offen!
  Entry-Preis:       {entry_p} EUR
  Aktueller P&L:     {pnl_pct:+.1f}% {'(im Plus)' if pnl_pct and pnl_pct > 0 else '(im Minus)' if pnl_pct else ''}
  Tage gehalten:     {days_held}
  Strategie:         {position_ctx.get('strategy', '?')}

Deine Aufgabe: Pruefe ob die Thesis noch gueltig ist. Suche aktiv nach **Leichen im Keller**
— Downgrades, neue Politik-Risiken, Bilanz-Probleme, Konkurrent-Moves.

Verdict-Mapping fuer Hold-Check:
  KAUFEN       = Thesis intakt → HALTEN
  WARTEN       = Gelb, Vorsicht → Position halten, kein Aufstocken
  NICHT_KAUFEN = **EXIT-SIGNAL** → Position schliessen (Leiche entdeckt)
"""

    task_line = (
        f"**Hold-Verdict** fuer {facts['ticker']} — sollen wir die offene Position halten?"
        if mode == 'hold'
        else f"**Trading-Verdict** fuer {facts['ticker']} nach dem Deep-Dive-Protokoll."
    )

    # Scenario-Kontext aus dem Scenario-Mapper laden (falls vorhanden)
    scenario_context = ''
    try:
        sm_path = WS / 'data' / 'scenario_map.json'
        if sm_path.exists():
            sm = json.loads(sm_path.read_text(encoding='utf-8'))
            top_scenarios = sm.get('top_catalysts', [])[:3]
            if top_scenarios:
                lines = []
                for c in top_scenarios:
                    lines.append(f"- {c.get('name','?')} ({c.get('date','?')}): {c.get('summary','')[:160]}")
                    for sc in c.get('scenarios', [])[:3]:
                        lines.append(f"   · {sc.get('label','?')} P={sc.get('probability',0)}: Winners={sc.get('winners',[])[:5]} Losers={sc.get('losers',[])[:5]}")
                scenario_context = "\n### AKTIVE TOP-KATALYSATOREN (aus Scenario-Map)\n" + '\n'.join(lines)
    except Exception:
        pass

    # Kalibrierungs-Feedback aus dem Thesis-Graveyard (Phase 22 Closed-Loop)
    calibration_context = ''
    try:
        import sys as _sys
        _scripts = WS / 'scripts'
        if str(_scripts) not in _sys.path:
            _sys.path.insert(0, str(_scripts))
        from thesis_graveyard import build_calibration_block
        calibration_context = build_calibration_block(max_missed=3)
    except Exception:
        calibration_context = ''

    # Positioning-Kontext (Pain-Trade Detector)
    positioning_context = ''
    try:
        pt_path = WS / 'data' / 'positioning.json'
        if pt_path.exists():
            pt = json.loads(pt_path.read_text(encoding='utf-8'))
            sector = (facts.get('sector') or '').lower()
            sector_data = pt.get('sectors', {}).get(sector) or pt.get(sector)
            if sector_data:
                positioning_context = (
                    f"\n### POSITIONIERUNG (Pain-Trade-Layer)\n"
                    f"Sektor '{sector}': Positioning={sector_data.get('positioning','?')} "
                    f"State={sector_data.get('state','?')} Pain-Trade={sector_data.get('pain_trade','?')}\n"
                    f"Aggregiert: Put/Call={pt.get('put_call_ratio','?')} "
                    f"AAII-Bullish={pt.get('aaii_bullish','?')} VIX-Struktur={pt.get('vix_structure','?')}"
                )
    except Exception:
        pass

    prompt = f"""Du bist Albert, der AI-CEO von TradeMind. Du machst einen Deep Dive fuer
den Paper-Trading-Bot im Auftrag von Victor.

Deine Aufgabe: {task_line}
{mode_header}

KRITISCH — NEUES MINDSET (Phase 22, seit 17.04.2026):
Du denkst NICHT mehr rueckwaertsgewandt ("ist RSI okay, ist Preis ueber MA50").
Du denkst VORWAERTSGEWANDT und in SZENARIEN wie ein Hedge-Fund-Analyst:

  1. Welches konkrete Event aufloest diese These in den naechsten 14 Tagen?
  2. Wenn Event in Richtung X aufloest: wieviel % Upside? Wenn Richtung Y: wieviel Downside?
  3. Wo liegt der Marktkonsens aktuell? Ist der Trade ein Pain-Trade (Contrarian) oder Crowd-Trade?
  4. Was ist der Expected Value (Wahrscheinlichkeit x Payoff - Transaktionskosten)?

Technische Daten sind KONTEXT, nicht der Treiber. Ein Ticker der RSI 78 hat kann trotzdem KAUFEN
sein wenn ein asymmetrischer Katalysator mit EV > +€50 ansteht. Ein Ticker mit Golden Cross
kann NICHT_KAUFEN sein wenn er bereits Konsens-Long ist und Pain-Trade ist short.

HARTE REGEL: Wenn du keinen spezifischen Katalysator in den naechsten 30 Tagen nennen kannst,
lautet das Verdict WARTEN mit Begruendung "kein benannter Katalysator".

### HARTE FAKTEN (aus DB, {facts['timestamp'][:19]})
Ticker: {facts['ticker']}
Sektor: {facts['sector']}
{regime_block}

Preis & Technik:
  Preis aktuell:     {p['latest_price']} EUR
  Preis-Datum:       {p['price_date_latest']}
  20-SMA:            {p.get('ma20')}
  50-SMA:            {p.get('ma50')}
  200-SMA:           {p.get('ma200')}
  RSI(14):           {p.get('rsi14')}
  52W-Hoch:          {p['high_52w']}  ({p['pct_from_52w_high']}% entfernt)
  52W-Tief:          {p['low_52w']}  ({p['pct_from_52w_low']}% darueber)
  3M-Trend:          {p.get('trend_3m_pct')}%
  Ueber MA50:        {p.get('above_ma50')}
  Ueber MA200:       {p.get('above_ma200')}
  Golden Cross:      {p.get('ma50_above_ma200')}

Recent News (letzte 7 Tage):
{news_block}
{scenario_context}
{positioning_context}
{calibration_context}

### DEEP DIVE PROTOKOLL (Scenario-based, Phase 22)
1. **Katalysator identifizieren** — Welches benannte Event (Datum!) loest die These aus?
   → Kein Katalysator in 30 Tagen = WARTEN
2. **Szenario-Mapping** — Mind. 2 Szenarien (bullish Case, bearish Case):
   → P(bull) + P(bear) + P(side) = 1.0
   → Fuer jedes Szenario: erwartete Rendite auf 14-Tage-Sicht in %
3. **Expected Value (EV)** berechnen:
   → EV_pct = P_bull * rendite_bull_pct + P_bear * rendite_bear_pct + P_side * rendite_side_pct
   → EV_eur = EV_pct * 1500 / 100  (Annahme: €1.500 Position)
4. **Payoff-Skew** — rendite_bull_pct / abs(rendite_bear_pct) >= 1.5 ?
5. **Positionierung** — Ist dieser Trade Consensus oder Contrarian (Pain-Trade)?
6. **Pre-Mortem / Falsifikation** — Welches einzelne Event wuerde diese These killen?

### ENTSCHEIDUNGS-LOGIK (neu)
- EV_eur > +€50 UND Skew >= 2.0 UND Katalysator vorhanden → KAUFEN
- EV_eur > +€10 UND Skew >= 1.5 UND Katalysator vorhanden → KAUFEN (half-size signal)
- EV_eur zwischen -€10 und +€10 → WARTEN
- EV_eur < -€10 oder Falling Knife bestaetigt → NICHT_KAUFEN
- Kein benannter Katalysator → WARTEN (egal wie gut die Technik aussieht)

### KILLER-REGELN (Override-Kriterien)
- Preis < EMA50 UND 3M-Trend < -20%  → NICHT_KAUFEN (echter Falling Knife)
- 50%+ unter 52W-Hoch ohne Katalysator  → NICHT_KAUFEN
- Consensus crowded long UND RSI > 80 → WARTEN (Pain-Trade-Gefahr)

### OUTPUT-FORMAT (streng, Phase-22-Schema)
Gib AUSSCHLIESSLICH valides JSON zurueck, KEIN Markdown.

{{
  "verdict": "KAUFEN" | "WARTEN" | "NICHT_KAUFEN",
  "confidence": <int 0-100>,
  "reasoning": "<2-3 Saetze warum>",
  "katalysator": "<konkretes Event + Datum, z.B. 'FOMC 24.04' oder 'keiner erkennbar'>",
  "catalyst_date": "<YYYY-MM-DD oder null>",
  "scenarios": [
    {{"label": "bull", "probability": 0.45, "expected_return_pct": 8.0, "trigger": "<was muss passieren>"}},
    {{"label": "bear", "probability": 0.45, "expected_return_pct": -4.0, "trigger": "<was muss passieren>"}},
    {{"label": "side", "probability": 0.10, "expected_return_pct": 0.0, "trigger": "<was muss passieren>"}}
  ],
  "ev_pct": <float, berechnet aus scenarios>,
  "ev_eur": <float, ev_pct * 1500 / 100>,
  "payoff_skew": <float, rendite_bull / abs(rendite_bear)>,
  "consensus_position": "crowded_long" | "crowded_short" | "neutral" | "contrarian_opp",
  "pain_trade_flag": <true|false, ob dies ein Contrarian-Trade gegen den Konsens ist>,
  "falsification": "<welches konkrete Event wuerde diese These zerstoeren>",
  "target_hold_days": <int, typisch 7-30>,
  "entry_price_hint": <float oder null>,
  "stop_pct_hint": <float, z.B. -6.0>,
  "target_pct_hint": <float, z.B. +12.0>,
  "key_risks": ["<risiko1>", "<risiko2>"],
  "facts_claims": {{
    "above_ma50": <true|false|null>,
    "above_ma200": <true|false|null>,
    "trend_3m_positive": <true|false|null>,
    "rsi_overbought": <true|false|null>
  }}
}}

WICHTIG: Der Score basiert auf EV+Skew, NICHT mehr nur auf Confidence.
Ein Trade mit EV +€80 und Skew 3.0 bei Confidence 55% ist besser als ein Trade
mit EV +€5 und Skew 1.1 bei Confidence 80%. Pro-HF-Logik: Asymmetrie schlaegt Sicherheit.
"""
    return prompt


# ────────────────────────────────────────────────────────────────────────────
# Claude Call
# ────────────────────────────────────────────────────────────────────────────


def call_claude(prompt: str, model: str | None = None, max_tokens: int = 2500) -> tuple[str, dict]:
    """
    Ruft Anthropic API auf. Raises bei Fehler.
    Returns: (text, usage_dict) mit input_tokens / output_tokens / cost_usd_est
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise RuntimeError('ANTHROPIC_API_KEY nicht gesetzt')
    model = model or os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-4-5')

    try:
        import anthropic
    except ImportError:
        raise RuntimeError('anthropic package nicht installiert (pip install anthropic)')

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    # Extrahiere Text
    content = resp.content[0].text if resp.content else ''

    # Token-Kosten (opus-4-5: $15/MTok input, $75/MTok output — konservativ)
    # sonnet: $3/MTok input, $15/MTok output
    usage = {
        'input_tokens': getattr(resp.usage, 'input_tokens', 0) if resp.usage else 0,
        'output_tokens': getattr(resp.usage, 'output_tokens', 0) if resp.usage else 0,
    }
    if 'opus' in model.lower():
        usage['cost_usd_est'] = (usage['input_tokens'] * 15 + usage['output_tokens'] * 75) / 1_000_000
    else:
        usage['cost_usd_est'] = (usage['input_tokens'] * 3 + usage['output_tokens'] * 15) / 1_000_000
    return content, usage


def parse_verdict(text: str) -> dict:
    """Extrahiere JSON aus Claude-Output, auch wenn Markdown drum rum."""
    # Suche das erste {...} Block
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise ValueError('Kein JSON im Claude-Output gefunden')
    return json.loads(m.group(0))


# ────────────────────────────────────────────────────────────────────────────
# Anti-Halluzinations-Check
# ────────────────────────────────────────────────────────────────────────────


def check_hallucinations(facts: dict, verdict: dict) -> list[str]:
    """Vergleicht Claude's facts_claims mit den harten Fakten. Liste Mismatches."""
    warnings = []
    p = facts['price']
    claims = verdict.get('facts_claims', {}) or {}

    if claims.get('above_ma50') is not None and p.get('above_ma50') is not None:
        if claims['above_ma50'] != p['above_ma50']:
            warnings.append(f"above_ma50 MISMATCH: Claude={claims['above_ma50']} DB={p['above_ma50']}")
    if claims.get('above_ma200') is not None and p.get('above_ma200') is not None:
        if claims['above_ma200'] != p['above_ma200']:
            warnings.append(f"above_ma200 MISMATCH: Claude={claims['above_ma200']} DB={p['above_ma200']}")
    if claims.get('trend_3m_positive') is not None and p.get('trend_3m_pct') is not None:
        db_positive = p['trend_3m_pct'] > 0
        if claims['trend_3m_positive'] != db_positive:
            warnings.append(
                f"trend_3m MISMATCH: Claude={claims['trend_3m_positive']} DB={p['trend_3m_pct']}%"
            )
    if claims.get('rsi_overbought') is not None and p.get('rsi14') is not None:
        db_overbought = p['rsi14'] > 70
        if claims['rsi_overbought'] != db_overbought:
            warnings.append(
                f"rsi_overbought MISMATCH: Claude={claims['rsi_overbought']} DB-RSI={p['rsi14']}"
            )
    return warnings


# ────────────────────────────────────────────────────────────────────────────
# Persistenz
# ────────────────────────────────────────────────────────────────────────────


def load_verdicts() -> dict:
    try:
        return json.loads(VERDICTS.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_verdict(ticker: str, verdict: dict, facts: dict, warnings: list[str], model: str) -> None:
    try:
        from atomic_json import atomic_write_json
        writer = atomic_write_json
    except Exception:
        def writer(p, d):
            Path(p).write_text(json.dumps(d, indent=2, ensure_ascii=False))

    data = load_verdicts()
    # Kompatibel zum bisherigen Format (einfaches Verdict pro Ticker)
    final_verdict = verdict.get('verdict')
    if warnings and final_verdict == 'KAUFEN':
        # Bei Halluzinations-Mismatch downgrade
        final_verdict = 'WARTEN'
        verdict['_degraded_from'] = 'KAUFEN'
        verdict['_degraded_reason'] = 'FACTS_MISMATCH'

    data[ticker.upper()] = {
        'verdict': final_verdict,
        'confidence': verdict.get('confidence'),
        'reasoning': verdict.get('reasoning'),
        'key_risks': verdict.get('key_risks', []),
        'katalysator': verdict.get('katalysator'),
        'catalyst_date': verdict.get('catalyst_date'),
        'target_hold_days': verdict.get('target_hold_days'),
        # Phase 22 — Scenario + EV fields
        'scenarios': verdict.get('scenarios', []),
        'ev_pct': verdict.get('ev_pct'),
        'ev_eur': verdict.get('ev_eur'),
        'payoff_skew': verdict.get('payoff_skew'),
        'consensus_position': verdict.get('consensus_position'),
        'pain_trade_flag': verdict.get('pain_trade_flag'),
        'falsification': verdict.get('falsification'),
        'entry_price_hint': verdict.get('entry_price_hint'),
        'stop_pct_hint': verdict.get('stop_pct_hint'),
        'target_pct_hint': verdict.get('target_pct_hint'),
        'source': 'AUTO_CLAUDE',
        'model': model,
        'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'mismatch_warnings': warnings,
        'facts_snapshot': {
            'price': facts['price'].get('latest_price'),
            'ma50': facts['price'].get('ma50'),
            'ma200': facts['price'].get('ma200'),
            'rsi14': facts['price'].get('rsi14'),
            'trend_3m': facts['price'].get('trend_3m_pct'),
            'pct_from_52w_high': facts['price'].get('pct_from_52w_high'),
        },
    }
    writer(VERDICTS, data)


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────


def run(
    ticker: str,
    *,
    force: bool = False,
    dry: bool = False,
    mode: str = 'entry',
    position_ctx: dict | None = None,
) -> dict:
    """
    Fuehre einen Deep Dive aus.
    Returns: {status: 'ok'|'skipped'|'error', verdict: str, confidence: int,
              usage: dict, warnings: list, error: str | None}
    """
    ticker = ticker.upper()
    existing = load_verdicts().get(ticker)
    if existing and not force:
        # < 14 Tage alt?
        try:
            ts = existing.get('timestamp') or existing.get('date')
            if ts:
                last = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - last).days
                if age_days < 14:
                    print(f"[{ticker}] Verdict noch frisch ({age_days}d) — skip (--force zum erzwingen)")
                    return {
                        'status': 'skipped',
                        'reason': f'fresh_{age_days}d',
                        'verdict': existing.get('verdict'),
                        'confidence': existing.get('confidence'),
                    }
        except Exception:
            pass

    facts = collect_facts(ticker)
    if not facts['price'].get('facts_ok'):
        print(f"[{ticker}] ABBRUCH: {facts['price'].get('error')}")
        return {'status': 'error', 'error': facts['price'].get('error'), 'verdict': None}

    prompt = build_prompt(facts, mode=mode, position_ctx=position_ctx)
    if dry:
        print(prompt)
        return {'status': 'ok', 'verdict': None, 'dry': True}

    model = os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-4-5')
    max_tokens = int(os.environ.get('AUTO_DD_MAX_TOKENS', '2500'))

    print(f"[{ticker}] Claude API call (mode={mode}, model={model})...")
    try:
        response, usage = call_claude(prompt, model=model, max_tokens=max_tokens)
    except Exception as e:
        print(f"[{ticker}] API-Fehler: {e}")
        return {'status': 'error', 'error': f'api: {e}', 'verdict': None}

    try:
        verdict = parse_verdict(response)
    except Exception as e:
        print(f"[{ticker}] Parse-Fehler: {e}\nRaw:\n{response[:500]}")
        return {'status': 'error', 'error': f'parse: {e}', 'verdict': None, 'usage': usage}

    warnings = check_hallucinations(facts, verdict)
    if warnings:
        print(f"[{ticker}] ⚠️ Halluzinations-Warnungen ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")

    save_verdict(ticker, verdict, facts, warnings, model)

    final = verdict.get('verdict')
    if warnings and verdict.get('verdict') == 'KAUFEN':
        final = 'WARTEN (downgraded)'
    ev_eur = verdict.get('ev_eur')
    skew = verdict.get('payoff_skew')
    pain = verdict.get('pain_trade_flag')
    ev_str = f"EV={ev_eur:+.0f}€" if isinstance(ev_eur, (int, float)) else "EV=?"
    skew_str = f"skew={skew:.1f}" if isinstance(skew, (int, float)) else ""
    pain_str = "🎯pain" if pain else ""
    print(f"[{ticker}] ✅ {final}  conf={verdict.get('confidence')}  {ev_str} {skew_str} {pain_str}  "
          f"reasoning={verdict.get('reasoning','')[:100]}")
    return {
        'status': 'ok',
        'verdict': final,
        'raw_verdict': verdict.get('verdict'),
        'confidence': verdict.get('confidence'),
        'reasoning': verdict.get('reasoning'),
        'key_risks': verdict.get('key_risks', []),
        'warnings': warnings,
        'usage': usage,
        'mode': mode,
        'ev_eur': verdict.get('ev_eur'),
        'ev_pct': verdict.get('ev_pct'),
        'payoff_skew': verdict.get('payoff_skew'),
        'pain_trade_flag': verdict.get('pain_trade_flag'),
        'catalyst_date': verdict.get('catalyst_date'),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ticker')
    ap.add_argument('--force', action='store_true', help='Auch wenn Verdict < 14 Tage alt')
    ap.add_argument('--dry', action='store_true', help='Nur Prompt ausgeben, keine API')
    ap.add_argument('--mode', choices=['entry', 'hold'], default='entry', help='Entry- oder Hold-Check')
    args = ap.parse_args()
    result = run(args.ticker, force=args.force, dry=args.dry, mode=args.mode)
    sys.exit(0 if result.get('status') in ('ok', 'skipped') else 2)


if __name__ == '__main__':
    main()
