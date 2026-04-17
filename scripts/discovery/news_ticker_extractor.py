#!/usr/bin/env python3
"""
News Ticker Extractor — Phase 7.15 Discovery Source 1
=======================================================
Scannt news_events der letzten 24h und extrahiert Tickers die noch nicht
in UNIVERSE/strategies bekannt sind. Nutzt Claude Sonnet um aus Headlines
Company-Names zu extrahieren und Ticker-Symbole zuzuordnen.

Strategie:
  1. news_events der letzten 24h, relevance_score >= 0.4
  2. Filter: headline erwaehnt einen bekannten Ticker NICHT
             ODER tickers-Feld ist leer
  3. Claude-Batch-Call: extrahiere Company-Names und deren Ticker
  4. Neue Tickers (nicht in UNIVERSE/strategies) -> candidate_tickers.json

Budget:
  - Max 30 Headlines pro Run in einem Batch-Call (spart Kosten)
  - Target: ~$0.10-0.30/Tag (Sonnet)

CLI:
  python3 scripts/discovery/news_ticker_extractor.py
  python3 scripts/discovery/news_ticker_extractor.py --dry
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'discovery'))

from candidates import add_candidate, get_known_tickers, is_new_ticker

MAX_HEADLINES_PER_RUN = 30
MIN_RELEVANCE = 0.4


def fetch_candidate_headlines() -> list[dict]:
    """Headlines der letzten 24h mit hoher Relevance."""
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, headline, source, sector, tickers, sentiment_score, relevance_score, published_at
        FROM news_events
        WHERE published_at >= datetime('now', '-24 hours')
          AND relevance_score >= ?
        ORDER BY relevance_score DESC, published_at DESC
        LIMIT 100
    """, (MIN_RELEVANCE,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def filter_headlines_needing_extraction(headlines: list[dict], known: set[str]) -> list[dict]:
    """Headlines wo tickers leer sind ODER kein bekannter Ticker drinsteht."""
    out = []
    for h in headlines:
        existing_raw = h.get('tickers') or ''
        existing = []
        try:
            existing = json.loads(existing_raw) if existing_raw else []
        except Exception:
            existing = []

        # Wenn bereits bekannte Tickers drin -> skip
        if existing and any(t.upper() in known for t in existing):
            continue
        out.append(h)
        if len(out) >= MAX_HEADLINES_PER_RUN:
            break
    return out


def build_extraction_prompt(headlines: list[dict]) -> str:
    """Batch-Prompt fuer alle Headlines."""
    lines = []
    for i, h in enumerate(headlines, 1):
        lines.append(f"{i}. [{h.get('source','?')}] {h.get('headline','')}")

    blob = '\n'.join(lines)

    return f"""Du bist ein Ticker-Extraktions-Assistent fuer einen Trading-Bot.

Extrahiere aus den folgenden Headlines die boersengelisteten Unternehmen und
ihre Ticker-Symbole. Nur klar erkennbare Unternehmen, keine Spekulation.

WICHTIG:
- Nur Ticker wenn Unternehmen **eindeutig** erwaehnt wird
- Verwende offizielle Ticker (z.B. NVDA, RHM.DE, BA.L, NOVO-B.CO)
- Bei ADRs: den US-Ticker (z.B. NVO statt NOVO-B.CO bei US-Listing Erwaehnung)
- Skip wenn nur Branche/Makro diskutiert wird (z.B. "Tech-Sektor")
- Skip Rohstoffe/Indizes (Brent, S&P, VIX)
- Skip wenn Headline zu vage ist

Headlines:
{blob}

OUTPUT (strenges JSON, kein Markdown):
{{
  "extractions": [
    {{
      "headline_index": <int, 1-basiert>,
      "ticker": "<SYMBOL>",
      "company": "<offizieller Firmenname>",
      "sentiment": "bullish" | "bearish" | "neutral",
      "confidence": <int 0-100>
    }}
  ]
}}

Nur Extractions mit confidence >= 60 einschliessen. Lieber leer lassen als raten."""


def call_claude(prompt: str) -> dict:
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise RuntimeError('ANTHROPIC_API_KEY nicht gesetzt')
    try:
        import anthropic
    except ImportError:
        raise RuntimeError('anthropic package nicht installiert')

    model = os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-4-5')
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = resp.content[0].text if resp.content else ''
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise ValueError(f'Kein JSON im Claude-Output: {text[:200]}')
    usage = {
        'input_tokens': getattr(resp.usage, 'input_tokens', 0) if resp.usage else 0,
        'output_tokens': getattr(resp.usage, 'output_tokens', 0) if resp.usage else 0,
    }
    # Sonnet: $3/MTok input, $15/MTok output
    usage['cost_usd_est'] = (usage['input_tokens'] * 3 + usage['output_tokens'] * 15) / 1_000_000
    return {'data': json.loads(m.group(0)), 'usage': usage}


def run(dry: bool = False) -> dict:
    known = get_known_tickers()
    print(f"[news-extractor] {len(known)} bekannte Tickers in UNIVERSE+strategies")

    headlines = fetch_candidate_headlines()
    print(f"[news-extractor] {len(headlines)} relevante Headlines letzte 24h")

    to_process = filter_headlines_needing_extraction(headlines, known)
    print(f"[news-extractor] {len(to_process)} Headlines brauchen Claude-Extraktion")

    if not to_process:
        return {'status': 'ok', 'processed': 0, 'new_candidates': 0, 'cost_usd': 0.0}

    prompt = build_extraction_prompt(to_process)
    if dry:
        print(prompt)
        return {'status': 'dry', 'processed': len(to_process)}

    try:
        resp = call_claude(prompt)
    except Exception as e:
        print(f"[news-extractor] Claude-Fehler: {e}")
        return {'status': 'error', 'error': str(e)}

    extractions = resp['data'].get('extractions', [])
    print(f"[news-extractor] Claude extrahierte {len(extractions)} Ticker-Mentions")

    new_count = 0
    for ex in extractions:
        ticker = str(ex.get('ticker', '')).strip().upper()
        conf = int(ex.get('confidence', 0) or 0)
        company = ex.get('company', '')
        sentiment = ex.get('sentiment', 'neutral')
        idx = ex.get('headline_index')
        try:
            headline = to_process[int(idx) - 1]['headline']
        except Exception:
            headline = ''

        if conf < 60 or not ticker:
            continue
        if not is_new_ticker(ticker):
            continue

        # Score basierend auf Sentiment
        score_map = {'bullish': 0.8, 'bearish': 0.3, 'neutral': 0.5}
        score = score_map.get(sentiment, 0.5) * (conf / 100.0)

        detail = f"{company}: {headline[:120]} [{sentiment}]"
        added = add_candidate(ticker, 'news', detail, score=score)
        if added:
            new_count += 1
            print(f"  + {ticker} ({company}) score={score:.2f} — {headline[:80]}")

    print(f"[news-extractor] {new_count} neue Kandidaten, ${resp['usage']['cost_usd_est']:.3f}")
    return {
        'status': 'ok',
        'processed': len(to_process),
        'extractions_total': len(extractions),
        'new_candidates': new_count,
        'cost_usd': round(resp['usage']['cost_usd_est'], 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()
    result = run(dry=args.dry)
    sys.exit(0 if result.get('status') in ('ok', 'dry') else 2)


if __name__ == '__main__':
    main()
