"""
trademind/core/config.py — Zentrale Konfiguration

Einzige Stelle für alle Pfade und Trading-Konstanten.
"""
import os
from pathlib import Path

# ── Pfade ──────────────────────────────────────────────────────────────────────
WORKSPACE = Path("/data/.openclaw/workspace")
DB_PATH   = WORKSPACE / "data" / "trading.db"
MEMORY_DIR  = WORKSPACE / "memory"
DATA_DIR    = WORKSPACE / "data"
SCRIPTS_DIR = WORKSPACE / "scripts"

# ── Portfolio-Konstanten ────────────────────────────────────────────────────────
DEFAULT_PORTFOLIO_SIZE = 100_000   # Virtuelles Portfolio (€)
DEFAULT_CRV = 3.0                  # Min. Chance-Risiko-Verhältnis

MAX_POSITIONS = {
    "low":      5,
    "medium":   4,
    "elevated": 3,
    "high":     2,
    "extreme":  1,
}

# VIX-adaptive Risikobudgets (% des Portfolios pro Trade)
RISK_PCT = {
    "low":      0.020,   # VIX < 20
    "medium":   0.015,   # VIX 20-25
    "elevated": 0.015,   # alias (albert_strategy nutzt 'elevated')
    "high":     0.010,   # VIX 25-35
    "extreme":  0.005,   # VIX > 35
}

MIN_CRV = {
    "low":      3.0,
    "medium":   3.0,
    "elevated": 3.0,
    "high":     4.0,
    "extreme":  5.0,
}

MAX_SECTOR_RISK_PCT = 0.04   # Max 4 % Risiko pro Sektor
MAX_SAME_THEME      = 2      # Max 2 Positionen im gleichen Geo-Theme
MIN_CASH_PCT        = 0.40   # Immer 40 % Cash halten
ATR_STOP_MULTIPLIER = 2.0    # 2× ATR als Stop-Distanz

# ── FX Fallback-Kurse (wenn Yahoo Finance nicht erreichbar) ────────────────────
FX_FALLBACK = {
    "USD": 0.87,
    "GBP": 1.16,
    "NOK": 0.084,
    "SEK": 0.083,
    "DKK": 0.134,
    "HKD": 0.112,
    "CAD": 0.64,
}
