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
    "model": "claude-opus-4-5",
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
  ANTHROPIC_MODEL    (optional, default claude-opus-4-5)
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


def build_prompt(facts: dict) -> str:
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

    prompt = f"""Du bist Albert, der AI-CEO von TradeMind. Du machst einen Deep Dive fuer
den Paper-Trading-Bot im Auftrag von Victor.

Deine Aufgabe: **Trading-Verdict** fuer {facts['ticker']} nach dem Deep-Dive-Protokoll.

KRITISCH: Du gibst NUR ein Verdict basierend auf den Fakten unten. Keine Spekulation ueber
Daten die du nicht hast. Wenn wichtige Infos fehlen (z.B. keine News, kein KGV), dann
reflektiere das im Verdict — "WARTEN wegen Daten-Luecke" ist ein legitimes Ergebnis.

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

### DEEP DIVE PROTOKOLL (Kurzform)
1. **Bewertung** — KGV/EV-EBITDA sektorgerecht (du kennst Fundamentals nicht aus DB)
   → Falls keine Fundamentals: kennzeichne als DATEN-LUECKE
2. **Technische Lage** — oben bereits in Fakten
3. **Katalysator** — gibt es einen frischen, spezifischen Trigger? (News-Block pruefen)
4. **Leiche im Keller** — Risiken, Downgrades, Polit-Risiko, Schulden
5. **Gegenthese** — warum koennte die Aktie NICHT steigen?
6. **Timing** — ist das ein Knife-Catch (unter MA50 + 3M < -10%)?

### KILLER-REGELN (hart)
- Preis < EMA50 UND 3M-Trend < -10%  → NICHT_KAUFEN (Falling Knife)
- 40%+ unter 52W-Hoch  → WARTEN oder NICHT_KAUFEN (Vertrauensbruch im Chart)
- RSI > 75  → WARTEN (ueberkauft)
- RSI < 25 UND unter MA200  → WARTEN (noch nicht gedreht)
- Keine News & 52W-Hoch nahe & RSI hoch  → WARTEN (Momentum-Chase)

### OUTPUT-FORMAT (streng)
Gib AUSSCHLIESSLICH valides JSON zurueck, KEIN Markdown, KEIN Fliesstext drumherum.

{{
  "verdict": "KAUFEN" | "WARTEN" | "NICHT_KAUFEN",
  "confidence": <int 0-100>,
  "reasoning": "<2-3 Saetze warum>",
  "key_risks": ["<risiko1>", "<risiko2>"],
  "katalysator": "<spezifischer Trigger oder 'keiner erkennbar'>",
  "target_hold_days": <int, typisch 7-30>,
  "facts_claims": {{
    "above_ma50": <true|false|null>,
    "above_ma200": <true|false|null>,
    "trend_3m_positive": <true|false|null>,
    "rsi_overbought": <true|false|null>
  }}
}}

Die "facts_claims" verwenden wir zum Anti-Halluzinations-Check — trag nur rein was
DU aus den Fakten oben schliesst, nicht was du glaubst wahr sein sollte.
"""
    return prompt


# ────────────────────────────────────────────────────────────────────────────
# Claude Call
# ────────────────────────────────────────────────────────────────────────────


def call_claude(prompt: str, model: str | None = None, max_tokens: int = 2500) -> str:
    """Ruft Anthropic API auf. Raises bei Fehler."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise RuntimeError('ANTHROPIC_API_KEY nicht gesetzt')
    model = model or os.environ.get('ANTHROPIC_MODEL', 'claude-opus-4-5')

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
    return content


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
        'target_hold_days': verdict.get('target_hold_days'),
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


def run(ticker: str, *, force: bool = False, dry: bool = False) -> int:
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
                    return 0
        except Exception:
            pass

    facts = collect_facts(ticker)
    if not facts['price'].get('facts_ok'):
        print(f"[{ticker}] ABBRUCH: {facts['price'].get('error')}")
        return 2

    prompt = build_prompt(facts)
    if dry:
        print(prompt)
        return 0

    model = os.environ.get('ANTHROPIC_MODEL', 'claude-opus-4-5')
    max_tokens = int(os.environ.get('AUTO_DD_MAX_TOKENS', '2500'))

    print(f"[{ticker}] Claude API call (model={model})...")
    try:
        response = call_claude(prompt, model=model, max_tokens=max_tokens)
    except Exception as e:
        print(f"[{ticker}] API-Fehler: {e}")
        return 3

    try:
        verdict = parse_verdict(response)
    except Exception as e:
        print(f"[{ticker}] Parse-Fehler: {e}\nRaw:\n{response[:500]}")
        return 4

    warnings = check_hallucinations(facts, verdict)
    if warnings:
        print(f"[{ticker}] ⚠️ Halluzinations-Warnungen ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")

    save_verdict(ticker, verdict, facts, warnings, model)

    final = verdict.get('verdict')
    if warnings and verdict.get('verdict') == 'KAUFEN':
        final = 'WARTEN (downgraded)'
    print(f"[{ticker}] ✅ {final}  conf={verdict.get('confidence')}  "
          f"reasoning={verdict.get('reasoning','')[:120]}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ticker')
    ap.add_argument('--force', action='store_true', help='Auch wenn Verdict < 14 Tage alt')
    ap.add_argument('--dry', action='store_true', help='Nur Prompt ausgeben, keine API')
    args = ap.parse_args()
    sys.exit(run(args.ticker, force=args.force, dry=args.dry))


if __name__ == '__main__':
    main()
