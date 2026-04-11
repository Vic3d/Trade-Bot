#!/usr/bin/env python3.14
"""
config.py — Zentrale Konfiguration für TradeMind
=================================================
Einzige Quelle der Wahrheit für Pfade, DB, und Basis-Einstellungen.
"""
import os
from pathlib import Path

# Workspace Root — kann via Env-Variable überschrieben werden
WS = Path(os.getenv('TRADEMIND_HOME', '/data/.openclaw/workspace'))

# Datenbankpfad
DB = WS / 'data' / 'trading.db'
DB_PATH = DB  # Alias für Kompatibilität

# Daten-Verzeichnisse
DATA_DIR = WS / 'data'
MEMORY_DIR = WS / 'memory'
LOGS_DIR = WS / 'data'

# Strategien
STRATEGIES_JSON = DATA_DIR / 'strategies.json'
MARKET_REGIME_JSON = DATA_DIR / 'market-regime.json'
CEO_DIRECTIVE_JSON = DATA_DIR / 'ceo_directive.json'
PENDING_THESES_JSON = DATA_DIR / 'pending_theses.json'
CROWD_CACHE_JSON = DATA_DIR / 'crowd_cache.json'

# Trading-Parameter
ENTRY_THRESHOLD = 45          # Minimum Conviction Score für Entry
STRONG_CONVICTION = 60        # Score für volle Position (2% Risiko)
MAX_POSITION_RISK_PCT = 0.02  # Max 2% Portfolio-Risiko pro Trade
MAX_POSITION_SIZE_PCT = 0.05  # Max 5% Portfolio pro Position
MAX_OPEN_TRADES = 8           # Max gleichzeitig offene Trades
MAX_NEW_TRADES_PER_RUN = 3    # Max neue Trades pro Scanner-Lauf
