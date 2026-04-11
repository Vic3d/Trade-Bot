#!/usr/bin/env python3.14
"""
PPO Agent — Phase 8 des ML-Bauplans
=====================================
Proximal Policy Optimization (PPO) in reinem PyTorch.
Keine stable_baselines3 nötig.

Architektur:
  Actor-Critic Network:
    Input  → Linear(12, 64) → ReLU
           → Linear(64, 64) → ReLU
    Actor  → Linear(64, 3)  → Softmax  → P(action)
    Critic → Linear(64, 1)             → V(state)

PPO-Kerneigenschaften:
  - Clip-Ratio ε=0.2: verhindert zu große Policy-Updates
  - Entropy-Bonus: fördert Exploration
  - Value-Function Loss: stabilisiert den Critic
  - GAE (Generalized Advantage Estimation): reduziert Varianz

Persistenz:
  - Checkpoints in data/rl_checkpoints/
  - Bestes Modell: data/rl_best_model.pt
"""

import json
import math
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.distributions import Categorical

WS = Path('/data/.openclaw/workspace')
CHECKPOINT_DIR = WS / 'data/rl_checkpoints'
BEST_MODEL_FILE = WS / 'data/rl_best_model.pt'
METRICS_FILE = WS / 'data/rl_metrics.json'

STATE_DIM = 12
N_ACTIONS = 3

# PPO Hyperparameter
LR = 3e-4
GAMMA = 0.99          # Discount Factor
GAE_LAMBDA = 0.95     # GAE λ
CLIP_EPS = 0.2        # PPO Clip
ENTROPY_COEF = 0.01   # Exploration-Bonus
VALUE_COEF = 0.5      # Critic Loss Gewicht
MAX_GRAD_NORM = 0.5   # Gradient Clipping
N_EPOCHS = 4          # PPO Update Epochs pro Batch
BATCH_SIZE = 64
ROLLOUT_STEPS = 512   # Steps pro PPO-Update


# ── Actor-Critic Network ──────────────────────────────────────────────────────

class ActorCritic(nn.Module):
    """
    Shared-Backbone Actor-Critic.
    Gemeinsamer Feature-Extraktor → getrennte Actor/Critic Köpfe.
    """

    def __init__(self, state_dim: int = STATE_DIM, n_actions: int = N_ACTIONS,
                  hidden: int = 64):
        super().__init__()
        self.backbone = nn.Sequential(
            nn.Linear(state_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
        )
        self.actor = nn.Linear(hidden, n_actions)
        self.critic = nn.Linear(hidden, 1)

        # Orthogonal Initialization (PPO best practice)
        for layer in self.backbone:
            if isinstance(layer, nn.Linear):
                nn.init.orthogonal_(layer.weight, gain=math.sqrt(2))
                nn.init.constant_(layer.bias, 0)
        nn.init.orthogonal_(self.actor.weight, gain=0.01)
        nn.init.constant_(self.actor.bias, 0)
        nn.init.orthogonal_(self.critic.weight, gain=1.0)
        nn.init.constant_(self.critic.bias, 0)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        features = self.backbone(x)
        logits = self.actor(features)
        value = self.critic(features)
        return logits, value

    def get_action(self, state: np.ndarray) -> tuple[int, float, float]:
        """Wählt Aktion aus aktueller Policy."""
        with torch.no_grad():
            s = torch.FloatTensor(state).unsqueeze(0)
            logits, value = self(s)
            dist = Categorical(logits=logits)
            action = dist.sample()
            log_prob = dist.log_prob(action)
        return int(action.item()), float(log_prob.item()), float(value.item())

    def evaluate(self, states: torch.Tensor, actions: torch.Tensor
                 ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Evaluiert States/Actions für PPO-Update."""
        logits, values = self(states)
        dist = Categorical(logits=logits)
        log_probs = dist.log_prob(actions)
        entropy = dist.entropy()
        return log_probs, values.squeeze(), entropy


# ── PPO Trainer ───────────────────────────────────────────────────────────────

class PPOTrainer:
    """
    PPO-Training-Loop mit Rollout-Buffer und Checkpoint-Management.
    """

    def __init__(self, resume: bool = True):
        self.net = ActorCritic()
        self.optimizer = optim.Adam(self.net.parameters(), lr=LR)

        self.metrics = self._load_metrics()
        self.best_reward = self.metrics.get('best_episode_reward', -999)
        self.total_steps = self.metrics.get('total_steps', 0)
        self.episodes = self.metrics.get('total_episodes', 0)

        if resume and BEST_MODEL_FILE.exists():
            self.load(BEST_MODEL_FILE)
            print(f"  ✅ Checkpoint geladen: {self.total_steps:,} Steps, "
                  f"Best Reward: {self.best_reward:.2f}")
        else:
            print(f"  🆕 Neuer Agent initialisiert")

    def _load_metrics(self) -> dict:
        if METRICS_FILE.exists():
            return json.loads(METRICS_FILE.read_text())
        return {
            'total_steps': 0, 'total_episodes': 0, 'best_episode_reward': -999,
            'episode_history': [], 'training_history': [],
        }

    def save(self, path: Path):
        torch.save({
            'model_state': self.net.state_dict(),
            'optimizer_state': self.optimizer.state_dict(),
            'total_steps': self.total_steps,
            'best_reward': self.best_reward,
            'episodes': self.episodes,
        }, path)

    def load(self, path: Path):
        checkpoint = torch.load(path, map_location='cpu', weights_only=False)
        self.net.load_state_dict(checkpoint['model_state'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state'])
        self.total_steps = checkpoint.get('total_steps', 0)
        self.best_reward = checkpoint.get('best_reward', -999)
        self.episodes = checkpoint.get('episodes', 0)

    # ── Rollout ───────────────────────────────────────────────────────────────

    def collect_rollout(self, env, n_steps: int = ROLLOUT_STEPS) -> dict:
        """
        Sammelt n_steps Erfahrungen in der Umgebung.
        Returns: Buffer mit States, Actions, Rewards, etc.
        """
        states, actions, log_probs, rewards, values, dones = [], [], [], [], [], []
        episode_rewards = []
        current_episode_reward = 0.0

        state = env.reset()

        for _ in range(n_steps):
            action, log_prob, value = self.net.get_action(state)
            next_state, reward, done, info = env.step(action)

            states.append(state)
            actions.append(action)
            log_probs.append(log_prob)
            rewards.append(reward)
            values.append(value)
            dones.append(float(done))

            current_episode_reward += reward
            state = next_state

            if done:
                episode_rewards.append(current_episode_reward)
                current_episode_reward = 0.0
                state = env.reset()

        # Last value für GAE
        _, last_value = self.net.backbone(torch.FloatTensor(state).unsqueeze(0)), 0.0
        with torch.no_grad():
            _, lv = self.net(torch.FloatTensor(state).unsqueeze(0))
            last_value = float(lv.item())

        # GAE berechnen
        advantages = self._compute_gae(rewards, values, dones, last_value)
        returns = [a + v for a, v in zip(advantages, values)]

        return {
            'states': torch.FloatTensor(np.array(states)),
            'actions': torch.LongTensor(actions),
            'log_probs': torch.FloatTensor(log_probs),
            'returns': torch.FloatTensor(returns),
            'advantages': torch.FloatTensor(advantages),
            'episode_rewards': episode_rewards,
        }

    def _compute_gae(self, rewards, values, dones, last_value) -> list[float]:
        """Generalized Advantage Estimation."""
        advantages = []
        gae = 0.0
        next_value = last_value

        for r, v, d in zip(reversed(rewards), reversed(values), reversed(dones)):
            delta = r + GAMMA * next_value * (1 - d) - v
            gae = delta + GAMMA * GAE_LAMBDA * (1 - d) * gae
            advantages.insert(0, gae)
            next_value = v

        return advantages

    # ── PPO Update ────────────────────────────────────────────────────────────

    def update(self, buffer: dict) -> dict:
        """
        PPO Policy Update auf gesammeltem Rollout-Buffer.
        Returns: Loss-Statistiken
        """
        states = buffer['states']
        actions = buffer['actions']
        old_log_probs = buffer['log_probs']
        returns = buffer['returns']
        advantages = buffer['advantages']

        # Normalize advantages
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        n_updates = 0

        for _ in range(N_EPOCHS):
            # Mini-Batch Shuffling
            indices = torch.randperm(len(states))
            for start in range(0, len(states), BATCH_SIZE):
                batch_idx = indices[start:start + BATCH_SIZE]
                if len(batch_idx) < 8:
                    continue

                b_states = states[batch_idx]
                b_actions = actions[batch_idx]
                b_old_log_probs = old_log_probs[batch_idx]
                b_returns = returns[batch_idx]
                b_advantages = advantages[batch_idx]

                # Neue Log-Probs + Values
                new_log_probs, new_values, entropy = self.net.evaluate(b_states, b_actions)

                # PPO Clip Loss
                ratio = torch.exp(new_log_probs - b_old_log_probs)
                surr1 = ratio * b_advantages
                surr2 = torch.clamp(ratio, 1 - CLIP_EPS, 1 + CLIP_EPS) * b_advantages
                policy_loss = -torch.min(surr1, surr2).mean()

                # Value Loss
                value_loss = nn.MSELoss()(new_values, b_returns)

                # Total Loss
                loss = policy_loss + VALUE_COEF * value_loss - ENTROPY_COEF * entropy.mean()

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.net.parameters(), MAX_GRAD_NORM)
                self.optimizer.step()

                total_policy_loss += float(policy_loss.item())
                total_value_loss += float(value_loss.item())
                total_entropy += float(entropy.mean().item())
                n_updates += 1

        n = max(n_updates, 1)
        return {
            'policy_loss': round(total_policy_loss / n, 4),
            'value_loss': round(total_value_loss / n, 4),
            'entropy': round(total_entropy / n, 4),
        }

    # ── Training Loop ─────────────────────────────────────────────────────────

    def train(self, env, total_steps: int = 50_000,
               report_every: int = 5_000) -> dict:
        """
        Haupt-Training-Loop.
        Läuft total_steps Schritte und speichert regelmäßig Checkpoints.
        """
        print(f"\n[PPO Training] Start: {total_steps:,} Steps")
        print(f"  Bereits trainiert: {self.total_steps:,} Steps\n")

        steps_done = 0
        all_episode_rewards = []

        while steps_done < total_steps:
            # Rollout sammeln
            buffer = self.collect_rollout(env, n_steps=min(ROLLOUT_STEPS, total_steps - steps_done))
            episode_rewards = buffer.pop('episode_rewards')
            all_episode_rewards.extend(episode_rewards)

            # PPO Update
            losses = self.update(buffer)

            steps_done += ROLLOUT_STEPS
            self.total_steps += ROLLOUT_STEPS
            self.episodes += len(episode_rewards)

            # Reporting
            if steps_done % report_every < ROLLOUT_STEPS:
                avg_reward = np.mean(all_episode_rewards[-20:]) if all_episode_rewards else 0
                print(f"  [{steps_done:6,}/{total_steps:,}] "
                      f"Ep-Reward: {avg_reward:+.2f} | "
                      f"PLoss: {losses['policy_loss']:.4f} | "
                      f"VLoss: {losses['value_loss']:.4f} | "
                      f"Entropy: {losses['entropy']:.3f}")

                # Checkpoint bei bestem Reward
                if avg_reward > self.best_reward:
                    self.best_reward = avg_reward
                    self.save(BEST_MODEL_FILE)
                    print(f"  ✅ Neuer Best: {self.best_reward:.2f} → gespeichert")

                # Training History updaten
                self.metrics['training_history'].append({
                    'total_steps': self.total_steps,
                    'avg_reward_20': round(float(avg_reward), 3),
                    'policy_loss': losses['policy_loss'],
                    'entropy': losses['entropy'],
                    'ts': datetime.now(timezone.utc).isoformat()[:10],
                })
                self.metrics['training_history'] = self.metrics['training_history'][-200:]

        # Finales Speichern
        self.save(CHECKPOINT_DIR / f"checkpoint_{self.total_steps:08d}.pt")
        final_avg = np.mean(all_episode_rewards[-50:]) if all_episode_rewards else 0.0
        self.metrics['total_steps'] = self.total_steps
        self.metrics['total_episodes'] = self.episodes
        self.metrics['best_episode_reward'] = self.best_reward
        METRICS_FILE.write_text(json.dumps(self.metrics, indent=2))

        return {
            'steps_trained': steps_done,
            'episodes': len(all_episode_rewards),
            'final_avg_reward': round(float(final_avg), 3),
            'best_reward': round(self.best_reward, 3),
        }

    # ── Evaluation ────────────────────────────────────────────────────────────

    def evaluate(self, env, n_episodes: int = 20) -> dict:
        """
        Evaluiert aktuellen Agenten deterministisch (ohne Exploration).
        """
        results = []
        for _ in range(n_episodes):
            state = env.reset()
            total_reward = 0.0
            done = False
            while not done:
                with torch.no_grad():
                    s = torch.FloatTensor(state).unsqueeze(0)
                    logits, _ = self.net(s)
                    action = int(torch.argmax(logits).item())  # Greedy
                state, reward, done, _ = env.step(action)
                total_reward += reward

            stats = env.current_env.episode_stats if hasattr(env, 'current_env') else {}
            results.append({'reward': total_reward, **stats})

        rewards = [r['reward'] for r in results]
        wrs = [r.get('win_rate', 0) for r in results if r.get('n_trades', 0) > 0]
        ns = [r.get('n_trades', 0) for r in results]

        return {
            'n_episodes': n_episodes,
            'mean_reward': round(float(np.mean(rewards)), 3),
            'std_reward': round(float(np.std(rewards)), 3),
            'mean_win_rate': round(float(np.mean(wrs)), 3) if wrs else 0,
            'mean_trades_per_ep': round(float(np.mean(ns)), 1),
            'best_reward': round(float(max(rewards)), 3),
        }
