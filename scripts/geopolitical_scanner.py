#!/usr/bin/env python3
"""
Geopolitical Scanner — Frühwarnsystem für Krisen
Scannt liveuamap-Regionen + Google News RSS auf Krisensignale.
Alertet bei Threshold-Überschreitung direkt per Discord.

Usage:
  python3 geopolitical_scanner.py [--tier all|1|2] [--force]

Output:
  - Stdout: JSON-Summary
  - Discord: Alert wenn alert_tier != NONE
  - Log: memory/newswire-analysis.md (letzten 20 Einträge)
  - Dashboard: memory/scanner-dashboard-data.json (letzten 50 Runs)
"""

import urllib.request
import urllib.parse
import json
import re
import os
import sys
import hashlib
import time
from datetime import datetime, timezone

# ─── Konfiguration ────────────────────────────────────────────────────────────

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE     = os.path.join(WORKSPACE, "memory", "scanner-state.json")
LOG_FILE       = os.path.join(WORKSPACE, "memory", "newswire-analysis.md")
DASHBOARD_FILE = os.path.join(WORKSPACE, "memory", "scanner-dashboard-data.json")

# Regionen — Tier 1: täglich (alle Läufe), Tier 2: bei konkretem Anlass
REGIONS = {
    1: [
        ("iran",            "🇮🇷 Iran/Hormuz",       ["S1", "S8"]),
        ("israelpalestine", "🇮🇱 Israel/Palästina",  ["S1"]),
        ("iraq",            "🇮🇶 Irak/Öl",           ["S1", "S8"]),
        ("caribbean",       "🌊 Karibik/Kuba",        ["S9"]),
        ("venezuela",       "🇻🇪 Venezuela",          ["S9"]),
        ("russia",          "🇷🇺 Russland",           ["S1", "S2"]),
        ("turkey",          "🇹🇷 Türkei",             ["S1"]),
        ("pakistan",        "🇵🇰 Pakistan",           ["S1"]),
        ("libya",           "🇱🇾 Libyen/Öl",          ["S1", "S8"]),
        ("taiwan",          "🇹🇼 Taiwan",             ["S3", "S9"]),
    ],
    2: [
        ("china",           "🇨🇳 China",             ["S3", "S9"]),
        ("koreas",          "🇰🇷 Korea",              ["S3"]),
        ("germany",         "🇩🇪 Deutschland",        ["S2"]),
        ("uk",              "🇬🇧 UK",                 []),
        ("france",          "🇫🇷 Frankreich",         []),
        ("afghanistan",     "🇦🇫 Afghanistan",        ["S1"]),
        ("sahel",           "🌍 Sahel",               []),
        ("myanmar",         "🇲🇲 Myanmar",            []),
        ("caucasus",        "🏔️ Kaukasus",            []),
    ],
}

# Portfolio-Mapping: Region → Strategien + Tickers
PORTFOLIO_MAP = {
    "iran":            {"strategies": ["S1"], "tickers": ["DR0.DE", "EQNR"]},
    "israelpalestine": {"strategies": ["S1"], "tickers": ["DR0.DE", "EQNR"]},
    "iraq":            {"strategies": ["S1"], "tickers": ["DR0.DE", "EQNR"]},
    "libya":           {"strategies": ["S1"], "tickers": ["DR0.DE", "EQNR"]},
    "saudiarabia":     {"strategies": ["S1"], "tickers": ["DR0.DE", "EQNR"]},
    "caribbean":       {"strategies": ["S9"], "tickers": ["S.TO", "CCL", "GLEN.L"]},
    "venezuela":       {"strategies": ["S9"], "tickers": ["S.TO", "CCL"]},
    "russia":          {"strategies": ["S1", "S2"], "tickers": ["RHM.DE", "DR0.DE"]},
    "taiwan":          {"strategies": ["S3"], "tickers": ["NVDA", "MSFT"]},
    "china":           {"strategies": ["S3"], "tickers": ["NVDA", "MSFT", "MP"]},
    "koreas":          {"strategies": ["S3"], "tickers": ["NVDA"]},
}

# Google News RSS — breite Suchterms für Discovery Mode
GNEWS_QUERIES = [
    "oil tanker blocked intercepted 2026",
    "regime change indictment military 2026",
    "pipeline explosion oil supply disruption",
    "blockade sanctions warship naval confrontation",
    "power grid collapse energy crisis",
    "ballistic missile strike airstrike",
    "new sanctions country oil gas",
]

# Crisis Scoring — Keywords nach Schweregrad
CRISIS_KEYWORDS = {
    "CRITICAL": [
        "ballistic missile", "airstrike", "air strike", "nuclear",
        "regime change", "indictment", "power grid collapse",
        "tanker seized", "tanker intercepted", "tanker blocked",
        "oil field attack", "oil field struck", "pipeline explosion",
        "blockade", "warship confrontation", "coup", "invasion",
        "hormuz", "kharg island", "grid collapsed",
    ],
    "HIGH": [
        "drone attack", "explosion", "military buildup", "sanctions",
        "protest", "ceasefire", "escalation", "naval", "emergency",
        "pipeline shutdown", "oil supply", "refinery attack",
        "killed", "troops deployed", "intercepted",
        "regime", "diplomatic", "ultimatum",
    ],
    "MEDIUM": [
        "tensions", "warning", "military exercise", "seized",
        "detained", "arrested", "demonstration", "strike",
    ],
}

SCORE_WEIGHTS   = {"CRITICAL": 10, "HIGH": 4, "MEDIUM": 1}
ALERT_THRESHOLD = 12   # Gesamtscore ab dem Discord-Alert ausgelöst wird
NOTIFY_THRESHOLD = 6   # Log-Eintrag, kein Alert

# Alert-Tier Grenzen
TIER_HIGH   = 50
TIER_MEDIUM = 30
TIER_LOW    = 12

# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def fetch(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""

def score_text(text):
    text_lower = text.lower()
    score = 0
    matched = {"CRITICAL": [], "HIGH": [], "MEDIUM": []}
    for level, keywords in CRISIS_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                score += SCORE_WEIGHTS[level]
                matched[level].append(kw)
    return score, matched

def item_hash(text):
    return hashlib.md5(text.encode()).hexdigest()[:12]

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"seen": {}, "last_run": None}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def compute_alert_tier(total_score):
    if total_score >= TIER_HIGH:
        return "HIGH"
    elif total_score >= TIER_MEDIUM:
        return "MEDIUM"
    elif total_score >= TIER_LOW:
        return "LOW"
    else:
        return "NONE"

def compute_deep_dive_terms(alert_items, regions_scanned):
    """Top-2-3 Keywords/Regionen die den Score getrieben haben."""
    # Sammle Regionen mit Score
    region_scores = {}
    for item in alert_items:
        slug = item.get("source", "")
        if slug and slug != "gnews":
            region_scores[slug] = region_scores.get(slug, 0) + item["score"]
        # Auch Keywords als Terms
        for kw in item.get("keywords", {}).get("CRITICAL", []):
            region_scores[kw] = region_scores.get(kw, 0) + SCORE_WEIGHTS["CRITICAL"]
        for kw in item.get("keywords", {}).get("HIGH", []):
            region_scores[kw] = region_scores.get(kw, 0) + SCORE_WEIGHTS["HIGH"]

    sorted_terms = sorted(region_scores.items(), key=lambda x: x[1], reverse=True)
    return [t[0] for t in sorted_terms[:3]]

def compute_portfolio_impact(alert_items):
    """Berechne affected_strategies und affected_tickers aus alert_items."""
    strategies = set()
    tickers = set()

    for item in alert_items:
        slug = item.get("source", "")
        if slug in PORTFOLIO_MAP:
            for s in PORTFOLIO_MAP[slug]["strategies"]:
                strategies.add(s)
            for t in PORTFOLIO_MAP[slug]["tickers"]:
                tickers.add(t)

    return sorted(strategies), sorted(tickers)

def log_findings(findings, ts):
    """Append findings to newswire-analysis.md (letzte 20 Einträge behalten)"""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    entry = f"\n## {ts} — Geopolitical Scanner\n"
    if not findings:
        entry += "_Keine neuen Krisensignale._\n"
    else:
        for f in findings[:10]:
            entry += f"- **[{f['level']}]** `{f['region']}` — {f['text'][:120]}...\n"
            if f.get("strategies"):
                entry += f"  → Strategien: {', '.join(f['strategies'])}\n"

    existing = ""
    try:
        with open(LOG_FILE) as f:
            existing = f.read()
    except Exception:
        pass

    sections = re.split(r'(?=\n## \d{4}-)', existing)
    trimmed = (entry + "".join(sections[:20]))
    with open(LOG_FILE, "w") as f:
        f.write(trimmed)

def update_dashboard(run_data):
    """Schreibe/update scanner-dashboard-data.json (max 50 Runs)."""
    os.makedirs(os.path.dirname(DASHBOARD_FILE), exist_ok=True)

    dashboard = {"last_updated": "", "runs": []}
    try:
        with open(DASHBOARD_FILE) as f:
            dashboard = json.load(f)
    except Exception:
        pass

    dashboard["last_updated"] = datetime.now(timezone.utc).isoformat()
    dashboard["runs"].append(run_data)

    # Max 50 Runs behalten
    if len(dashboard["runs"]) > 50:
        dashboard["runs"] = dashboard["runs"][-50:]

    with open(DASHBOARD_FILE, "w") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)

# ─── Fetcher ──────────────────────────────────────────────────────────────────

def fetch_liveuamap(slug):
    """Fetcht eine liveuamap-Region und gibt Liste von Textelementen zurück."""
    url = f"https://{slug}.liveuamap.com"
    html = fetch(url)
    if not html:
        return []

    items = []
    pattern = r'(\d+\s+(?:minute|hour|day|week)s?\s+ago)\s*\n\s*(.+?)(?=\n\n|\n\d+\s+(?:minute|hour|day)|$)'
    matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)

    if not matches:
        lines = [l.strip() for l in html.split('\n') if len(l.strip()) > 40]
        return [{"age": "?", "text": l} for l in lines[:20]]

    for age, text in matches[:15]:
        text = re.sub(r'\s+', ' ', text.strip())
        if len(text) > 20:
            items.append({"age": age.strip(), "text": text})
    return items

def fetch_gnews(query):
    """Fetcht Google News RSS und gibt Items zurück."""
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en&gl=US&ceid=US:en"
    xml = fetch(url)
    if not xml:
        return []
    titles = re.findall(r'<title><!\[CDATA\[(.+?)\]\]></title>', xml)
    if not titles:
        titles = re.findall(r'<title>(.+?)</title>', xml)[1:]
    return [{"age": "RSS", "text": t} for t in titles[:8]]

# ─── Discord-Alert Builder ────────────────────────────────────────────────────

def build_discord_alert(alert_items, total_score, alert_tier, affected_strategies, affected_tickers, deep_dive_terms):
    """Erstellt Tier-spezifisches Discord-Alert-Format."""
    strategies_str = ", ".join(affected_strategies) if affected_strategies else "–"
    tickers_str    = ", ".join(affected_tickers) if affected_tickers else "–"

    def fmt_item(item):
        emoji = "🔴" if item["level"] == "CRITICAL" else ("🟠" if item["level"] == "HIGH" else "🟡")
        text = item["text"][:140] + ("…" if len(item["text"]) > 140 else "")
        return f"{emoji} **{item['region']}** (Score {item['score']}): {text}"

    if alert_tier == "LOW":
        top = alert_items[:2]
        lines = [f"📡 **Geo-Alert** | Score {total_score}"]
        for item in top:
            lines.append(f"• {fmt_item(item)}")
        lines.append(f"Strategien: {strategies_str} | Tickers: {tickers_str}")
        return "\n".join(lines)

    elif alert_tier == "MEDIUM":
        top = alert_items[:3]
        lines = [f"⚠️ **Geo-Alert MEDIUM** | Score {total_score}"]
        for item in top:
            lines.append(f"• {fmt_item(item)}")
        lines.append(f"Strategien: {strategies_str} | Tickers: {tickers_str}")
        # Region summaries
        seen_regions = set()
        for item in top:
            src = item.get("source", "")
            if src and src != "gnews" and src not in seen_regions:
                seen_regions.add(src)
                lines.append(f"📍 **{item['region']}**: Erhöhte Aktivität erkannt — Score {item['score']}.")
        return "\n".join(lines)

    else:  # HIGH
        top = alert_items[:5]
        lines = [f"🚨 **GEO-ALERT HIGH** | Score {total_score}"]
        for item in top:
            lines.append(f"• {fmt_item(item)}")
        lines.append(f"Strategien: {strategies_str} | Tickers: {tickers_str}")
        if deep_dive_terms:
            terms_str = ", ".join(deep_dive_terms[:3])
            lines.append(f"⚡ Deep Dive empfohlen — sag \"Deep Dive {deep_dive_terms[0]}\"")
        return "\n".join(lines)

# ─── Haupt-Scanner ────────────────────────────────────────────────────────────

def run_scanner(tier=1, force=False):
    state = load_state()
    seen = state.get("seen", {})
    now = datetime.now(timezone.utc)
    ts_iso = now.isoformat()
    ts = now.strftime("%Y-%m-%d %H:%M UTC")

    findings    = []
    alert_items = []

    # Regionen zusammenstellen
    regions_to_scan = REGIONS[1].copy()
    if tier == "all" or tier == 2:
        regions_to_scan += REGIONS[2]

    # Welche Slugs werden gescannt?
    scanned_slugs = {slug for slug, _, _ in regions_to_scan}

    # ── Liveuamap scannen ──
    for slug, label, strategies in regions_to_scan:
        items = fetch_liveuamap(slug)
        for item in items:
            text = item["text"]
            h = item_hash(text)
            if h in seen and not force:
                continue
            seen[h] = ts

            score, matched = score_text(text)
            if score >= NOTIFY_THRESHOLD:
                level = "MEDIUM"
                if matched["CRITICAL"]:
                    level = "CRITICAL"
                elif matched["HIGH"]:
                    level = "HIGH"

                finding = {
                    "source": slug,
                    "region": label,
                    "strategies": strategies,
                    "age": item["age"],
                    "text": text,
                    "score": score,
                    "level": level,
                    "keywords": matched,
                }
                findings.append(finding)
                if score >= ALERT_THRESHOLD:
                    alert_items.append(finding)

    # ── Google News RSS scannen ──
    try:
        for query in GNEWS_QUERIES:
            items = fetch_gnews(query)
            for item in items:
                text = item["text"]
                h = item_hash(text)
                if h in seen and not force:
                    continue
                seen[h] = ts

                score, matched = score_text(text)
                if score >= NOTIFY_THRESHOLD:
                    level = "MEDIUM"
                    if matched["CRITICAL"]:
                        level = "CRITICAL"
                    elif matched["HIGH"]:
                        level = "HIGH"

                    finding = {
                        "source": "gnews",
                        "region": f"🌐 Google News: {query[:40]}",
                        "strategies": [],
                        "age": "RSS",
                        "text": text,
                        "score": score,
                        "level": level,
                        "keywords": matched,
                    }
                    findings.append(finding)
                    if score >= ALERT_THRESHOLD:
                        alert_items.append(finding)
    except Exception:
        pass

    # Sortieren nach Score (höchster zuerst)
    findings.sort(key=lambda x: x["score"], reverse=True)
    alert_items.sort(key=lambda x: x["score"], reverse=True)

    # ── Score + Tier berechnen ──
    total_score = sum(item["score"] for item in alert_items)
    alert_tier  = compute_alert_tier(total_score)
    deep_dive_recommended = total_score >= TIER_HIGH
    deep_dive_terms = compute_deep_dive_terms(alert_items, scanned_slugs) if alert_items else []

    # ── Portfolio-Impact ──
    # Nur Regionen mit score > 0 berücksichtigen
    affected_strategies, affected_tickers = compute_portfolio_impact(alert_items)

    # ── State speichern ──
    if len(seen) > 5000:
        seen_list = list(seen.items())
        seen = dict(seen_list[-4000:])
    state["seen"] = seen
    state["last_run"] = ts
    save_state(state)

    # ── Log schreiben ──
    log_findings(findings, ts)

    # ── Discord-Alert ──
    discord_message = None
    if alert_tier != "NONE":
        discord_message = build_discord_alert(
            alert_items, total_score, alert_tier,
            affected_strategies, affected_tickers, deep_dive_terms
        )

    # ── Dashboard-Run-Eintrag ──
    top_items_for_dashboard = []
    for item in alert_items[:5]:
        top_items_for_dashboard.append({
            "region": item.get("source", item["region"]),
            "text":   item["text"][:200],
            "score":  item["score"],
            "tier":   item["level"],
        })

    # Strategie-Heatmap: pro Strategie den höchsten Score des Tages
    strategy_scores = {}
    for item in alert_items:
        slug = item.get("source", "")
        if slug in PORTFOLIO_MAP:
            for s in PORTFOLIO_MAP[slug]["strategies"]:
                strategy_scores[s] = max(strategy_scores.get(s, 0), item["score"])

    run_data = {
        "ts":                   ts_iso,
        "total_score":          total_score,
        "alert_tier":           alert_tier,
        "alert_items":          len(alert_items),
        "affected_strategies":  affected_strategies,
        "affected_tickers":     affected_tickers,
        "top_items":            top_items_for_dashboard,
        "deep_dive_recommended": deep_dive_recommended,
        "deep_dive_terms":      deep_dive_terms,
        "strategy_scores":      strategy_scores,
    }
    update_dashboard(run_data)

    # ── JSON-Output ──
    result = {
        "ts":                   ts,
        "ts_iso":               ts_iso,
        "regions_scanned":      len(regions_to_scan),
        "new_items_total":      len(findings),
        "alert_items":          len(alert_items),
        "total_score":          total_score,
        "alert_tier":           alert_tier,
        "deep_dive_recommended": deep_dive_recommended,
        "deep_dive_terms":      deep_dive_terms,
        "affected_strategies":  affected_strategies,
        "affected_tickers":     affected_tickers,
        "top_findings":         findings[:5],
        "alert":                alert_tier != "NONE",
    }

    if discord_message:
        result["discord_message"] = discord_message

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result

# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tier  = 1
    force = False
    for arg in sys.argv[1:]:
        if arg.startswith("--tier="):
            val = arg.split("=")[1]
            tier = int(val) if val.isdigit() else val
        elif arg == "--force":
            force = True

    run_scanner(tier=tier, force=force)
