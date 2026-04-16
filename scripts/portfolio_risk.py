#!/usr/bin/env python3
"""
Portfolio Risk Management 3.0 — Phase 21 (Korrelations-basiert)

Pro-Level Risiko-Checks die das Portfolio vor Cluster-Risiken,
Drawdown-Spiralen und schlecht dimensionierten Positionen schützen.

7 Checks:
1. check_correlation()        — Cluster-Risiko + Size-Factor (z.B. 3x Öl = 1 Bet)
2. kelly_position_size()      — Dynamische Kelly-basierte Größe
3. volatility_adjusted_size() — VIX-skalierte Positionsgröße
4. check_sector_exposure()    — Max 30% pro Sektor
5. check_drawdown_circuit()   — -5% in 7 Tagen → Pause

Portfolio-Level Analytics (Phase 21):
6. compute_full_matrix()          — NxN Korrelationsmatrix
7. compute_diversification_ratio() — Diversifikations-Score
8. compute_herfindahl_sector()    — Sektor-Konzentration
9. find_correlation_clusters()    — Korrelierte Gruppen erkennen
10. compute_parametric_var()      — Value at Risk in EUR

Alle Funktionen sind defensiv: bei fehlenden Daten → graceful degradation,
keine Blockade von Trades (better safe: loggen, nicht blockieren wenn Daten fehlen).

Integration:
    from scripts.portfolio_risk import run_all_risk_checks
    risk = run_all_risk_checks(ticker='OXY', strategy_id='PS1', base_size=1500)
    if risk['blocked']:
        return {'success': False, 'blocked_by': risk['blocked_by'], 'reason': risk['reason']}
    final_size = risk['final_size']
    size_factor = risk.get('size_factor', 1.0)  # Correlation-based scaling
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import statistics
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')
from pathlib import Path
from typing import Any

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
LEARNINGS = WS / 'data' / 'trading_learnings.json'
RISK_STATE = WS / 'data' / 'risk_state.json'
LOG_FILE = WS / 'data' / 'portfolio_risk.log'

log = logging.getLogger('portfolio_risk')
if not log.handlers:
    _h = logging.FileHandler(LOG_FILE)
    _h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    log.addHandler(_h)
    log.setLevel(logging.INFO)


# ────────────────────────────────────────────────────────────────────────────
# Ticker → Sektor Mapping
# ────────────────────────────────────────────────────────────────────────────

TICKER_SECTOR: dict[str, str] = {
    # Energy / Oil & Gas
    'OXY': 'energy', 'XOM': 'energy', 'CVX': 'energy', 'EOG': 'energy',
    'COP': 'energy', 'PSX': 'energy', 'MPC': 'energy', 'VLO': 'energy',
    'DINO': 'energy', 'SLB': 'energy', 'HAL': 'energy',
    'EQNR': 'energy', 'EQNR.OL': 'energy', 'TTE.PA': 'energy',
    'SHEL.L': 'energy', 'BP.L': 'energy',
    # Shipping / Tanker (highly correlated with oil)
    'FRO': 'energy', 'DHT': 'energy', 'EURN': 'energy', 'TK': 'energy',
    'STNG': 'energy', 'TNK': 'energy',
    # Tech — Large Cap
    'AAPL': 'tech_mega', 'MSFT': 'tech_mega', 'GOOGL': 'tech_mega',
    'AMZN': 'tech_mega', 'META': 'tech_mega',
    # Tech — Semiconductor
    'NVDA': 'semi', 'AMD': 'semi', 'INTC': 'semi', 'ASML': 'semi',
    'AMAT': 'semi', 'ARM': 'semi', 'QCOM': 'semi', 'MU': 'semi',
    'AVGO': 'semi', 'IFX.DE': 'semi', 'SMCI': 'semi', 'TSM': 'semi',
    # Tech — Software / Cloud
    'SAP.DE': 'software', 'ORCL': 'software', 'CRM': 'software',
    'ADBE': 'software', 'NOW': 'software', 'SNOW': 'software',
    'PLTR': 'software',
    # EV / Auto
    'TSLA': 'auto', 'BMW.DE': 'auto', 'MBG.DE': 'auto', 'VOW3.DE': 'auto',
    'BYDDY': 'auto', 'NIO': 'auto', 'RIVN': 'auto',
    # Defense / Aerospace
    'RHM.DE': 'defense', 'LMT': 'defense', 'RTX': 'defense', 'NOC': 'defense',
    'GD': 'defense', 'AIR.PA': 'defense', 'HAG.DE': 'defense',
    'BA.L': 'defense', 'KTOS': 'defense', 'HII': 'defense', 'BWXT': 'defense',
    'BA': 'defense',
    # Financial
    'JPM': 'financial', 'BAC': 'financial', 'GS': 'financial', 'MS': 'financial',
    'WFC': 'financial', 'C': 'financial', 'V': 'financial', 'MA': 'financial',
    'DBK.DE': 'financial', 'ALV.DE': 'financial', 'UBS': 'financial',
    # Pharma / Biotech
    'NVO': 'pharma', 'LLY': 'pharma', 'ABBV': 'pharma', 'PFE': 'pharma',
    'MRK': 'pharma', 'JNJ': 'pharma', 'BAYN.DE': 'pharma', 'UNH': 'healthcare',
    'CVS': 'healthcare', 'BMY': 'pharma',
    # Consumer / Retail
    'ADS.DE': 'consumer', 'NKE': 'consumer', 'WMT': 'consumer',
    'COST': 'consumer', 'MCD': 'consumer',
    # Crypto-proxies (highly correlated)
    'COIN': 'crypto', 'MSTR': 'crypto', 'MARA': 'crypto', 'RIOT': 'crypto',
    'HUT': 'crypto',
    # Industrial
    'SIE.DE': 'industrial', 'GE': 'industrial', 'HON': 'industrial',
    # Materials / Mining
    'AG': 'mining', 'GOLD': 'mining', 'NEM': 'mining', 'FCX': 'mining',
    'MOS': 'materials', 'ADM': 'materials',
    # Agriculture
    'ANET': 'tech_networking',  # Arista Networks
}

def get_sector(ticker: str) -> str:
    """Gibt Sektor-Code zurück, fällt auf 'unknown' zurück bei unbekanntem Ticker."""
    if not ticker:
        return 'unknown'
    return TICKER_SECTOR.get(ticker.upper(), 'unknown')


# ────────────────────────────────────────────────────────────────────────────
# DB Helpers
# ────────────────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def _get_open_positions() -> list[dict]:
    """Alle aktuell offenen Paper-Trades aus paper_portfolio (Single Source of Truth).

    paper_portfolio hat keine position_size_eur-Spalte — wir leiten sie aus
    shares*entry_price ab, damit downstream-Code unverändert bleiben kann.
    """
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT ticker, strategy, entry_price, shares, "
            "COALESCE(shares, 0) * COALESCE(entry_price, 0) AS position_size_eur, "
            "entry_date, sector "
            "FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error(f"_get_open_positions: {e}")
        return []


def _get_cash() -> float:
    """Aktueller Cash-Wert aus paper_fund (Key-Value Schema: current_cash)."""
    try:
        conn = _db()
        row = conn.execute(
            "SELECT value FROM paper_fund WHERE key IN ('current_cash', 'cash') "
            "ORDER BY CASE key WHEN 'current_cash' THEN 0 ELSE 1 END LIMIT 1"
        ).fetchone()
        conn.close()
        return float(row[0]) if row else 25000.0
    except Exception:
        return 25000.0


def _get_fund_value() -> float:
    """Gesamter Portfolio-Wert = Cash + offene Positionen (Entry-basiert).

    Für die Size-Berechnung ist Entry-Wert eine konservative Schätzung,
    weil MTM sich ständig ändert. Kelly soll stabil sizen.
    """
    cash = _get_cash()
    positions = _get_open_positions()
    position_value = sum((p.get('position_size_eur') or 0) for p in positions)
    return cash + position_value


def _get_vix() -> float | None:
    """Liest aktuellen VIX aus macro_daily. None wenn nicht verfügbar."""
    try:
        conn = _db()
        row = conn.execute(
            "SELECT value FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return float(row[0]) if row else None
    except Exception as e:
        log.warning(f"_get_vix: {e}")
        return None


def _get_price_series(ticker: str, days: int = 30) -> list[float]:
    """Holt die letzten N täglichen Schlusskurse eines Tickers aus der prices-Tabelle."""
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT ?",
            (ticker.upper(), days),
        ).fetchall()
        conn.close()
        # älteste zuerst
        return list(reversed([float(r[0]) for r in rows]))
    except Exception:
        return []


# ────────────────────────────────────────────────────────────────────────────
# CHECK 1: Portfolio-Korrelation (Cluster-Risiko)
# ────────────────────────────────────────────────────────────────────────────

def _pearson(a: list[float], b: list[float]) -> float | None:
    """Einfache Pearson-Korrelation. Gibt None zurück wenn nicht berechenbar."""
    if len(a) != len(b) or len(a) < 10:
        return None
    try:
        mean_a = statistics.mean(a)
        mean_b = statistics.mean(b)
        num = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        den_a = sum((x - mean_a) ** 2 for x in a)
        den_b = sum((y - mean_b) ** 2 for y in b)
        if den_a == 0 or den_b == 0:
            return None
        return num / ((den_a * den_b) ** 0.5)
    except Exception:
        return None


def _pct_returns(prices: list[float]) -> list[float]:
    """Tägliche Prozent-Returns aus Kurs-Serie."""
    if len(prices) < 2:
        return []
    return [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
        if prices[i - 1] > 0
    ]


def check_correlation(
    new_ticker: str,
    threshold_block: float = 0.70,
    threshold_reduce: float = 0.50,
    max_correlated: int = 2,
) -> dict:
    """
    Phase 21: Erweiterter Korrelations-Check mit Size-Factor.

    Logik:
    - corr < 0.50: size_factor=1.0 (volle Größe)
    - corr 0.50-0.70: size_factor linear runter auf 0.5
    - corr > 0.70 bei 2+ Positionen: BLOCK (Cluster-Risiko)
    - Sektor-Override: gleicher Sektor = Minimum-Korrelation 0.60

    Args:
        new_ticker: Neuer Ticker der gekauft werden soll
        threshold_block: Ab dieser Korrelation zählt als "hoch korreliert" (0.70)
        threshold_reduce: Ab dieser Korrelation Size-Reduktion (0.50)
        max_correlated: Ab wie vielen hoch-korrelierten Positionen blockiert wird

    Returns:
        {blocked, reason, max_correlation, correlated_with, size_factor, cluster_warning}
    """
    result_base = {
        'blocked': False, 'reason': '', 'max_correlation': 0.0,
        'correlated_with': [], 'size_factor': 1.0, 'cluster_warning': None,
    }

    positions = _get_open_positions()
    if not positions:
        return result_base

    new_prices = _get_price_series(new_ticker, days=30)
    if len(new_prices) < 15:
        log.info(f"Korrelation skipped: {new_ticker} hat nur {len(new_prices)} Kurse")
        result_base['reason'] = 'insufficient_history'
        return result_base

    new_rets = _pct_returns(new_prices)
    new_sector = get_sector(new_ticker)
    all_corrs: list[tuple[str, float]] = []
    high_correlated: list[tuple[str, float]] = []
    max_corr = 0.0

    for pos in positions:
        pos_ticker = pos.get('ticker', '')
        if not pos_ticker or pos_ticker.upper() == new_ticker.upper():
            continue

        pos_prices = _get_price_series(pos_ticker, days=30)
        pos_rets = _pct_returns(pos_prices) if len(pos_prices) >= 15 else []

        # Korrelation berechnen
        n = min(len(new_rets), len(pos_rets))
        corr = _pearson(new_rets[-n:], pos_rets[-n:]) if n >= 10 else None

        # Sektor-Override: gleicher Sektor = min 0.60 Korrelation
        # (Öl-Aktien fallen zusammen auch wenn Returns kurzfristig divergieren)
        pos_sector = get_sector(pos_ticker)
        if (pos_sector == new_sector and new_sector != 'unknown'):
            sector_min = 0.60
            if corr is None or corr < sector_min:
                corr = sector_min
                log.info(f"Sector override: {new_ticker}↔{pos_ticker} ({new_sector}) → corr={corr}")

        if corr is None:
            continue

        all_corrs.append((pos_ticker, round(corr, 3)))
        if abs(corr) > abs(max_corr):
            max_corr = corr
        if corr >= threshold_block:
            high_correlated.append((pos_ticker, round(corr, 3)))

    # Entscheidung: Block wenn 2+ hoch korreliert
    if len(high_correlated) >= max_correlated:
        return {
            'blocked': True,
            'reason': (
                f'CLUSTER_RISK: {len(high_correlated)} Positionen korrelieren > {threshold_block} '
                f'({", ".join(f"{t}={c}" for t, c in high_correlated)})'
            ),
            'max_correlation': round(max_corr, 3),
            'correlated_with': high_correlated,
            'size_factor': 0.0,
            'cluster_warning': None,
        }

    # Size-Factor: abgestufte Reduktion bei mittlerer Korrelation
    size_factor = 1.0
    if all_corrs:
        # Durchschnitt der Korrelationen mit bestehenden Positionen
        avg_corr = sum(c for _, c in all_corrs) / len(all_corrs)
        if avg_corr >= threshold_reduce:
            # Linear: 1.0 bei threshold_reduce, 0.5 bei threshold_block
            range_width = threshold_block - threshold_reduce
            if range_width > 0:
                reduction = (avg_corr - threshold_reduce) / range_width
                size_factor = max(0.5, 1.0 - reduction * 0.5)

    # Cluster-Warning: 3+ Positionen im selben Sektor
    same_sector_count = sum(
        1 for p in positions
        if get_sector(p.get('ticker', '')) == new_sector and new_sector != 'unknown'
    )
    cluster_warning = None
    if same_sector_count >= 2:
        cluster_warning = f'{same_sector_count + 1} Positionen in Sektor "{new_sector}"'

    reason = ''
    if size_factor < 1.0:
        reason = f'Corr-Adjust: size_factor={size_factor:.0%} (avg_corr={avg_corr:.2f})'
    if cluster_warning:
        reason = f'{reason}; {cluster_warning}' if reason else cluster_warning

    return {
        'blocked': False,
        'reason': reason,
        'max_correlation': round(max_corr, 3),
        'correlated_with': all_corrs,
        'size_factor': round(size_factor, 2),
        'cluster_warning': cluster_warning,
    }


# ────────────────────────────────────────────────────────────────────────────
# CHECK 2: Kelly Criterion Position Sizing
# ────────────────────────────────────────────────────────────────────────────

def _load_learnings() -> dict:
    if not LEARNINGS.exists():
        return {}
    try:
        return json.loads(LEARNINGS.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _get_strategy_stats(strategy_id: str) -> dict | None:
    """
    Holt Win-Rate, avg_win, avg_loss, trade_count für eine Strategie
    aus trades-Tabelle (historisch, reell).
    """
    try:
        conn = _db()
        # Alle geschlossenen Trades dieser Strategie
        rows = conn.execute(
            "SELECT pnl_eur FROM paper_portfolio WHERE strategy=? AND status IN ('CLOSED','WIN','LOSS') AND pnl_eur IS NOT NULL",
            (strategy_id,),
        ).fetchall()
        conn.close()
        if not rows:
            return None
        pnls = [float(r[0]) for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        n = len(pnls)
        if n < 5:
            return None  # Zu wenig Daten für Kelly
        win_rate = len(wins) / n
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 1.0
        return {
            'n_trades': n,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
        }
    except Exception as e:
        log.warning(f"_get_strategy_stats({strategy_id}): {e}")
        return None


def kelly_position_size(
    strategy_id: str,
    fund_value: float | None = None,
    base_default: float = 1500.0,
    kelly_fraction: float = 0.25,
    min_size: float = 500.0,
    max_size: float = 2000.0,
) -> dict:
    """
    Berechnet Kelly-optimale Position-Größe basierend auf historischer Performance.

    Formel: f* = (p*b - q) / b
    - p = Win-Rate
    - q = 1 - p (Loss-Rate)
    - b = avg_win / avg_loss (Payoff-Ratio)

    Wir verwenden Quarter-Kelly (0.25 * f*) als konservative Annäherung,
    weil Full Kelly in der Praxis zu volatil ist (hohe Ruin-Wahrscheinlichkeit
    bei Estimation-Error der Parameter).

    Graceful degradation:
    - < 5 historische Trades → base_default
    - Negative Kelly (Strategie verliert Geld) → min_size (kleinstmögliche Position)
    - Kelly > 10% des Fund → auf 10% Fund capped

    Returns:
        {
            final_size: float,
            method: 'kelly'|'default'|'min_loss',
            kelly_f: float | None,
            n_trades: int | None,
            reason: str,
        }
    """
    if fund_value is None:
        fund_value = _get_fund_value()

    stats = _get_strategy_stats(strategy_id)
    if not stats or stats['n_trades'] < 5:
        # Zu wenig Daten → Default-Size
        size = max(min_size, min(base_default, max_size, fund_value * 0.06))
        return {
            'final_size': round(size, 2),
            'method': 'default',
            'kelly_f': None,
            'n_trades': stats['n_trades'] if stats else 0,
            'reason': f'Insufficient history ({stats["n_trades"] if stats else 0} trades)',
        }

    p = stats['win_rate']
    b = stats['avg_win'] / stats['avg_loss'] if stats['avg_loss'] > 0 else 1.0
    q = 1.0 - p
    kelly_f = (p * b - q) / b if b > 0 else -1.0

    if kelly_f <= 0:
        # Strategie verliert Erwartungswert → kleinstmögliche Position
        # (oder gar nicht tradieren — aber das regelt der Learning Loop)
        return {
            'final_size': round(min_size, 2),
            'method': 'min_loss',
            'kelly_f': round(kelly_f, 4),
            'n_trades': stats['n_trades'],
            'reason': f'Negative Kelly (WR={p:.0%}, payoff={b:.2f}) → min size',
        }

    # Quarter Kelly
    size_pct = kelly_fraction * kelly_f
    # Hard cap: max 10% of fund per position (never oversize)
    size_pct = min(size_pct, 0.10)
    size = fund_value * size_pct
    # Floor / Ceiling
    size = max(min_size, min(max_size, size))

    return {
        'final_size': round(size, 2),
        'method': 'kelly',
        'kelly_f': round(kelly_f, 4),
        'n_trades': stats['n_trades'],
        'reason': f'Kelly OK (WR={p:.0%}, payoff={b:.2f}, f*={kelly_f:.2f}, quarter-Kelly={size_pct:.1%})',
    }


# ────────────────────────────────────────────────────────────────────────────
# CHECK 3: Volatility-Adjusted Sizing (VIX-Scaling)
# ────────────────────────────────────────────────────────────────────────────

def volatility_adjusted_size(base_size: float, vix: float | None = None) -> dict:
    """
    Skaliert Position-Größe basierend auf VIX-Regime.

    Standardisierte Skala:
    - VIX < 15:  1.00x  (low vol, full size)
    - VIX 15-20: 1.00x  (normal vol)
    - VIX 20-25: 0.75x  (elevated vol)
    - VIX 25-30: 0.50x  (stress)
    - VIX > 30:  0.25x  (panic, only highest conviction)

    Wenn VIX nicht verfügbar → base_size unverändert.
    """
    if vix is None:
        vix = _get_vix()

    if vix is None:
        return {
            'adjusted_size': base_size,
            'multiplier': 1.0,
            'vix': None,
            'regime': 'unknown',
        }

    if vix < 20:
        mult, regime = 1.00, 'normal'
    elif vix < 25:
        mult, regime = 0.75, 'elevated'
    elif vix < 30:
        mult, regime = 0.50, 'stress'
    else:
        mult, regime = 0.25, 'panic'

    return {
        'adjusted_size': round(base_size * mult, 2),
        'multiplier': mult,
        'vix': round(vix, 2),
        'regime': regime,
    }


# ────────────────────────────────────────────────────────────────────────────
# CHECK 4: Sector Exposure Limit
# ────────────────────────────────────────────────────────────────────────────

def check_sector_exposure(
    new_ticker: str,
    new_size_eur: float,
    max_sector_pct: float = 0.30,
) -> dict:
    """
    Prüft ob neue Position den Sektor über den Grenzwert drücken würde.

    Max 30% des Fund-Value in einem Sektor (Standard bei Profi-Portfolio-Bau).

    Returns:
        {
            blocked: bool,
            reason: str,
            sector: str,
            current_sector_eur: float,
            current_sector_pct: float,
            after_trade_pct: float,
        }
    """
    new_sector = get_sector(new_ticker)
    fund_value = _get_fund_value()

    if new_sector == 'unknown':
        # Unbekannter Sektor → können wir nicht prüfen, nicht blockieren
        return {
            'blocked': False,
            'reason': 'unknown_sector',
            'sector': 'unknown',
            'current_sector_eur': 0.0,
            'current_sector_pct': 0.0,
            'after_trade_pct': 0.0,
        }

    positions = _get_open_positions()
    sector_eur = sum(
        (p.get('position_size_eur') or 0)
        for p in positions
        if get_sector(p.get('ticker', '')) == new_sector
    )
    current_pct = sector_eur / fund_value if fund_value > 0 else 0.0
    after_pct = (sector_eur + new_size_eur) / fund_value if fund_value > 0 else 0.0

    if after_pct > max_sector_pct:
        return {
            'blocked': True,
            'reason': (
                f'SECTOR_LIMIT: {new_sector} wäre bei {after_pct:.0%} '
                f'(max {max_sector_pct:.0%})'
            ),
            'sector': new_sector,
            'current_sector_eur': round(sector_eur, 2),
            'current_sector_pct': round(current_pct, 4),
            'after_trade_pct': round(after_pct, 4),
        }

    return {
        'blocked': False,
        'reason': '',
        'sector': new_sector,
        'current_sector_eur': round(sector_eur, 2),
        'current_sector_pct': round(current_pct, 4),
        'after_trade_pct': round(after_pct, 4),
    }


# ────────────────────────────────────────────────────────────────────────────
# CHECK 5: Drawdown Circuit Breaker
# ────────────────────────────────────────────────────────────────────────────

def _load_risk_state() -> dict:
    if not RISK_STATE.exists():
        return {}
    try:
        return json.loads(RISK_STATE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_risk_state(state: dict) -> None:
    try:
        RISK_STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    except Exception as e:
        log.error(f"_save_risk_state: {e}")


def _get_portfolio_value_series(days: int = 8) -> list[tuple[str, float]]:
    """
    Rekonstruiert tägliche Portfolio-Werte aus Trades.
    Simplified: Cash + entry_value aller offenen Positionen pro Tag.
    Für strikten Drawdown-Check müsste man MTM bewerten — das holen wir
    aus dem paper_exit_manager falls verfügbar, sonst aus Equity-Snapshot.
    """
    # Versuche zuerst einen dedizierten Equity-Snapshot zu lesen
    eq_file = WS / 'data' / 'equity_curve.json'
    if eq_file.exists():
        try:
            data = json.loads(eq_file.read_text(encoding='utf-8'))
            # Erwartet: {date: total_value} oder Liste
            if isinstance(data, dict):
                items = sorted(data.items())
                return [(d, float(v)) for d, v in items[-days:]]
            elif isinstance(data, list):
                # [{date, value}, ...]
                return [
                    (e.get('date', ''), float(e.get('value', 0)))
                    for e in data[-days:]
                    if e.get('date')
                ]
        except Exception:
            pass
    return []


def check_drawdown_circuit(
    max_dd_pct: float = 0.05,
    lookback_days: int = 7,
    pause_hours: int = 24,
) -> dict:
    """
    Prüft ob Portfolio in den letzten N Tagen mehr als max_dd_pct verloren hat.
    Wenn ja → Pause-Flag setzen für `pause_hours`.

    Während der Pause: keine neuen Entries, nur Exits/Hedges.

    Returns:
        {blocked, reason, peak_value, current_value, drawdown_pct, pause_until}
    """
    state = _load_risk_state()
    now = datetime.now(_BERLIN)

    # Wenn Pause aktiv und noch nicht abgelaufen → blockieren
    pause_until_str = state.get('dd_pause_until')
    if pause_until_str:
        try:
            pause_until = datetime.fromisoformat(pause_until_str)
            if now < pause_until:
                return {
                    'blocked': True,
                    'reason': f'DRAWDOWN_PAUSE aktiv bis {pause_until.strftime("%Y-%m-%d %H:%M")}',
                    'peak_value': state.get('dd_peak', 0),
                    'current_value': state.get('dd_current', 0),
                    'drawdown_pct': state.get('dd_pct', 0),
                    'pause_until': pause_until_str,
                }
        except Exception:
            pass

    # Aktuelle Equity-Kurve holen
    series = _get_portfolio_value_series(days=lookback_days + 1)
    if len(series) < 3:
        # Nicht genug Daten → durchlassen
        return {
            'blocked': False,
            'reason': 'insufficient_equity_history',
            'peak_value': 0,
            'current_value': 0,
            'drawdown_pct': 0,
            'pause_until': None,
        }

    values = [v for _, v in series]
    peak = max(values)
    current = values[-1]
    dd_pct = (peak - current) / peak if peak > 0 else 0.0

    if dd_pct >= max_dd_pct:
        # Circuit Breaker auslösen
        pause_until = now + timedelta(hours=pause_hours)
        state['dd_pause_until'] = pause_until.isoformat()
        state['dd_peak'] = peak
        state['dd_current'] = current
        state['dd_pct'] = round(dd_pct, 4)
        state['dd_triggered_at'] = now.isoformat()
        _save_risk_state(state)
        log.warning(
            f"CIRCUIT BREAKER ausgelöst: peak={peak:.0f} current={current:.0f} "
            f"dd={dd_pct:.1%} → Pause bis {pause_until}"
        )
        return {
            'blocked': True,
            'reason': (
                f'CIRCUIT_BREAKER: {dd_pct:.1%} Drawdown in {lookback_days}d '
                f'(peak={peak:.0f}€, current={current:.0f}€)'
            ),
            'peak_value': round(peak, 2),
            'current_value': round(current, 2),
            'drawdown_pct': round(dd_pct, 4),
            'pause_until': pause_until.isoformat(),
        }

    return {
        'blocked': False,
        'reason': '',
        'peak_value': round(peak, 2),
        'current_value': round(current, 2),
        'drawdown_pct': round(dd_pct, 4),
        'pause_until': None,
    }


# ────────────────────────────────────────────────────────────────────────────
# Phase 21: Portfolio-Level Correlation Analytics
# ────────────────────────────────────────────────────────────────────────────

def compute_full_matrix(tickers: list[str], days: int = 30) -> dict[str, dict[str, float]]:
    """
    NxN Korrelationsmatrix für alle gegebenen Tickers.
    Berechnet Returns einmal pro Ticker, dann alle paarweisen Korrelationen.
    Für N=15 sind das 105 Paare — trivial in pure Python.

    Returns:
        {'NVDA': {'MSFT': 0.72, 'OXY': -0.01, ...}, ...}
    """
    # Returns einmal pro Ticker berechnen
    returns: dict[str, list[float]] = {}
    for t in tickers:
        prices = _get_price_series(t, days=days)
        if len(prices) >= 10:
            returns[t] = _pct_returns(prices)

    valid_tickers = list(returns.keys())
    matrix: dict[str, dict[str, float]] = {}

    for i, t_a in enumerate(valid_tickers):
        matrix[t_a] = {}
        for j, t_b in enumerate(valid_tickers):
            if i == j:
                matrix[t_a][t_b] = 1.0
                continue
            if j < i:
                # Symmetrisch — bereits berechnet
                matrix[t_a][t_b] = matrix[t_b][t_a]
                continue
            # Auf gleiche Länge kürzen
            n = min(len(returns[t_a]), len(returns[t_b]))
            if n < 10:
                matrix[t_a][t_b] = 0.0
                continue
            corr = _pearson(returns[t_a][-n:], returns[t_b][-n:])
            matrix[t_a][t_b] = round(corr, 3) if corr is not None else 0.0

    return matrix


def compute_diversification_ratio(
    positions: list[dict],
    corr_matrix: dict[str, dict[str, float]],
) -> float:
    """
    Portfolio Diversification Ratio = wertgewichteter Durchschnitt aller paarweisen Korrelationen.
    0.0 = perfekt diversifiziert, 1.0 = alle Positionen identisch.
    """
    if len(positions) < 2:
        return 0.0

    total_value = sum((p.get('position_size_eur') or 0) for p in positions)
    if total_value <= 0:
        total_value = len(positions)  # Fallback: gleiche Gewichtung

    weighted_sum = 0.0
    weight_total = 0.0

    for i in range(len(positions)):
        t_a = positions[i].get('ticker', '').upper()
        val_a = (positions[i].get('position_size_eur') or 0) or (total_value / len(positions))
        for j in range(i + 1, len(positions)):
            t_b = positions[j].get('ticker', '').upper()
            val_b = (positions[j].get('position_size_eur') or 0) or (total_value / len(positions))
            weight = val_a * val_b
            corr = corr_matrix.get(t_a, {}).get(t_b, 0.0)
            weighted_sum += weight * corr
            weight_total += weight

    return round(weighted_sum / weight_total, 3) if weight_total > 0 else 0.0


def compute_herfindahl_sector(positions: list[dict]) -> float:
    """
    Herfindahl-Hirschman Index für Sektor-Konzentration.
    HHI = Summe der quadrierten Sektor-Gewichte.
    1.0 = nur ein Sektor, ~0.1 = gut diversifiziert über 10 Sektoren.
    """
    total_value = sum((p.get('position_size_eur') or 0) for p in positions)
    if total_value <= 0:
        total_value = len(positions)

    sector_values: dict[str, float] = {}
    for p in positions:
        sector = get_sector(p.get('ticker', ''))
        val = (p.get('position_size_eur') or 0) or (total_value / len(positions))
        sector_values[sector] = sector_values.get(sector, 0) + val

    hhi = sum((v / total_value) ** 2 for v in sector_values.values()) if total_value > 0 else 1.0
    return round(hhi, 3)


def find_correlation_clusters(
    corr_matrix: dict[str, dict[str, float]],
    threshold: float = 0.60,
) -> list[list[str]]:
    """
    Findet Gruppen von 3+ Positionen wo alle paarweisen Korrelationen > threshold.
    Greedy Clique Detection (ausreichend für N < 20).
    """
    tickers = list(corr_matrix.keys())
    clusters: list[list[str]] = []
    used: set[str] = set()

    for t in tickers:
        if t in used:
            continue
        # Finde alle stark korrelierten Partner
        group = [t]
        for other in tickers:
            if other == t or other in used:
                continue
            # Muss mit allen bestehenden Gruppenmitgliedern korrelieren
            all_corr = all(
                corr_matrix.get(member, {}).get(other, 0.0) >= threshold
                for member in group
            )
            if all_corr:
                group.append(other)

        if len(group) >= 3:
            clusters.append(group)
            used.update(group)

    return clusters


def compute_parametric_var(
    positions: list[dict],
    corr_matrix: dict[str, dict[str, float]],
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> float:
    """
    Parametrischer VaR unter Nutzung der Korrelationsmatrix.

    Steps:
    1. Tägliche Volatilität pro Position aus Returns Std-Dev
    2. Kovarianz-Matrix = vol_i * vol_j * corr_ij
    3. Portfolio-Varianz = w^T * Cov * w
    4. VaR = portfolio_value * z_score * sqrt(variance) * sqrt(horizon)

    Returns: VaR in EUR (negativer Betrag = maximaler erwarteter Verlust)
    """
    z_scores = {0.95: 1.645, 0.99: 2.326}
    z = z_scores.get(confidence, 1.645)

    # Positionen mit Werten
    pos_with_values = []
    for p in positions:
        ticker = p.get('ticker', '').upper()
        val = (p.get('position_size_eur') or 0)
        if val <= 0:
            continue
        prices = _get_price_series(ticker, days=30)
        rets = _pct_returns(prices)
        if len(rets) < 5:
            continue
        vol = statistics.stdev(rets) if len(rets) > 1 else 0.02
        pos_with_values.append({'ticker': ticker, 'value': val, 'vol': vol})

    if not pos_with_values:
        return 0.0

    total = sum(p['value'] for p in pos_with_values)
    n = len(pos_with_values)

    # Portfolio-Varianz: Summe über alle Paare (i,j) von w_i * w_j * vol_i * vol_j * corr_ij
    port_var = 0.0
    for i in range(n):
        w_i = pos_with_values[i]['value'] / total
        v_i = pos_with_values[i]['vol']
        t_i = pos_with_values[i]['ticker']
        for j in range(n):
            w_j = pos_with_values[j]['value'] / total
            v_j = pos_with_values[j]['vol']
            t_j = pos_with_values[j]['ticker']
            if i == j:
                corr = 1.0
            else:
                corr = corr_matrix.get(t_i, {}).get(t_j, 0.0)
            port_var += w_i * w_j * v_i * v_j * corr

    port_vol = port_var ** 0.5 if port_var > 0 else 0.0
    var_eur = total * z * port_vol * (horizon_days ** 0.5)

    return round(-var_eur, 2)


def get_exposure_breakdown(positions: list[dict] | None = None) -> dict:
    """
    Phase 21: Vollständiges Exposure-Breakdown für Dashboard.

    Returns:
        {
            'by_sector': {sector: {'eur': float, 'pct': float, 'count': int}},
            'by_region': {region: {'eur': float, 'pct': float}},
            'by_currency': {currency: {'eur': float, 'pct': float}},
            'total_eur': float,
            'position_count': int,
        }
    """
    if positions is None:
        positions = _get_open_positions()

    total = sum((p.get('position_size_eur') or 0) for p in positions)
    if total <= 0:
        total = len(positions)  # Fallback

    # Sektor
    by_sector: dict[str, dict] = {}
    for p in positions:
        sector = get_sector(p.get('ticker', ''))
        val = (p.get('position_size_eur') or 0) or (total / len(positions) if positions else 0)
        if sector not in by_sector:
            by_sector[sector] = {'eur': 0.0, 'count': 0}
        by_sector[sector]['eur'] += val
        by_sector[sector]['count'] += 1

    for s in by_sector:
        by_sector[s]['pct'] = round(by_sector[s]['eur'] / total, 3) if total > 0 else 0

    # Region (basierend auf Ticker-Suffix)
    def _region(ticker: str) -> str:
        t = ticker.upper()
        if any(s in t for s in ['.DE', '.PA', '.AS', '.MI', '.BR']):
            return 'EU'
        if '.L' in t:
            return 'UK'
        if '.OL' in t or '.CO' in t or '.ST' in t:
            return 'Nordics'
        if '.T' in t:
            return 'Japan'
        if '.HK' in t:
            return 'China/HK'
        if '.AX' in t:
            return 'Australia'
        if '.TO' in t:
            return 'Canada'
        return 'US'

    by_region: dict[str, dict] = {}
    for p in positions:
        region = _region(p.get('ticker', ''))
        val = (p.get('position_size_eur') or 0) or (total / len(positions) if positions else 0)
        if region not in by_region:
            by_region[region] = {'eur': 0.0}
        by_region[region]['eur'] += val

    for r in by_region:
        by_region[r]['pct'] = round(by_region[r]['eur'] / total, 3) if total > 0 else 0

    # Währung
    def _currency(ticker: str) -> str:
        t = ticker.upper()
        if any(s in t for s in ['.DE', '.PA', '.AS', '.MI', '.BR']):
            return 'EUR'
        if '.L' in t:
            return 'GBP'
        if '.OL' in t:
            return 'NOK'
        if '.CO' in t:
            return 'DKK'
        if '.ST' in t:
            return 'SEK'
        if '.T' in t:
            return 'JPY'
        if '.HK' in t:
            return 'HKD'
        if '.AX' in t:
            return 'AUD'
        if '.TO' in t:
            return 'CAD'
        return 'USD'

    by_currency: dict[str, dict] = {}
    for p in positions:
        curr = _currency(p.get('ticker', ''))
        val = (p.get('position_size_eur') or 0) or (total / len(positions) if positions else 0)
        if curr not in by_currency:
            by_currency[curr] = {'eur': 0.0}
        by_currency[curr]['eur'] += val

    for c in by_currency:
        by_currency[c]['pct'] = round(by_currency[c]['eur'] / total, 3) if total > 0 else 0

    return {
        'by_sector': by_sector,
        'by_region': by_region,
        'by_currency': by_currency,
        'total_eur': round(total, 2),
        'position_count': len(positions),
    }


# ────────────────────────────────────────────────────────────────────────────
# Combined Risk Check — der eine Aufruf für paper_trade_engine.py
# ────────────────────────────────────────────────────────────────────────────

def run_all_risk_checks(
    ticker: str,
    strategy_id: str,
    base_size: float | None = None,
) -> dict:
    """
    Führt alle 5 Risk-Checks durch und gibt ein konsolidiertes Verdict zurück.

    Reihenfolge:
    1. Drawdown-Circuit (wenn aktiv → hart blockiert)
    2. Correlation / Sector Cluster
    3. Kelly-basierte Size-Berechnung
    4. VIX-Volatility-Adjustment
    5. Sector-Exposure-Check (mit finaler Size)

    Returns:
        {
            blocked: bool,
            blocked_by: str,  # 'drawdown' | 'correlation' | 'sector' | ''
            reason: str,
            final_size: float,
            details: {...}  # alle 5 Check-Ergebnisse
        }
    """
    ticker = ticker.upper()
    details: dict[str, Any] = {}

    # 1. Drawdown Circuit Breaker
    dd = check_drawdown_circuit()
    details['drawdown'] = dd
    if dd['blocked']:
        log.warning(f"BLOCKED[drawdown]: {ticker} — {dd['reason']}")
        return {
            'blocked': True,
            'blocked_by': 'drawdown_circuit',
            'reason': dd['reason'],
            'final_size': 0.0,
            'details': details,
        }

    # 2. Correlation / Cluster (Phase 21: mit size_factor)
    corr = check_correlation(ticker)
    details['correlation'] = corr
    corr_size_factor = corr.get('size_factor', 1.0)
    if corr['blocked']:
        log.warning(f"BLOCKED[correlation]: {ticker} — {corr['reason']}")
        return {
            'blocked': True,
            'blocked_by': 'correlation_cluster',
            'reason': corr['reason'],
            'final_size': 0.0,
            'size_factor': 0.0,
            'details': details,
        }

    # 3. Kelly Sizing
    kelly = kelly_position_size(strategy_id)
    details['kelly'] = kelly
    kelly_size = kelly['final_size']

    # 4. VIX Adjustment
    vol = volatility_adjusted_size(kelly_size)
    details['volatility'] = vol
    vol_size = vol['adjusted_size']

    # Phase 21: Korrelations-basierte Size-Reduktion anwenden
    corr_adjusted = vol_size * corr_size_factor
    if corr_size_factor < 1.0:
        log.info(f"Corr-Size-Adjust: {ticker} {vol_size:.0f}€ × {corr_size_factor} = {corr_adjusted:.0f}€")

    # Wenn base_size explizit mitgegeben wurde, nie über base_size hinausgehen
    final_size = min(corr_adjusted, base_size) if base_size else corr_adjusted
    # Niemals unter Min
    final_size = max(500.0, final_size)

    # 5. Sector Exposure
    sector = check_sector_exposure(ticker, final_size)
    details['sector'] = sector
    if sector['blocked']:
        log.warning(f"BLOCKED[sector]: {ticker} — {sector['reason']}")
        return {
            'blocked': True,
            'blocked_by': 'sector_exposure',
            'reason': sector['reason'],
            'final_size': 0.0,
            'details': details,
        }

    log.info(
        f"RISK_OK[{ticker}/{strategy_id}]: size={final_size:.0f}€ "
        f"kelly={kelly['method']} vol={vol['regime']}@{vol['multiplier']}x "
        f"sector={sector['sector']} corr={corr['max_correlation']}"
    )

    return {
        'blocked': False,
        'blocked_by': '',
        'reason': 'OK',
        'final_size': round(final_size, 2),
        'size_factor': corr_size_factor,
        'details': details,
    }


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker', default='OXY')
    parser.add_argument('--strategy', default='PS1')
    parser.add_argument('--snapshot', action='store_true', help='Zeige Portfolio-Risk-Snapshot')
    args = parser.parse_args()

    if args.snapshot:
        positions = _get_open_positions()
        fund = _get_fund_value()
        cash = _get_cash()
        vix = _get_vix()
        print("=" * 60)
        print(f"  Portfolio Risk Snapshot — {datetime.now(_BERLIN).strftime('%Y-%m-%d %H:%M')}")
        print("=" * 60)
        print(f"Fund Value:     {fund:,.0f}€")
        print(f"Cash:           {cash:,.0f}€")
        print(f"Open Positions: {len(positions)}")
        print(f"VIX:            {vix}")
        print()
        # Sektor-Breakdown
        sectors: dict[str, float] = {}
        for p in positions:
            s = get_sector(p.get('ticker', ''))
            sectors[s] = sectors.get(s, 0) + (p.get('position_size_eur') or 0)
        print("Sector Breakdown:")
        for s, v in sorted(sectors.items(), key=lambda x: -x[1]):
            pct = v / fund if fund > 0 else 0
            bar = '█' * int(pct * 40)
            print(f"  {s:15s} {v:7,.0f}€  {pct:5.1%}  {bar}")
        print()
        dd = check_drawdown_circuit()
        print(f"Drawdown Check: blocked={dd['blocked']} ({dd.get('reason') or 'OK'})")
    else:
        print(f"\nTesting full risk check: {args.ticker} / {args.strategy}\n")
        result = run_all_risk_checks(args.ticker, args.strategy)
        print(f"BLOCKED: {result['blocked']}")
        print(f"BY:      {result['blocked_by']}")
        print(f"REASON:  {result['reason']}")
        print(f"SIZE:    {result['final_size']}€")
        print("\nDetails:")
        for k, v in result['details'].items():
            print(f"  [{k}] {v}")
