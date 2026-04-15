#!/usr/bin/env python3
"""
Portfolio Risk Management 2.0 — Phase 9

Pro-Level Risiko-Checks die das Portfolio vor Cluster-Risiken,
Drawdown-Spiralen und schlecht dimensionierten Positionen schützen.

5 Checks:
1. check_correlation()        — Cluster-Risiko (z.B. 3x Öl = 1 Bet)
2. kelly_position_size()      — Dynamische Kelly-basierte Größe
3. volatility_adjusted_size() — VIX-skalierte Positionsgröße
4. check_sector_exposure()    — Max 30% pro Sektor
5. check_drawdown_circuit()   — -5% in 7 Tagen → Pause

Alle Funktionen sind defensiv: bei fehlenden Daten → graceful degradation,
keine Blockade von Trades (better safe: loggen, nicht blockieren wenn Daten fehlen).

Integration:
    from scripts.portfolio_risk import run_all_risk_checks
    risk = run_all_risk_checks(ticker='OXY', strategy_id='PS1', base_size=1500)
    if risk['blocked']:
        return {'success': False, 'blocked_by': risk['blocked_by'], 'reason': risk['reason']}
    final_size = risk['final_size']
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import statistics
from datetime import datetime, date, timedelta
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
    """Alle aktuell offenen Paper-Trades."""
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT ticker, strategy, entry_price, shares, position_size_eur, entry_date "
            "FROM trades WHERE status='OPEN'"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error(f"_get_open_positions: {e}")
        return []


def _get_cash() -> float:
    """Aktueller Cash-Wert aus paper_fund."""
    try:
        conn = _db()
        row = conn.execute("SELECT value FROM paper_fund WHERE key='cash'").fetchone()
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
    threshold: float = 0.70,
    max_correlated: int = 2,
) -> dict:
    """
    Prüft ob neue Position zu stark mit bestehenden korreliert.

    Logik:
    - Wenn >= `max_correlated` bestehende Positionen Korrelation > threshold
      zum neuen Ticker haben → BLOCK (Cluster-Risiko)
    - Wenn 1 Position hoch korreliert → WARNING (nicht blockiert)

    Args:
        new_ticker: Neuer Ticker der gekauft werden soll
        threshold: Korrelations-Schwelle (default 0.70)
        max_correlated: Ab wie vielen hoch-korrelierten Positionen blockiert wird

    Returns:
        {blocked, reason, max_correlation, correlated_with: [(ticker, corr)]}
    """
    positions = _get_open_positions()
    if not positions:
        return {'blocked': False, 'reason': '', 'max_correlation': 0.0, 'correlated_with': []}

    new_prices = _get_price_series(new_ticker, days=30)
    if len(new_prices) < 15:
        # Zu wenig Historie für robuste Korrelation → skip
        log.info(f"Korrelation skipped: {new_ticker} hat nur {len(new_prices)} Kurse")
        return {
            'blocked': False,
            'reason': 'insufficient_history',
            'max_correlation': 0.0,
            'correlated_with': [],
        }

    new_rets = _pct_returns(new_prices)
    correlated: list[tuple[str, float]] = []
    max_corr = 0.0

    for pos in positions:
        pos_ticker = pos.get('ticker', '')
        if not pos_ticker or pos_ticker.upper() == new_ticker.upper():
            continue
        pos_prices = _get_price_series(pos_ticker, days=30)
        if len(pos_prices) < 15:
            continue
        pos_rets = _pct_returns(pos_prices)
        # Auf gleiche Länge kürzen
        n = min(len(new_rets), len(pos_rets))
        if n < 10:
            continue
        corr = _pearson(new_rets[-n:], pos_rets[-n:])
        if corr is None:
            continue
        if abs(corr) > abs(max_corr):
            max_corr = corr
        if corr >= threshold:
            correlated.append((pos_ticker, round(corr, 3)))

    # Auch Sektor-basierter Fallback: wenn 2+ Positionen im selben Sektor sind,
    # gilt automatisch als korreliert (egal was die Preise sagen)
    new_sector = get_sector(new_ticker)
    same_sector_count = sum(
        1 for p in positions if get_sector(p.get('ticker', '')) == new_sector and new_sector != 'unknown'
    )

    if len(correlated) >= max_correlated:
        return {
            'blocked': True,
            'reason': f'CLUSTER_RISK: {len(correlated)} existing positions correlate > {threshold}',
            'max_correlation': round(max_corr, 3),
            'correlated_with': correlated,
        }

    if same_sector_count >= max_correlated:
        return {
            'blocked': True,
            'reason': f'SECTOR_CLUSTER: {same_sector_count} positions already in sector "{new_sector}"',
            'max_correlation': round(max_corr, 3),
            'correlated_with': correlated,
        }

    return {
        'blocked': False,
        'reason': '',
        'max_correlation': round(max_corr, 3),
        'correlated_with': correlated,
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
            "SELECT pnl_eur FROM trades WHERE strategy=? AND status='CLOSED' AND pnl_eur IS NOT NULL",
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
    now = datetime.now()

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

    # 2. Correlation / Cluster
    corr = check_correlation(ticker)
    details['correlation'] = corr
    if corr['blocked']:
        log.warning(f"BLOCKED[correlation]: {ticker} — {corr['reason']}")
        return {
            'blocked': True,
            'blocked_by': 'correlation_cluster',
            'reason': corr['reason'],
            'final_size': 0.0,
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

    # Wenn base_size explizit mitgegeben wurde, nie über base_size hinausgehen
    final_size = min(vol_size, base_size) if base_size else vol_size
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
        print(f"  Portfolio Risk Snapshot — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
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
