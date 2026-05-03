#!/usr/bin/env python3
"""
news_inference_engine.py — Phase 44af: Deep-Cascade-Analyse fuer HIGH-Events.

User-Direktive (Victor 03.05): 'Zwischen den Zeilen lesen — nicht nur die
Nachricht selbst, sondern was sich daraus ableiten laesst.'

News-Reactor macht das schon pro offene Position. ABER: bei wirklich grossen
Macro-Events (HIGH-severity, z.B. Iran-Eskalation, Fed-Surprise) braucht
es eine TIEFERE Analyse die nicht nur unsere Positions checkt, sondern:

  - Welche NEUEN Setups entstehen jetzt? (Hunter-Pre-Cycle)
  - Welche Sektoren rotiert der Markt jetzt?
  - Welche Tickers in unserem UNIVERSE waeren jetzt Kandidaten?
  - Welche bestehenden Strategien werden gestaerkt/geschwaecht?
  - Welche Cross-Asset-Korrelationen werden brechen?

Output:
  memory/ceo-thesis-pipeline/YYYY-MM-DD-inference.md  (anhang an pipeline)
  data/news_inference_log.jsonl
  Discord-Push HIGH wenn neue actionable Theses identifiziert
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'news_inference_log.jsonl'
PIPELINE_DIR = WS / 'memory' / 'ceo-thesis-pipeline'


SYSTEM = """Du bist Albert im DEEP-INFERENCE-MODE. Ein wichtiges Macro-Event
ist passiert. Lese ZWISCHEN DEN ZEILEN.

Aufgabe: nimm die Top-3 Headlines + den verbindlichen Truth-Header oben
(open positions, active strategies, current macro state) und analysiere:

1. CASCADE-MAP (3-4 Ordnungen tief):
   1st-order: direkter Effekt
   2nd-order: Substitution, Supply-Chain, Konkurrenz
   3rd-order: Sentiment, Rotation, Cross-Asset
   4th-order: Wenn-dann-Implications fuer naechste 1-4 Wochen

2. AKTIONS-RELEVANZ:
   a) Bestehende Positions: muss was ueberdacht werden?
   b) NEUE Setups: welche Tickers werden jetzt Kandidaten?
      (nutze deine Active-Strategy-Liste — welche feuert gerade?)
   c) Strategy-Pivot: welche Strategie wird gestaerkt/geschwaecht?
   d) Cross-Asset: was passiert mit Korrelationen (Gold-USD, Brent-Tanker, VIX-Tech)?

3. KONKRETE ACTION-ITEMS (max 5):
   Pro Item: was, warum, urgency (now/today/this_week), wer ausfuehrt

REGEL: Cascade muss konkret und plausibel sein. Keine Spekulation
('vermutlich' / 'koennte' verboten — siehe banned phrases).
Nur Tickers/Strategien die im Truth-Header oder Active-Strategy-Liste stehen.

Antwort als strukturiertes Markdown."""


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _gather_recent_high_news(hours: int = 6) -> list[dict]:
    """Holt Headlines die vom macro_event_detector als HIGH gemarkt sind."""
    if not DB.exists(): return []
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        # Macro-Events letzte N hours
        rows = c.execute(
            "SELECT m.event_type, m.severity, m.detected_at, "
            "       n.headline, n.source FROM macro_events m "
            "LEFT JOIN news_events n ON m.news_event_id = n.id "
            "WHERE m.detected_at >= datetime('now', '-{}h') "
            "AND m.severity >= 0.85 ORDER BY m.severity DESC, m.detected_at DESC "
            "LIMIT 8".format(hours)
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def run() -> dict:
    high_news = _gather_recent_high_news(hours=6)
    if not high_news:
        return {'ts': _now(), 'note': 'no_high_severity_news', 'analyzed': 0}

    # Prompt mit den Top-Headlines
    headlines_str = '\n'.join(
        f"- [{n.get('severity','?')} {n.get('event_type','?')}] {n.get('headline','')[:140]}"
        for n in high_news[:5]
    )
    prompt = (
        f"HIGH-Severity-News (letzte 6h, sortiert nach Severity):\n{headlines_str}\n\n"
        f"Mache die Deep-Cascade-Analyse + identifiziere konkrete Action-Items.\n"
        f"Beziehe dich auf den Truth-Header oben (Open-Positions, Active-Strategies)."
    )

    text = ''
    try:
        from core.llm_client import call_llm
        text, usage = call_llm(prompt, model_hint='sonnet', max_tokens=2000,
                                system=SYSTEM, audit_context='news_inference')
    except Exception as e:
        text = f'(LLM-fail: {e})'

    today = datetime.now().strftime('%Y-%m-%d')
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    f = PIPELINE_DIR / f'{today}-inference.md'
    existing = f.read_text(encoding='utf-8') if f.exists() else ''
    f.write_text(
        existing + f'\n\n## Deep-Inference @ {datetime.now().strftime("%H:%M")}\n\n'
                    f'**HIGH-News-Cluster:**\n{headlines_str}\n\n{text}\n',
        encoding='utf-8'
    )

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps({'ts': _now(), 'n_high_news': len(high_news),
                              'inference_preview': text[:500]},
                             ensure_ascii=False) + '\n')

    # Discord-Push (HIGH-Whitelist) wenn Action-Items erkennbar
    has_action_items = ('Action-Item' in text or 'action_items' in text.lower()
                        or 'now' in text.lower() or 'today' in text.lower())
    if has_action_items:
        try:
            from discord_dispatcher import send_alert, TIER_HIGH
            preview = text[:1200]
            msg = (f'🧠 **Deep-Cascade-Inference** — {len(high_news)} HIGH-Events analysiert\n'
                   f'_Volle Notiz: {f}_\n\n'
                   f'```\n{preview}\n```')
            send_alert(msg[:1900], tier=TIER_HIGH, category='ceo_action_request',
                        dedupe_key=f'inference_{datetime.now().strftime("%Y%m%d_%H")}')
        except Exception: pass

    return {'ts': _now(), 'analyzed': len(high_news), 'file': str(f)}


def main() -> int:
    r = run()
    print(f'═══ News-Inference @ {r["ts"][:16]} ═══')
    print(f'  Analyzed HIGH-news: {r.get("analyzed",0)}')
    if 'file' in r:
        print(f'  File: {r["file"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
