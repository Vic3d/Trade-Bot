#!/usr/bin/env python3
"""
source_ranker.py — Source-Tier-Ranking für Overnight-Research-System
Tier 1: Primärquellen (Nachrichtenagenturen, Militär, Regierung)
Tier 2: Finanz-/Qualitätsmedien
Tier 3: Andere / unbekannte Quellen
"""

SOURCE_TIER_KEYWORDS = {
    1: ["liveuamap", "reuters", "apnews", "ap news", "dpa", "bbc", "gov", "centcom", "pentagon",
        "mil.gov", "nato.int", "un.org", "whitehouse", "state.gov", "defense.gov",
        "maritime-executive", "al jazeera", "aljazeera", "afp"],
    2: ["bloomberg", "ft.com", "wsj", "google", "finnhub", "polygon", "marketwatch", "yahoo",
        "cnbc", "economist", "handelsblatt", "spiegel", "zeit.de", "faz.net",
        "investing.com", "seekingalpha", "barrons", "thestreet"],
}


def rank_source(source: str) -> int:
    """
    Gibt Tier 1, 2 oder 3 zurück.
    Tier 1 = höchste Qualität/Primärquelle
    Tier 3 = unbekannte/niedrige Quelle
    """
    if not source:
        return 3
    s = source.lower()
    for tier, kws in SOURCE_TIER_KEYWORDS.items():
        if any(k in s for k in kws):
            return tier
    return 3


if __name__ == "__main__":
    # Quick test
    test_sources = [
        "Reuters",
        "bloomberg_markets",
        "Bloomberg Energy",
        "Google News",
        "liveuamap.com",
        "BBC News",
        "Unknown Blog",
        "CENTCOM",
        "MarketWatch",
        "some random website",
    ]
    print("Source Tier Test:")
    for src in test_sources:
        print(f"  {rank_source(src)} — {src}")
