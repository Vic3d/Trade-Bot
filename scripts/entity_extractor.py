#!/usr/bin/env python3
"""
entity_extractor.py — Claude Haiku Entity Extraction für Overnight-Research
Extrahiert Akteure, Event-Typ, betroffene Strategien und Impact-Richtung aus Headlines.
"""
import anthropic
import json

STRATEGY_CONTEXT = (
    "S1=Iran/Öl/Hormuz, S2=Rüstung/NATO, S3=KI/Tech, S4=Silber/Gold, "
    "S5=Kupfer, S8=Tanker, S9=Kuba, S10=Airlines, S11=Silberminen"
)

FALLBACK_RESULT = {
    "actors": [],
    "event_type": "other",
    "strategies_affected": [],
    "impact_direction": "neutral",
    "confidence": 0.3,
    "why": "parse error"
}


def extract_entities(headline: str) -> dict:
    """
    Ruft Claude Haiku auf um Entities aus einer Headline zu extrahieren.
    Gibt immer ein valides Dict zurück (Fallback bei Fehler).
    """
    try:
        client = anthropic.Anthropic()
        prompt = (
            f'Headline: "{headline}"\n'
            f'Strategies: {STRATEGY_CONTEXT}\n'
            f'Respond ONLY with valid JSON: {{"actors": [...], '
            f'"event_type": "airstrike|statement|sanction|deal|data|other", '
            f'"strategies_affected": [...], '
            f'"impact_direction": "bullish_oil|bearish_oil|bullish_defense|bullish_tech|bearish_airlines|geopolitical_watchlist|neutral", '
            f'"confidence": 0.0-1.0, '
            f'"why": "one sentence"}}'
        )
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        # Validate required fields
        for key in ["actors", "event_type", "strategies_affected", "impact_direction", "confidence", "why"]:
            if key not in result:
                result[key] = FALLBACK_RESULT[key]
        return result
    except Exception as e:
        fb = FALLBACK_RESULT.copy()
        fb["why"] = f"extraction failed: {str(e)[:80]}"
        return fb


if __name__ == "__main__":
    test_headlines = [
        "Iran launches missile strike on US base in Iraq",
        "Fed signals rate cut in September meeting",
        "Rheinmetall wins €2bn NATO contract for artillery shells",
        "Oil tanker seized in Strait of Hormuz by IRGC forces",
    ]
    print("Entity Extraction Test (Haiku):")
    for h in test_headlines:
        print(f"\n  Headline: {h}")
        result = extract_entities(h)
        print(f"  → {json.dumps(result, ensure_ascii=False)}")
