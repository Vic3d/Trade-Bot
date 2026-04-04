#!/usr/bin/env python3.13
"""
RL Trading Environment — Phase 8 des ML-Bauplans
=================================================
Simulierte Trading-Umgebung ohne gymnasium-Abhängigkeit.
Kompatibel mit Standard gym-Interface: reset() / step().

State (12 Dimensionen):
  0: RSI(14) normalisiert [0–1]
  1: Volume-Ratio [0–3, clipped]
  2: MA50-Distanz [%] normalisiert
  3: ATR% normalisiert
  4: SPY 5d Return normalisiert
  5: VIX normalisiert [0–1]
  6: HMM-Regime [0–3, normalisiert]
  7: Position gehalten (0=kein, 1=long)
  8: Tage im Trade normalisiert [0–1, max 21]
  9: Unrealisierter PnL % normalisiert
  10: Portfolio Heat [0–1, Anzahl offener Positionen/max]
  11: Drawdown seit Peak normalisiert

Actions (diskret):
  0: HOLD       — nichts tun
  1: ENTER_LONG — long kaufen (wenn nicht im Trade)
  2: EXIT       — Position schließen (wenn im Trade)

Reward-Funktion:
  r = daily_pnl_pct * 10          # Tages-Return
    - 0.001 * hold_penalty         # leichter Druck zum Handeln
    - overtrading_penalty          # >3 Trades in 10 Tagen = -0.5
    + sharpe_bonus                 # Belohnung für gute Sharpe
    - drawdown_penalty             # Max-DD Strafe
"""

import json
import math
import random
from pathlib import Path
from datetime import datetime

import numpy as np

WS = Path('/data/.openclaw/workspace')
CACHE = WS / 'data/price_cache'

STATE_DIM = 12
N_ACTIONS = 3

# Hyperparameter
MAX_HOLD_DAYS = 21
STOP_LOSS_PCT = 0.07        # 7% Stop
TAKE_PROFIT_PCT = 0.14      # 14% Target (CRV 2:1)
TRANSACTION_COST = 0.001    # 0.1% pro Trade (Trade Republic ~0.1%)


class TradingEnv:
    """
    Simulierte Trading-Umgebung für einen einzelnen Ticker.
    """

    def __init__(self, ticker: str, vix_data: dict | None = None,
                  spy_data: dict | None = None, seed: int | None = None):
        self.ticker = ticker
        self.vix_data = vix_data or {}
        self.spy_data = spy_data or {}
        self.rng = random.Random(seed)

        # Lade Preisdaten
        self.bars = self._load_bars(ticker)
        self.dates = sorted(self.bars.keys())
        self.closes = np.array([self.bars[d]['c'] for d in self.dates])
        self.volumes = np.array([self.bars[d].get('v', 1e6) for d in self.dates])

        # Pre-berechne Indikatoren
        self.rsi = self._calc_rsi(self.closes, 14)
        self.ma50 = self._calc_ma(self.closes, 50)
        self.atr = self._calc_atr(self.closes, 14)
        self.avg_vol = self._calc_ma(self.volumes.astype(float), 20)

        # VIX aus Cache
        self.vix_series = self._load_vix()
        self.spy_series = self._load_spy()

        # Episode-State
        self.pos = 0                  # Position (Shares)
        self.entry_price = 0.0
        self.entry_date_idx = 0
        self.current_idx = 50         # Start nach Indikator-Warmup
        self.done = False
        self.episode_trades = []
        self.peak_value = 1.0
        self.portfolio_value = 1.0    # Normalisiert auf 1.0
        self.trade_history = []       # Für Sharpe-Berechnung

    def _load_bars(self, ticker: str) -> dict:
        f = CACHE / f"{ticker.replace('/', '_').replace('^', 'IX')}.json"
        if not f.exists():
            raise FileNotFoundError(f"Kein Cache für {ticker}")
        return json.loads(f.read_text())

    def _load_vix(self) -> dict:
        f = CACHE / 'IXVIX.json'
        return json.loads(f.read_text()) if f.exists() else {}

    def _load_spy(self) -> dict:
        f = CACHE / 'SPY.json'
        return json.loads(f.read_text()) if f.exists() else {}

    @staticmethod
    def _calc_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
        rsi = np.full(len(closes), 50.0)
        if len(closes) <= period:
            return rsi
        deltas = np.diff(closes)
        gains = np.maximum(deltas, 0)
        losses = np.maximum(-deltas, 0)
        avg_g = np.mean(gains[:period])
        avg_l = np.mean(losses[:period])
        for i in range(period, len(closes) - 1):
            avg_g = (avg_g * (period - 1) + gains[i]) / period
            avg_l = (avg_l * (period - 1) + losses[i]) / period
            rs = avg_g / avg_l if avg_l > 0 else 100
            rsi[i + 1] = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def _calc_ma(arr: np.ndarray, period: int) -> np.ndarray:
        ma = np.full(len(arr), arr[0])
        for i in range(period, len(arr)):
            ma[i] = np.mean(arr[i - period:i])
        return ma

    @staticmethod
    def _calc_atr(closes: np.ndarray, period: int = 14) -> np.ndarray:
        atr = np.full(len(closes), 0.02)
        if len(closes) <= 1:
            return atr
        tr = np.abs(np.diff(closes)) / closes[:-1]
        for i in range(period, len(closes)):
            atr[i] = np.mean(tr[max(0, i - period):i])
        return atr

    # ── State ─────────────────────────────────────────────────────────────────

    def _get_state(self) -> np.ndarray:
        i = self.current_idx
        c = self.closes[i]
        date = self.dates[i]

        # VIX
        vix_val = self.vix_series.get(date, {}).get('c', 20.0)
        vix_norm = min(vix_val / 50.0, 1.0)

        # SPY 5d Return
        spy_5d = 0.0
        if i >= 5 and date in self.spy_series:
            dates_before = self.dates[i - 5]
            spy_now = self.spy_series.get(date, {}).get('c', 0)
            spy_old = self.spy_series.get(dates_before, {}).get('c', 0)
            if spy_old > 0:
                spy_5d = (spy_now - spy_old) / spy_old

        # HMM-Regime (vereinfacht: VIX-basiert, solange HMM nicht live)
        hmm_regime = 0.0 if vix_val < 16 else (1.0 if vix_val < 20 else (2.0 if vix_val < 27 else 3.0))
        hmm_norm = hmm_regime / 3.0

        # MA50-Distanz
        ma50 = self.ma50[i]
        ma50_dist = (c - ma50) / ma50 if ma50 > 0 else 0.0
        ma50_norm = np.clip(ma50_dist / 0.3 + 0.5, 0, 1)  # [-30%, +30%] → [0, 1]

        # Volume-Ratio
        avg_vol = self.avg_vol[i]
        vol_ratio = min(self.volumes[i] / avg_vol if avg_vol > 0 else 1.0, 3.0)
        vol_norm = vol_ratio / 3.0

        # Trade-State
        in_pos = float(self.pos > 0)
        days_held = 0.0
        unrealized = 0.0
        if self.pos > 0 and self.entry_price > 0:
            days_held = min((i - self.entry_date_idx) / MAX_HOLD_DAYS, 1.0)
            unrealized = np.clip((c - self.entry_price) / self.entry_price, -0.2, 0.2) / 0.2 + 0.5

        # Portfolio Health
        portfolio_heat = min(len(self.episode_trades) / 10.0, 1.0)
        drawdown = max(0, (self.peak_value - self.portfolio_value) / self.peak_value)

        return np.array([
            self.rsi[i] / 100.0,   # RSI normalisiert
            vol_norm,               # Volume-Ratio
            ma50_norm,              # MA50-Distanz
            min(self.atr[i] * 100, 0.1) / 0.1,  # ATR%
            np.clip(spy_5d / 0.1 + 0.5, 0, 1),   # SPY 5d
            vix_norm,               # VIX
            hmm_norm,               # Regime
            in_pos,                 # Im Trade?
            days_held,              # Wie lange im Trade
            unrealized,             # Unrealisierter PnL
            portfolio_heat,         # Portfolio-Auslastung
            min(drawdown, 0.3) / 0.3,  # Drawdown
        ], dtype=np.float32)

    # ── Step ──────────────────────────────────────────────────────────────────

    def step(self, action: int) -> tuple[np.ndarray, float, bool, dict]:
        """
        Führt eine Aktion aus.
        Returns: (next_state, reward, done, info)
        """
        i = self.current_idx
        c = self.closes[i]
        reward = 0.0
        info = {'action': action, 'ticker': self.ticker, 'date': self.dates[i]}

        # ── Action ausführen ──
        if action == 1 and self.pos == 0:  # ENTER
            self.pos = 1
            self.entry_price = c * (1 + TRANSACTION_COST)
            self.entry_date_idx = i
            reward -= TRANSACTION_COST * 10  # Kleine Entry-Kosten
            info['event'] = 'ENTER'

        elif action == 2 and self.pos > 0:  # EXIT
            pnl_pct = (c * (1 - TRANSACTION_COST) - self.entry_price) / self.entry_price
            reward += pnl_pct * 10  # Haupt-Reward
            self.portfolio_value *= (1 + pnl_pct)
            self.peak_value = max(self.peak_value, self.portfolio_value)
            self.episode_trades.append(pnl_pct)
            self.trade_history.append(pnl_pct)
            self.pos = 0
            self.entry_price = 0.0
            info['event'] = 'EXIT'
            info['pnl_pct'] = round(pnl_pct, 4)

        elif action == 0:  # HOLD
            if self.pos > 0:
                # Sehr kleiner fester Hold-Penalty (nicht eskalierend)
                reward -= 0.002
            else:
                # Kein Trade = kleiner Opportunity-Cost
                reward -= 0.0005

        # ── Auto-Stop/Target/Time-Exit ──
        if self.pos > 0:
            pnl_pct = (c - self.entry_price) / self.entry_price
            days_held = i - self.entry_date_idx

            if pnl_pct <= -STOP_LOSS_PCT:
                reward += pnl_pct * 5   # Reduzierte Stop-Strafe
                self.portfolio_value *= (1 + pnl_pct - TRANSACTION_COST)
                self.episode_trades.append(pnl_pct)
                self.pos = 0
                reward -= 0.3   # Kleinere feste Stop-Strafe
                info['event'] = 'STOP_OUT'
            elif pnl_pct >= TAKE_PROFIT_PCT:
                reward += pnl_pct * 10 + 0.5  # Kleiner Bonus für Ziel erreicht
                self.portfolio_value *= (1 + pnl_pct - TRANSACTION_COST)
                self.episode_trades.append(pnl_pct)
                self.pos = 0
                info['event'] = 'TARGET_HIT'
            elif days_held >= MAX_HOLD_DAYS:
                reward += pnl_pct * 10
                self.portfolio_value *= (1 + pnl_pct - TRANSACTION_COST)
                self.episode_trades.append(pnl_pct)
                self.pos = 0
                info['event'] = 'TIME_EXIT'

        # ── Drawdown-Strafe ──
        if self.portfolio_value < self.peak_value * 0.85:
            reward -= 0.2  # Starke Drawdown-Strafe

        # ── Sharpe-Bonus (am Episoden-Ende) ──
        self.current_idx += 1
        if self.current_idx >= len(self.dates) - 1:
            self.done = True
            if len(self.episode_trades) >= 3:
                sharpe = self._calc_sharpe(self.episode_trades)
                reward += sharpe * 0.5

        next_state = self._get_state() if not self.done else np.zeros(STATE_DIM, dtype=np.float32)
        return next_state, float(reward), self.done, info

    def _calc_sharpe(self, returns: list[float], risk_free: float = 0.0) -> float:
        if len(returns) < 2:
            return 0.0
        arr = np.array(returns)
        excess = arr - risk_free
        std = np.std(excess)
        return float(np.mean(excess) / std) if std > 0 else 0.0

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self, start_idx: int | None = None) -> np.ndarray:
        """Startet neue Episode. Random Start wenn start_idx=None."""
        max_start = len(self.dates) - MAX_HOLD_DAYS - 10
        if start_idx is not None:
            self.current_idx = max(50, min(start_idx, max_start))
        else:
            self.current_idx = self.rng.randint(50, max(51, max_start))

        self.pos = 0
        self.entry_price = 0.0
        self.entry_date_idx = 0
        self.done = False
        self.episode_trades = []
        self.peak_value = 1.0
        self.portfolio_value = 1.0
        return self._get_state()

    @property
    def episode_stats(self) -> dict:
        trades = self.episode_trades
        if not trades:
            return {'n_trades': 0, 'win_rate': 0, 'total_return': 0, 'sharpe': 0}
        wins = sum(1 for t in trades if t > 0)
        return {
            'n_trades': len(trades),
            'win_rate': round(wins / len(trades), 3),
            'total_return': round(sum(trades), 4),
            'sharpe': round(self._calc_sharpe(trades), 3),
            'portfolio_value': round(self.portfolio_value, 4),
        }


class MultiTickerEnv:
    """
    Wechselt zwischen mehreren Tickers während des Trainings.
    Gibt dem Agenten Exposure zu verschiedenen Marktbedingungen.
    """
    TICKERS = ['NVDA', 'PLTR', 'MSFT', 'OXY', 'EQNR', 'FRO', 'DHT',
               'MOS', 'HL', 'PAAS', 'KTOS', 'HII', 'RHM.DE', 'HAG.DE', 'TTE.PA']

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self.envs = {}
        self._load_envs()
        self.current_env = None
        self.total_steps = 0
        self.episode_count = 0

    def _load_envs(self):
        """Lädt alle verfügbaren Ticker-Umgebungen."""
        for ticker in self.TICKERS:
            f = CACHE / f"{ticker.replace('/', '_').replace('^', 'IX')}.json"
            if f.exists():
                try:
                    env = TradingEnv(ticker, seed=self.seed)
                    if len(env.dates) >= 200:
                        self.envs[ticker] = env
                except Exception:
                    pass
        print(f"  MultiTickerEnv: {len(self.envs)} Tickers geladen")

    def reset(self) -> np.ndarray:
        """Wählt zufälligen Ticker + zufälligen Start."""
        ticker = self.rng.choice(list(self.envs.keys()))
        self.current_env = self.envs[ticker]
        self.episode_count += 1
        return self.current_env.reset()

    def step(self, action: int) -> tuple[np.ndarray, float, bool, dict]:
        result = self.current_env.step(action)
        self.total_steps += 1
        return result

    @property
    def ticker(self) -> str:
        return self.current_env.ticker if self.current_env else '?'
