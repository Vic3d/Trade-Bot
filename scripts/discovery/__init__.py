"""Phase 7.15 — Ticker-Discovery-Engine.

Alle Discovery-Sources schreiben in data/candidate_tickers.json.
Der auto_deep_dive_runner.py liest die Kandidaten als Priority 1.5
und Deep-Divet sie. Bei KAUFEN-Verdict promotet discovery_pipeline.py
den Ticker zu einer autonomen Strategie in strategies.json.
"""
