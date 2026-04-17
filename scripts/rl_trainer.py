#!/usr/bin/env python3
"""
RL Trainer — Phase 8
====================
Trainingssteuerung, Evaluation und Status-Reports für den PPO-Agenten.

Usage:
  python3 rl_trainer.py                    # Status + Evaluation
  python3 rl_trainer.py --train 50000      # 50k Steps trainieren
  python3 rl_trainer.py --train 10000 --quick   # Schneller Test-Run
  python3 rl_trainer.py --eval 20          # 20 Episoden Evaluation
  python3 rl_trainer.py --status           # Nur Status
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import torch

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
CHECKPOINT_DIR = WS / 'data/rl_checkpoints'
BEST_MODEL_FILE = WS / 'data/rl_best_model.pt'
METRICS_FILE = WS / 'data/rl_metrics.json'


def status_report():
    """Gibt Trainings-Status aus."""
    print("\n" + "="*55)
    print("PPO Agent — Phase 8 Status")
    print("="*55)

    if not METRICS_FILE.exists():
        print("  ⏳ Noch kein Training durchgeführt")
        print("     Starte mit: python3 rl_trainer.py --train 10000")
        return

    m = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
    total_steps = m.get('total_steps', 0)
    total_eps = m.get('total_episodes', 0)
    best_reward = m.get('best_episode_reward', -999)

    print(f"  Gesamt-Steps:    {total_steps:,}")
    print(f"  Episoden:        {total_eps:,}")
    print(f"  Bester Reward:   {best_reward:.2f}")
    print(f"  Checkpoint:      {'✅ vorhanden' if BEST_MODEL_FILE.exists() else '❌ fehlt'}")

    # Training Progress
    history = m.get('training_history', [])
    if len(history) >= 3:
        recent = history[-10:]
        rewards = [h['avg_reward_20'] for h in recent]
        trend = rewards[-1] - rewards[0]
        print(f"\n  Trend (letzte 10 Updates): {trend:+.2f}")
        print(f"  Letzter Reward Ø20:        {rewards[-1]:.3f}")

        # Ascii-Plot
        min_r, max_r = min(rewards), max(rewards)
        r_range = max_r - min_r if max_r != min_r else 1
        print(f"\n  Reward-Verlauf (letzte {len(recent)} Updates):")
        for r in rewards:
            bar_len = int((r - min_r) / r_range * 30)
            bar = '█' * bar_len + '░' * (30 - bar_len)
            print(f"    {r:+.2f} {bar}")

    # Readiness Assessment
    print(f"\n  Readiness für Real-Money:")
    if total_steps < 50_000:
        needed = 50_000 - total_steps
        print(f"  ⏳ Noch {needed:,} Steps nötig (Ziel: 50k)")
    elif best_reward < 0:
        print(f"  🔴 Reward noch negativ — Agent lernt noch")
    elif best_reward < 2.0:
        print(f"  🟡 Agent zeigt Fortschritt, aber noch nicht stabil")
    else:
        print(f"  🟢 Agent zeigt positive Renditen — Evaluation empfohlen")

    print("="*55)


def run_training(total_steps: int = 50_000, quick: bool = False) -> dict:
    """Führt Training aus."""
    sys.path.insert(0, str(WS / 'scripts'))
    from rl_env import MultiTickerEnv
    from rl_agent import PPOTrainer

    print("[RL Trainer] Lade Umgebung...")
    env = MultiTickerEnv(seed=42)

    # Graceful Skip wenn keine Ticker-Envs geladen (price_cache leer / <200 Bars)
    if not getattr(env, 'envs', None):
        print("[RL Trainer] WARN: Keine Ticker-Envs geladen (price_cache leer). Skip.")
        return {'skipped': True, 'reason': 'no_envs'}

    print("[RL Trainer] Initialisiere PPO Agent...")
    trainer = PPOTrainer(resume=True)

    if quick:
        total_steps = min(total_steps, 10_000)
        print(f"[RL Trainer] Quick-Mode: {total_steps:,} Steps")

    result = trainer.train(env, total_steps=total_steps)

    print(f"\n✅ Training abgeschlossen:")
    print(f"   Steps: {result['steps_trained']:,}")
    print(f"   Episoden: {result['episodes']}")
    print(f"   Final Ø-Reward: {result['final_avg_reward']:.3f}")
    print(f"   Bester Reward: {result['best_reward']:.3f}")

    return result


def run_evaluation(n_episodes: int = 20) -> dict:
    """Führt Evaluation durch."""
    sys.path.insert(0, str(WS / 'scripts'))
    from rl_env import MultiTickerEnv
    from rl_agent import PPOTrainer

    if not BEST_MODEL_FILE.exists():
        print("❌ Kein Checkpoint — erst trainieren!")
        return {}

    env = MultiTickerEnv(seed=99)  # Anderer Seed als Training
    trainer = PPOTrainer(resume=True)

    print(f"[RL Eval] Evaluiere auf {n_episodes} Episoden...")
    result = trainer.evaluate(env, n_episodes=n_episodes)

    print(f"\n📊 Evaluierungs-Ergebnis:")
    print(f"   Ø Reward:        {result['mean_reward']:+.3f} ± {result['std_reward']:.3f}")
    print(f"   Ø Win-Rate:      {result['mean_win_rate']:.0%}")
    print(f"   Ø Trades/Ep:     {result['mean_trades_per_ep']:.1f}")
    print(f"   Bester Reward:   {result['best_reward']:+.3f}")

    # Interpretation
    wr = result['mean_win_rate']
    reward = result['mean_reward']
    if reward > 2.0 and wr > 0.55:
        verdict = "🟢 STRONG — Agent handelt profitabel"
    elif reward > 0 and wr > 0.50:
        verdict = "🟡 DEVELOPING — Leicht positiv, mehr Training nötig"
    elif reward > -1.0:
        verdict = "🟠 LEARNING — Noch keine konsistente Edge"
    else:
        verdict = "🔴 EARLY — Agent lernt noch grundlegende Patterns"

    print(f"\n   Verdict: {verdict}")

    # In Metrics speichern
    if METRICS_FILE.exists():
        metrics = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        metrics['last_eval'] = {**result, 'ts': datetime.now(timezone.utc).isoformat()[:16]}
        METRICS_FILE.write_text(json.dumps(metrics, indent=2))

    return result


def predict_action(ticker: str, features: dict | None = None) -> dict:
    """
    Lässt den Agenten eine Empfehlung für einen Ticker geben.
    Integration in das bestehende Trading-System.
    """
    sys.path.insert(0, str(WS / 'scripts'))
    from rl_env import TradingEnv, STATE_DIM
    from rl_agent import PPOTrainer, ActorCritic
    import torch

    if not BEST_MODEL_FILE.exists():
        return {'action': 'HOLD', 'confidence': 0, 'note': 'Kein Modell'}

    # Modell laden
    trainer = PPOTrainer(resume=True)
    m = json.loads(METRICS_FILE.read_text(encoding="utf-8")) if METRICS_FILE.exists() else {}

    # State aus Feature-Collector
    if features is None:
        try:
            from feature_collector import collect_features
            features = collect_features(ticker)
        except Exception:
            features = {}

    # State-Vektor bauen (normalisiert wie in rl_env.py)
    rsi = features.get('rsi_at_entry', 50.0) or 50.0
    vix = features.get('vix_at_entry', 22.0) or 22.0
    vol = min(features.get('volume_ratio', 1.0) or 1.0, 3.0)
    ma50 = features.get('ma50_distance', 0.0) or 0.0
    hmm = features.get('hmm_regime', 1.0) or 1.0

    state = np.array([
        rsi / 100.0,
        vol / 3.0,
        np.clip(ma50 / 0.3 + 0.5, 0, 1),
        0.025,      # ATR default
        0.5,        # SPY 5d neutral
        min(vix / 50.0, 1.0),
        hmm / 3.0,
        0.0,        # nicht im Trade
        0.0, 0.5, 0.0, 0.0,  # days_held, unrealized, heat, drawdown
    ], dtype=np.float32)

    with torch.no_grad():
        s = torch.FloatTensor(state).unsqueeze(0)
        logits, value = trainer.net(s)
        probs = torch.softmax(logits, dim=-1).squeeze()

    action_names = ['HOLD', 'ENTER_LONG', 'EXIT']
    best_action = int(torch.argmax(probs).item())
    confidence = float(probs[best_action].item())

    # Nur wenn Agent genug trainiert ist (>20k Steps) ernst nehmen
    total_steps = m.get('total_steps', 0)
    reliable = total_steps >= 20_000

    return {
        'action': action_names[best_action],
        'confidence': round(confidence, 3),
        'probabilities': {
            'HOLD': round(float(probs[0].item()), 3),
            'ENTER_LONG': round(float(probs[1].item()), 3),
            'EXIT': round(float(probs[2].item()), 3),
        },
        'state_value': round(float(value.item()), 3),
        'reliable': reliable,
        'total_steps_trained': total_steps,
        'note': '' if reliable else f'Noch {max(0, 20000-total_steps):,} Steps bis zuverlässig'
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    args = sys.argv[1:]

    if '--train' in args:
        idx = args.index('--train')
        try:
            steps = int(args[idx + 1]) if len(args) > idx + 1 else 50_000
        except ValueError:
            steps = 50_000
        quick = '--quick' in args
        run_training(steps, quick=quick)
        status_report()

    elif '--eval' in args:
        idx = args.index('--eval')
        try:
            n = int(args[idx + 1]) if len(args) > idx + 1 else 20
        except ValueError:
            n = 20
        run_evaluation(n)

    elif '--predict' in args:
        idx = args.index('--predict')
        ticker = args[idx + 1] if len(args) > idx + 1 else 'NVDA'
        result = predict_action(ticker)
        print(f"\nRL Agent Empfehlung: {ticker}")
        print(f"  Aktion:       {result['action']}")
        print(f"  Konfidenz:    {result['confidence']:.0%}")
        print(f"  HOLD/ENTER/EXIT: {result['probabilities']}")
        print(f"  State Value:  {result['state_value']:.3f}")
        if not result['reliable']:
            print(f"  ⚠️  {result['note']}")

    else:
        status_report()
        if '--train' not in args:
            print("\nStarte ersten Training-Run mit 20k Steps...")
