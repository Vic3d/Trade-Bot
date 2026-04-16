#!/usr/bin/env python3
"""
strategy_monitor.py — Strategie-Aktualitätsprüfung & Neue-Themen-Detektor

Läuft 1x täglich (z.B. 08:00 + 20:00).
Prüft jede Strategie gegen: Preis-Momentum + News-Sentiment
Erkennt neue Makro-Themen die eine neue Strategie rechtfertigen könnten.

Output:
  - Statusbericht (🟢/🟡/🔴 je Strategie)
  - strategy-changelog.md Update wenn Status ändert
  - Neue Strategie-Kandidaten mit Begründung

Strategie-Definitionen kommen aus: data/strategies.json (Single Source of Truth)
"""

import sys, json, re
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))


sys.path.insert(0, str(Path(__file__).parent))

DATA_DIR = WS / 'data'
MEM_DIR  = WS / 'memory'
STRATEGIES_PATH = DATA_DIR / "strategies.json"


# ──────────────────────────────────────────────────────────────
# LADEN AUS SINGLE SOURCE OF TRUTH
# ──────────────────────────────────────────────────────────────

def load_strategies():
    """
    Lädt Strategie-Definitionen aus data/strategies.json.
    Returns:
        strategies: dict (nur PS1-PS5 = paper trading strategies für Monitor)
        emerging_themes: dict
        all_strategies: dict (S1-S7 + PS1-PS5)
    """
    if not STRATEGIES_PATH.exists():
        raise FileNotFoundError(f"strategies.json nicht gefunden: {STRATEGIES_PATH}")

    data = json.loads(STRATEGIES_PATH.read_text(encoding="utf-8"))

    # Emerging themes sind ein spezieller Top-Level-Key
    emerging_themes = data.pop("emerging_themes", {})

    # Paper strategies (PS*) für den Monitor
    paper_strategies = {k: v for k, v in data.items() if k.startswith("PS")}

    # All strategies (real + paper)
    all_strategies = data

    return paper_strategies, emerging_themes, all_strategies


def save_health_update(strategy_id, new_health):
    """
    Schreibt den neuen health-Status zurück in strategies.json.
    health: 'green' | 'yellow' | 'red' | 'green_hot'
    """
    if not STRATEGIES_PATH.exists():
        return
    data = json.loads(STRATEGIES_PATH.read_text(encoding="utf-8"))
    if strategy_id in data:
        data[strategy_id]["health"] = new_health
        STRATEGIES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ──────────────────────────────────────────────────────────────
# PREISMOMENTEM-CHECK
# ──────────────────────────────────────────────────────────────

def get_price_momentum(tickers, days=14):
    """
    Berechnet Preis-Momentum über `days` Tage für eine Ticker-Liste.
    Returns: dict {ticker: pct_change} + avg_momentum
    """
    try:
        from price_db import get_closes
        results = {}
        for t in tickers:
            closes = get_closes(t, days=days + 5)
            if closes and len(closes) >= 5:
                oldest = closes[0]
                newest = closes[-1]
                if oldest > 0:
                    pct = ((newest / oldest) - 1) * 100
                    results[t] = round(pct, 1)
        if results:
            avg = sum(results.values()) / len(results)
            return results, round(avg, 1)
    except Exception as e:
        pass
    return {}, 0.0


# ──────────────────────────────────────────────────────────────
# NEWS-SENTIMENT-CHECK
# ──────────────────────────────────────────────────────────────

def fetch_recent_news(n=30):
    """Holt aktuelle News aus allen Quellen."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        exec(open(str(Path(__file__).parent / 'news_fetcher.py')).read(), globals())
        articles = []
        # Bloomberg
        for cat in ['markets', 'energy', 'politics']:
            articles += bloomberg(categories=[cat], n=8)
        # Google News
        for query in ['oil iran conflict', 'defense spending nato', 'gold silver', 'fertilizer']:
            articles += google_news(query=query, n=5)
        return articles[:n]
    except Exception as e:
        return []


def score_news_sentiment(articles, keywords_bullish, keywords_bearish):
    """
    Zählt bullishe vs. bearishe Keyword-Treffer in den Artikeln.
    Returns: score -100 bis +100, hit_list
    """
    bull_hits = []
    bear_hits = []

    for art in articles:
        text = (art.get('title', '') + ' ' + art.get('summary', '')).lower()
        for kw in keywords_bullish:
            if kw.lower() in text:
                bull_hits.append({'kw': kw, 'title': art.get('title', '')[:60]})
        for kw in keywords_bearish:
            if kw.lower() in text:
                bear_hits.append({'kw': kw, 'title': art.get('title', '')[:60]})

    net = len(bull_hits) - len(bear_hits)
    # Normalisiere auf -100 bis +100 (max 10 hits = ±100)
    score = max(-100, min(100, net * 20))
    return score, bull_hits, bear_hits


def detect_emerging_themes(articles, emerging_theme_detectors):
    """
    Prüft ob neue Makro-Themen in den News auftauchen
    die noch KEINE Strategie haben.
    Returns: list of {theme, count, articles, candidates, thesis}
    """
    detections = []
    for theme_key, detector in emerging_theme_detectors.items():
        if not isinstance(detector, dict) or 'keywords' not in detector:
            continue  # Skip malformed entries (e.g. genesis/performance meta-fields)
        hits = []
        for art in articles:
            text = (art.get('title', '') + ' ' + art.get('summary', '')).lower()
            for kw in detector['keywords']:
                if kw.lower() in text:
                    hits.append(art.get('title', '')[:70])
                    break
        if len(hits) >= 2:  # Mindestens 2 Artikel zum gleichen Thema
            detections.append({
                'theme': detector.get('name', theme_key),
                'count': len(hits),
                'articles': hits[:3],
                'candidates': detector['candidates'],
                'sector': detector['sector'],
                'thesis': detector['thesis_template'],
            })
    return detections


# ──────────────────────────────────────────────────────────────
# THESIS-STATUS BERECHNEN
# ──────────────────────────────────────────────────────────────

def compute_thesis_status(momentum_avg, news_score):
    """
    Kombiniert Preis-Momentum und News-Sentiment zu einem Thesis-Status.

    Momentum: Durchschnittliche Preis-Bewegung der Strategie-Tickers (%)
    News-Score: -100 (sehr bearish) bis +100 (sehr bullish)

    Returns: status (STARK/NEUTRAL/GESCHWÄCHT), score (0-100), reasons
    """
    reasons = []

    # Gewichtung: 60% Preis-Momentum, 40% News
    momentum_score = 0
    if momentum_avg > 10:
        momentum_score = 80
        reasons.append(f"Preise stark +{momentum_avg:.1f}% (14T)")
    elif momentum_avg > 3:
        momentum_score = 60
        reasons.append(f"Preise positiv +{momentum_avg:.1f}% (14T)")
    elif momentum_avg > -3:
        momentum_score = 40
        reasons.append(f"Preise seitwärts {momentum_avg:+.1f}% (14T)")
    elif momentum_avg > -10:
        momentum_score = 20
        reasons.append(f"Preise schwach {momentum_avg:+.1f}% (14T)")
    else:
        momentum_score = 0
        reasons.append(f"Preise sehr schwach {momentum_avg:+.1f}% (14T)")

    # News Score: -100 bis +100 → 0 bis 80
    news_component = (news_score + 100) / 200 * 80
    if news_score > 20:
        reasons.append(f"News bullish (Score +{news_score})")
    elif news_score < -20:
        reasons.append(f"News bearish (Score {news_score})")
    else:
        reasons.append(f"News neutral (Score {news_score:+d})")

    combined = momentum_score * 0.6 + news_component * 0.4

    if combined >= 55:
        return "STARK", round(combined), reasons
    elif combined >= 35:
        return "NEUTRAL", round(combined), reasons
    else:
        return "GESCHWÄCHT", round(combined), reasons


def thesis_status_to_health(status):
    """Mappe Monitor-Status auf health-Wert in strategies.json."""
    return {
        "STARK": "green",
        "NEUTRAL": "yellow",
        "GESCHWÄCHT": "red",
    }.get(status, "yellow")


# ──────────────────────────────────────────────────────────────
# STRATEGIE-CHANGELOG UPDATEN
# ──────────────────────────────────────────────────────────────

def load_current_statuses(strategy_ids):
    """Liest aktuellen Status jeder Strategie aus strategy-changelog.md."""
    changelog = MEM_DIR / "strategy-changelog.md"
    if not changelog.exists():
        return {}

    content = changelog.read_text(encoding="utf-8")
    statuses = {}
    for ps_id in strategy_ids:
        pattern = rf'{ps_id}.*?(STARK|NEUTRAL|GESCHWÄCHT)'
        matches = re.findall(pattern, content)
        if matches:
            statuses[ps_id] = matches[-1]
    return statuses


def update_changelog(changes):
    """Schreibt Statusänderungen in strategy-changelog.md."""
    if not changes:
        return

    changelog = MEM_DIR / "strategy-changelog.md"
    now = datetime.now(_BERLIN).strftime("%Y-%m-%d %H:%M")

    new_entries = f"\n\n## {now} — Automatischer Status-Check\n\n"
    for ch in changes:
        emoji_map = {"STARK": "🟢", "NEUTRAL": "🟡", "GESCHWÄCHT": "🔴"}
        old_e = emoji_map.get(ch['old_status'], '❓')
        new_e = emoji_map.get(ch['new_status'], '❓')
        new_entries += f"### {ch['ps_id']} ({ch['name']})\n"
        new_entries += f"**{old_e} {ch['old_status']} → {new_e} {ch['new_status']}** (Score: {ch['score']})\n"
        new_entries += f"**Gründe:** {' | '.join(ch['reasons'])}\n\n"

    if changelog.exists():
        existing = changelog.read_text(encoding="utf-8")
        changelog.write_text(existing + new_entries, encoding="utf-8")
    else:
        changelog.write_text(f"# Strategy Changelog\n{new_entries}", encoding="utf-8")


# ──────────────────────────────────────────────────────────────
# MAIN REPORT
# ──────────────────────────────────────────────────────────────

def run_monitor():
    now = datetime.now(_BERLIN).strftime("%Y-%m-%d %H:%M")
    lines = []

    def log(msg=""):
        lines.append(msg)
        print(msg)

    log(f"=== STRATEGY MONITOR — {now} ===")
    log()

    # Load strategies from JSON (Single Source of Truth)
    try:
        paper_strategies, emerging_theme_detectors, all_strategies = load_strategies()
        log(f"📂 Strategien geladen aus {STRATEGIES_PATH}")
        log(f"   Paper: {list(paper_strategies.keys())}")
        log()
    except Exception as e:
        log(f"❌ Fehler beim Laden von strategies.json: {e}")
        return {}

    # 1. News holen
    log("📰 Lade aktuelle News...")
    articles = fetch_recent_news(n=40)
    log(f"   {len(articles)} Artikel geladen")
    log()

    # 2. Aktuelle Statuses laden
    old_statuses = load_current_statuses(list(paper_strategies.keys()))

    # 3. Jede Paper-Strategie prüfen
    emoji_map = {"STARK": "🟢", "NEUTRAL": "🟡", "GESCHWÄCHT": "🔴"}
    changes = []
    results = {}

    log("=" * 60)
    log("📊 STRATEGIE-CHECK")
    log("=" * 60)

    for ps_id, strat in paper_strategies.items():
        log()
        log(f"── {ps_id}: {strat['name']} ──")

        # Preis-Momentum
        momentum_map, momentum_avg = get_price_momentum(strat.get('tickers', []), days=14)
        momentum_str = " | ".join([f"{t}: {v:+.1f}%" for t, v in momentum_map.items()])
        if not momentum_str:
            momentum_str = "keine Daten"
            momentum_avg = 0
        log(f"   Momentum (14T): {momentum_str} → Ø {momentum_avg:+.1f}%")

        # News-Sentiment
        news_score, bull_hits, bear_hits = score_news_sentiment(
            articles, strat.get('keywords_bullish', []), strat.get('keywords_bearish', [])
        )
        log(f"   News: +{len(bull_hits)} bullish / -{len(bear_hits)} bearish → Score {news_score:+d}")
        for h in bull_hits[:2]:
            log(f"     ✅ [{h['kw']}] {h['title']}")
        for h in bear_hits[:2]:
            log(f"     ❌ [{h['kw']}] {h['title']}")

        # Status berechnen
        new_status, score, reasons = compute_thesis_status(momentum_avg, news_score)
        old_status = old_statuses.get(ps_id, "STARK")
        new_emoji = emoji_map[new_status]
        old_emoji = emoji_map.get(old_status, "🟢")

        log(f"   Status: {old_emoji} {old_status} → {new_emoji} {new_status} (Score {score}/100)")

        results[ps_id] = {
            'name': strat['name'],
            'status': new_status,
            'score': score,
            'momentum_avg': momentum_avg,
            'news_score': news_score,
            'reasons': reasons,
        }

        # health in strategies.json aktualisieren
        new_health = thesis_status_to_health(new_status)
        if strat.get('health') != new_health:
            save_health_update(ps_id, new_health)
            log(f"   💾 health aktualisiert: {strat.get('health')} → {new_health}")

        # Statuswechsel tracken
        if old_status != new_status:
            changes.append({
                'ps_id': ps_id,
                'name': strat['name'],
                'old_status': old_status,
                'new_status': new_status,
                'score': score,
                'reasons': reasons,
            })

    # 4. Neue Makro-Themen erkennen
    log()
    log("=" * 60)
    log("🔭 NEUE MAKRO-THEMEN (potentielle neue Strategien)")
    log("=" * 60)

    emerging = detect_emerging_themes(articles, emerging_theme_detectors)
    if emerging:
        for em in emerging:
            log()
            log(f"  💡 THEMA: {em['theme']} ({em['count']} Artikel)")
            log(f"     These: {em['thesis']}")
            log(f"     Kandidaten: {', '.join(em['candidates'])}")
            log(f"     Artikel:")
            for a in em['articles']:
                log(f"       - {a}")
    else:
        log("   Keine neuen Themen mit ausreichend Signalstärke (min. 2 Artikel)")

    # 5. Änderungen in Changelog schreiben
    if changes:
        log()
        log(f"⚠️  {len(changes)} STATUS-ÄNDERUNGEN → strategy-changelog.md update")
        update_changelog(changes)

    # 6. Zusammenfassung
    log()
    log("=" * 60)
    log("📋 ZUSAMMENFASSUNG")
    log("=" * 60)
    for ps_id, r in results.items():
        emoji = emoji_map[r['status']]
        log(f"  {emoji} {ps_id} {r['name']:<25} Score {r['score']:>3}/100 | Momentum {r['momentum_avg']:+.1f}% | News {r['news_score']:+d}")

    if changes:
        log()
        log("🚨 STATUSWECHSEL:")
        for ch in changes:
            old_e = emoji_map.get(ch['old_status'], '❓')
            new_e = emoji_map[ch['new_status']]
            log(f"  {old_e}→{new_e} {ch['ps_id']} {ch['name']}: {' | '.join(ch['reasons'])}")

    if emerging:
        log()
        log("💡 NEUE STRATEGIE-KANDIDATEN:")
        for em in emerging:
            log(f"  → {em['theme']}: {em['thesis']} ({', '.join(em['candidates'])})")

    # Ergebnis speichern
    result = {
        'timestamp': datetime.now(_BERLIN).isoformat(),
        'strategies': results,
        'changes': changes,
        'emerging_themes': emerging,
        'articles_analyzed': len(articles),
    }
    out_path = DATA_DIR / "strategy_monitor_last_run.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    log()
    log(f"💾 Gespeichert: {out_path}")

    return result


if __name__ == "__main__":
    run_monitor()
