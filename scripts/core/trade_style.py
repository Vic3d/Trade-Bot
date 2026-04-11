#!/usr/bin/env python3.14
"""
trade_style.py — Zentrale Definitionen für Day Trade vs Swing Trade
====================================================================

Day Trade:   Intraday — Entry + Exit am selben Tag. Enge Stops, hohe Conviction.
Swing Trade: Mehrere Tage bis Wochen. Breitere Stops, fundamentale Thesis-Stärke.

Import: from scripts.core.trade_style import get_style_config, classify_strategy
"""

from dataclasses import dataclass


@dataclass
class StyleConfig:
    name: str
    max_hold_days: int          # Maximale Haltedauer in Tagen
    forced_close_time: str | None  # "HH:MM" CET — Zwangsschluss (nur Day Trade)
    min_crv: float              # Mindest-CRV für Entry
    min_conviction: int         # Mindest-Conviction-Score 0-100
    max_vix: float              # VIX-Obergrenze (darüber kein Entry)
    min_stop_pct: float         # Minimaler Stop-Abstand in % (enger = teurer)
    max_stop_pct: float         # Maximaler Stop-Abstand in %
    position_size_mult: float   # Multiplikator auf Basis-Positionsgröße
    description: str


STYLES: dict[str, StyleConfig] = {
    'day': StyleConfig(
        name='Day Trade',
        max_hold_days=1,
        forced_close_time='21:50',   # 10 Min vor Marktschluss DE/US
        min_crv=2.0,                 # Mindest CRV 2:1 (schnell, kein Margin für Fehler)
        min_conviction=65,           # Hohe Conviction nötig — kein Zeit für Korrekturen
        max_vix=25.0,                # Bei VIX > 25 zu viel Noise für Intraday
        min_stop_pct=0.5,            # Stops engstens 0.5% (sonst kein Profit)
        max_stop_pct=2.5,            # Stops max 2.5% (Day Trade bleibt eng)
        position_size_mult=0.8,      # Etwas kleiner — Risiko pro Trade
        description='Intraday. Zwangsschluss 21:50 CET. Enge Stops. Hohe Conviction.',
    ),
    'swing': StyleConfig(
        name='Swing Trade',
        max_hold_days=20,
        forced_close_time=None,      # Kein Zwangsschluss — kann über Nacht halten
        min_crv=1.5,                 # Mindest CRV 1.5:1 (mehr Zeit = mehr Spielraum)
        min_conviction=45,           # Moderate Conviction reicht
        max_vix=35.0,                # Swing kann auch bei höherem VIX halten
        min_stop_pct=2.0,            # Stop mindestens 2% weg (sonst Whipsaw)
        max_stop_pct=10.0,           # Stop max 10% (für volatile Thesis-Plays)
        position_size_mult=1.0,      # Normale Positionsgröße
        description='Mehrtägig bis mehrwöchig. Kein Zwangsschluss. Thesis-getrieben.',
    ),
}

# Welche Strategie-Präfixe sind Day Trades?
DAY_TRADE_STRATEGIES = {'DT1', 'DT2', 'DT3', 'DT4', 'DT5', 'AR-AGRA', 'AR-HALB'}


def classify_strategy(strategy: str) -> str:
    """
    Gibt 'day' oder 'swing' zurück basierend auf Strategie-Prefix.
    DT* = Day Trade, alles andere = Swing.
    """
    prefix = strategy.split('_')[0].upper()
    return 'day' if prefix in DAY_TRADE_STRATEGIES else 'swing'


def get_style_config(style: str) -> StyleConfig:
    """Gibt StyleConfig für 'day' oder 'swing' zurück."""
    return STYLES.get(style, STYLES['swing'])


def validate_stop_for_style(entry: float, stop: float, style: str) -> tuple[bool, str]:
    """
    Prüft ob Stop-Abstand zum Trade-Style passt.
    Returns: (ok: bool, reason: str)
    """
    cfg = get_style_config(style)
    if entry <= 0:
        return False, "Entry-Preis ungültig"
    stop_pct = abs(entry - stop) / entry * 100
    if stop_pct < cfg.min_stop_pct:
        return False, f"{style.upper()}: Stop {stop_pct:.1f}% zu eng (min {cfg.min_stop_pct}%)"
    if stop_pct > cfg.max_stop_pct:
        return False, f"{style.upper()}: Stop {stop_pct:.1f}% zu weit (max {cfg.max_stop_pct}%)"
    return True, "OK"


def validate_crv_for_style(entry: float, stop: float, target: float, style: str) -> tuple[bool, str]:
    """Prüft ob CRV dem Style entspricht."""
    cfg = get_style_config(style)
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk <= 0:
        return False, "Kein Risiko definiert"
    crv = reward / risk
    if crv < cfg.min_crv:
        return False, f"{style.upper()}: CRV {crv:.1f} zu niedrig (min {cfg.min_crv})"
    return True, "OK"


def needs_forced_close(style: str) -> bool:
    """True wenn Trades dieses Styles am selben Tag geschlossen werden müssen."""
    cfg = get_style_config(style)
    return cfg.forced_close_time is not None


def get_forced_close_time(style: str) -> str | None:
    """Gibt Zwangsschluss-Zeit zurück (HH:MM CET) oder None."""
    return get_style_config(style).forced_close_time
