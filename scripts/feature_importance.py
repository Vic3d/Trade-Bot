#!/usr/bin/env python3
"""
Feature Importance — Phase 6 des ML-Bauplans
=============================================
Beantwortet: Welche Features sind wirklich wichtig?
Welche kann man weglassen? Was ist Rauschen?

Methoden:
  1. Permutation Importance  — Feature zufällig mischen → Accuracy-Drop messen
  2. Spearman-Korrelation    — Feature vs. Outcome (monotone Beziehung)
  3. Mutual Information      — nicht-lineare Abhängigkeit
  4. Feature-Verteilung      — WIN vs. LOSS Verteilung vergleichen (KS-Test)

Datenquellen (automatische Auswahl):
  - ≥50 echte Trades mit Features → Real-Mode (Priorität)
  - <50 echte → Bootstrap-Mode (622 Backtest-Trades, klar markiert)

Output:
  - data/feature_importance.json  — Ergebnisse für andere Skripte
  - Terminal-Report               — für Discord/Logs
  - Empfehlungen                  — welche Features stark/schwach/redundant sind

Usage:
  python3 feature_importance.py              # Standard-Run
  python3 feature_importance.py --real-only  # Nur echte Trades (evtl. zu wenig)
  python3 feature_importance.py --bootstrap  # Explizit Backtest-Daten
  python3 feature_importance.py --quick      # Nur Top-Features, kein Plot
"""

import json
import pickle
import random
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
from scipy import stats

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'
MODEL_FILE = WS / 'data/river_model.pkl'
BOOTSTRAP_FILE = WS / 'data/bootstrap_samples.json'
OUTPUT_FILE = WS / 'data/feature_importance.json'

FEATURES = [
    'rsi_at_entry',
    'volume_ratio',
    'vix_at_entry',
    'atr_pct_at_entry',
    'ma50_distance',
    'day_of_week',
    'sector_momentum',
    'spy_5d_return',
    'hmm_regime',
]

FEATURE_LABELS = {
    'rsi_at_entry':     'RSI(14)',
    'volume_ratio':     'Volume-Ratio',
    'vix_at_entry':     'VIX',
    'atr_pct_at_entry': 'ATR%',
    'ma50_distance':    'MA50-Distanz',
    'day_of_week':      'Wochentag',
    'sector_momentum':  'Sektor-Momentum',
    'spy_5d_return':    'SPY 5d Return',
    'hmm_regime':       'HMM-Regime',
}


# ── Daten laden ───────────────────────────────────────────────────────────────

def load_real_trades() -> tuple[list, str]:
    """Lädt echte abgeschlossene Trades mit Features aus DB."""
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, pnl_eur,
               rsi_at_entry, volume_ratio, vix_at_entry, atr_pct_at_entry,
               ma50_distance, day_of_week, sector_momentum, spy_5d_return,
               hmm_regime
        FROM paper_portfolio
        WHERE status IN ('WIN', 'CLOSED', 'LOSS')
          AND rsi_at_entry IS NOT NULL
          AND pnl_eur IS NOT NULL
        ORDER BY close_date DESC
    """).fetchall()
    conn.close()

    samples = []
    for r in rows:
        features = {feat: (float(r[feat]) if r[feat] is not None else None) for feat in FEATURES}
        outcome = 1 if (r['pnl_eur'] or 0) > 0 else 0
        samples.append({'features': features, 'outcome': outcome, 'source': 'real'})

    return samples, 'real'


def load_bootstrap_samples() -> tuple[list, str]:
    """Lädt Backtest-Bootstrap-Samples als Fallback."""
    if not BOOTSTRAP_FILE.exists():
        return [], 'none'
    data = json.loads(BOOTSTRAP_FILE.read_text(encoding="utf-8"))
    return data, 'bootstrap'


def get_samples(force_bootstrap: bool = False, real_only: bool = False) -> tuple[list, str]:
    """Automatische Datenquell-Auswahl."""
    real_samples, _ = load_real_trades()

    if real_only:
        return real_samples, 'real'

    if force_bootstrap or len(real_samples) < 50:
        bootstrap, src = load_bootstrap_samples()
        if len(real_samples) > 0:
            # Real-Trades an Bootstrap dranhalten (echte Daten priorisiert)
            combined = bootstrap + real_samples
            return combined, f'mixed({len(real_samples)} real + {len(bootstrap)} bootstrap)'
        return bootstrap, f'bootstrap({len(bootstrap)} samples)'

    return real_samples, f'real({len(real_samples)} trades)'


def to_arrays(samples: list) -> tuple[np.ndarray, np.ndarray]:
    """Konvertiert Sample-Liste in Feature-Matrix + Label-Vektor."""
    X = np.zeros((len(samples), len(FEATURES)))
    y = np.zeros(len(samples), dtype=int)

    for i, s in enumerate(samples):
        features = s['features']
        for j, feat in enumerate(FEATURES):
            val = features.get(feat)
            X[i, j] = float(val) if val is not None else _default(feat)
        y[i] = s['outcome']

    return X, y


def _default(feat: str) -> float:
    defaults = {
        'rsi_at_entry': 50.0, 'volume_ratio': 1.0, 'vix_at_entry': 22.0,
        'atr_pct_at_entry': 2.5, 'ma50_distance': 0.0, 'day_of_week': 2.0,
        'sector_momentum': 0.0, 'spy_5d_return': 0.0, 'hmm_regime': 1.0,
    }
    return defaults.get(feat, 0.0)


# ── Methode 1: Permutation Importance ────────────────────────────────────────

def permutation_importance(X: np.ndarray, y: np.ndarray,
                            n_repeats: int = 30) -> dict[str, dict]:
    """
    Misst wie viel Accuracy verloren geht wenn ein Feature zufällig gemischt wird.
    Hoher Drop = Feature ist wichtig.
    """
    if not MODEL_FILE.exists():
        return {}

    with open(MODEL_FILE, 'rb') as f:
        data = pickle.load(f)
    model = data['model']

    def accuracy(X_eval: np.ndarray) -> float:
        correct = 0
        for i in range(len(X_eval)):
            feat_dict = {feat: X_eval[i, j] for j, feat in enumerate(FEATURES)}
            pred = model.predict_one(feat_dict)
            if pred is not None and int(pred) == y[i]:
                correct += 1
        return correct / len(X_eval) if len(X_eval) > 0 else 0.5

    # Baseline Accuracy
    baseline = accuracy(X)

    results = {}
    for j, feat in enumerate(FEATURES):
        drops = []
        for _ in range(n_repeats):
            X_perm = X.copy()
            np.random.shuffle(X_perm[:, j])
            perm_acc = accuracy(X_perm)
            drops.append(baseline - perm_acc)

        results[feat] = {
            'baseline_accuracy': round(baseline, 4),
            'mean_drop': round(float(np.mean(drops)), 4),
            'std_drop': round(float(np.std(drops)), 4),
            'importance': round(float(np.mean(drops)) / baseline if baseline > 0 else 0, 4),
        }

    return results


# ── Methode 2: Spearman-Korrelation ──────────────────────────────────────────

def spearman_correlations(X: np.ndarray, y: np.ndarray) -> dict[str, dict]:
    """Spearman-Rang-Korrelation jedes Features mit dem Outcome."""
    results = {}
    for j, feat in enumerate(FEATURES):
        corr, pval = stats.spearmanr(X[:, j], y)
        try:
            corr_f = float(corr) if not (corr != corr) else 0.0  # nan check
            pval_f = float(pval) if not (pval != pval) else 1.0
        except Exception:
            corr_f, pval_f = 0.0, 1.0
        results[feat] = {
            'correlation': round(corr_f, 4),
            'p_value': round(pval_f, 4),
            'significant': bool(pval_f < 0.05),
            'direction': 'positive' if corr_f > 0 else 'negative',
        }
    return results


# ── Methode 3: Mutual Information ────────────────────────────────────────────

def mutual_information(X: np.ndarray, y: np.ndarray,
                        n_bins: int = 10) -> dict[str, float]:
    """
    Mutual Information zwischen Feature und Outcome.
    Misst nicht-lineare Abhängigkeit (besser als Korrelation).
    """
    results = {}
    for j, feat in enumerate(FEATURES):
        x_col = X[:, j]
        # Diskretisieren für MI-Berechnung
        bins = np.linspace(x_col.min(), x_col.max() + 1e-9, n_bins + 1)
        x_binned = np.digitize(x_col, bins) - 1

        # Gemeinsame + marginale Wahrscheinlichkeiten
        mi = 0.0
        n = len(y)
        classes = [0, 1]

        for c in classes:
            for b in range(n_bins):
                p_joint = np.sum((y == c) & (x_binned == b)) / n
                p_y = np.sum(y == c) / n
                p_x = np.sum(x_binned == b) / n
                if p_joint > 0 and p_y > 0 and p_x > 0:
                    mi += p_joint * np.log2(p_joint / (p_y * p_x))

        results[feat] = round(float(mi), 4)
    return results


# ── Methode 4: KS-Test (WIN vs. LOSS Verteilung) ─────────────────────────────

def ks_distributions(X: np.ndarray, y: np.ndarray) -> dict[str, dict]:
    """
    Kolmogorov-Smirnov Test: Sind die Feature-Verteilungen von WIN und LOSS verschieden?
    Große KS-Statistik = Feature unterscheidet gut zwischen WIN und LOSS.
    """
    results = {}
    wins = y == 1
    losses = y == 0

    for j, feat in enumerate(FEATURES):
        win_vals = X[wins, j]
        loss_vals = X[losses, j]

        if len(win_vals) < 5 or len(loss_vals) < 5:
            results[feat] = {'ks_stat': None, 'p_value': None, 'discriminative': False}
            continue

        ks_stat, p_val = stats.ks_2samp(win_vals, loss_vals)
        results[feat] = {
            'ks_stat': round(float(ks_stat), 4),
            'p_value': round(float(p_val), 4),
            'discriminative': bool(p_val < 0.05),
            'win_mean': round(float(np.mean(win_vals)), 3),
            'loss_mean': round(float(np.mean(loss_vals)), 3),
            'win_median': round(float(np.median(win_vals)), 3),
            'loss_median': round(float(np.median(loss_vals)), 3),
        }
    return results


# ── Gesamt-Score ──────────────────────────────────────────────────────────────

def compute_composite_score(perm: dict, spearman: dict, mi: dict,
                              ks: dict) -> dict[str, float]:
    """
    Kombiniert alle 4 Methoden zu einem Gesamt-Importance-Score (0–1).
    Gewichtung: Permutation 40% | MI 30% | KS 20% | Spearman 10%
    """
    scores = {}
    for feat in FEATURES:
        p_score = abs(perm.get(feat, {}).get('importance', 0))
        mi_score = mi.get(feat, 0)
        ks_score = ks.get(feat, {}).get('ks_stat') or 0
        spear_score = abs(spearman.get(feat, {}).get('correlation', 0))

        # Normalisieren auf 0–1 Range (relativ zu anderen Features)
        scores[feat] = {
            'perm': p_score,
            'mi': mi_score,
            'ks': ks_score,
            'spearman': spear_score,
        }

    # Normalize each method across features
    for method in ['perm', 'mi', 'ks', 'spearman']:
        vals = [scores[f][method] for f in FEATURES]
        max_val = max(vals) if max(vals) > 0 else 1
        for feat in FEATURES:
            scores[feat][f'{method}_norm'] = scores[feat][method] / max_val

    # Weighted composite
    composite = {}
    for feat in FEATURES:
        s = scores[feat]
        composite[feat] = round(
            0.40 * s['perm_norm'] +
            0.30 * s['mi_norm'] +
            0.20 * s['ks_norm'] +
            0.10 * s['spearman_norm'],
            4
        )

    return composite


# ── Empfehlungen ─────────────────────────────────────────────────────────────

def generate_recommendations(composite: dict, ks: dict,
                              spearman: dict) -> list[str]:
    """Generiert konkrete Handlungs-Empfehlungen."""
    recs = []
    sorted_feats = sorted(composite.items(), key=lambda x: -x[1])

    top3 = [f for f, _ in sorted_feats[:3]]
    bottom3 = [f for f, _ in sorted_feats[-3:]]

    recs.append(f"🏆 TOP Features: {', '.join(FEATURE_LABELS[f] for f in top3)}")
    recs.append(f"🗑️  Schwache Features: {', '.join(FEATURE_LABELS[f] for f in bottom3)}")

    # Spezifische Erkenntnisse
    for feat, score in sorted_feats[:3]:
        corr = spearman.get(feat, {}).get('correlation', 0)
        ks_s = ks.get(feat, {}).get('ks_stat')
        ks_disc = ks.get(feat, {}).get('discriminative', False)
        label = FEATURE_LABELS[feat]

        if ks_disc and abs(corr) > 0.1:
            direction = 'höher = WIN' if corr > 0 else 'niedriger = WIN'
            recs.append(f"  → {label}: {direction} (KS signifikant, Corr {corr:+.2f})")
        elif ks_disc:
            w_m = ks.get(feat, {}).get('win_mean')
            l_m = ks.get(feat, {}).get('loss_mean')
            if w_m and l_m:
                recs.append(f"  → {label}: WIN Ø{w_m:.1f} vs LOSS Ø{l_m:.1f}")

    # Redundanz-Check (starke Korrelation zwischen Features)
    recs.append("\n📊 Feature-Redundanz:")
    redundant_pairs = []
    for i, f1 in enumerate(FEATURES):
        for j, f2 in enumerate(FEATURES):
            if j <= i:
                continue
            # Grobe Prüfung: sind die normalized scores ähnlich?
            if abs(composite[f1] - composite[f2]) < 0.05 and composite[f1] > 0.3:
                redundant_pairs.append((f1, f2))

    if redundant_pairs:
        for f1, f2 in redundant_pairs[:3]:
            recs.append(f"  ⚠️  {FEATURE_LABELS[f1]} ≈ {FEATURE_LABELS[f2]} (ähnliche Importance)")
    else:
        recs.append("  ✅ Keine offensichtliche Redundanz")

    return recs


# ── Haupt-Analyse ─────────────────────────────────────────────────────────────

def run_analysis(force_bootstrap: bool = False, real_only: bool = False,
                  quick: bool = False) -> dict:
    """Vollständige Feature-Importance-Analyse."""
    samples, data_source = get_samples(force_bootstrap, real_only)

    if len(samples) < 10:
        print(f"  ⚠️  Zu wenig Samples ({len(samples)}) — mindestens 10 nötig")
        return {}

    print(f"  Datenquelle: {data_source}")
    X, y = to_arrays(samples)
    n_wins = int(np.sum(y))
    n_loss = len(y) - n_wins
    print(f"  Samples: {len(samples)} | WIN: {n_wins} ({n_wins/len(y):.0%}) | LOSS: {n_loss}")

    print("  [1/4] Permutation Importance...")
    n_repeats = 10 if quick else 30
    perm = permutation_importance(X, y, n_repeats=n_repeats)

    print("  [2/4] Spearman Korrelation...")
    spearman = spearman_correlations(X, y)

    print("  [3/4] Mutual Information...")
    mi = mutual_information(X, y)

    print("  [4/4] KS Verteilungstest...")
    ks = ks_distributions(X, y)

    print("  Composite Score berechnen...")
    composite = compute_composite_score(perm, spearman, mi, ks)
    recommendations = generate_recommendations(composite, ks, spearman)

    result = {
        'data_source': data_source,
        'n_samples': len(samples),
        'n_wins': n_wins,
        'n_losses': n_loss,
        'win_rate': round(n_wins / len(samples), 3),
        'composite_scores': composite,
        'permutation_importance': perm,
        'spearman': spearman,
        'mutual_information': mi,
        'ks_test': ks,
        'recommendations': recommendations,
        'analyzed_at': datetime.now(timezone.utc).isoformat(),
    }

    OUTPUT_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(result: dict):
    """Formatierter Report für Terminal/Discord."""
    if not result:
        print("❌ Keine Ergebnisse")
        return

    composite = result['composite_scores']
    ks = result['ks_test']
    spearman = result['spearman']
    mi = result['mutual_information']
    perm = result['permutation_importance']

    sorted_feats = sorted(composite.items(), key=lambda x: -x[1])

    print("\n" + "="*60)
    print("Feature Importance — Phase 6")
    print(f"Daten: {result['data_source']} | "
          f"Win-Rate: {result['win_rate']:.0%} | N={result['n_samples']}")
    print("="*60)
    print(f"\n{'Feature':<18} {'Score':>6} {'Perm↓':>7} {'SpRank':>7} {'MI':>6} {'KS':>6} {'Diskr':>6}")
    print("-"*60)

    icons = {0: '🏆', 1: '🥈', 2: '🥉'}

    for rank, (feat, score) in enumerate(sorted_feats):
        icon = icons.get(rank, '  ')
        label = FEATURE_LABELS[feat]
        perm_drop = perm.get(feat, {}).get('mean_drop', 0)
        spear = spearman.get(feat, {}).get('correlation', 0)
        mi_val = mi.get(feat, 0)
        ks_stat = ks.get(feat, {}).get('ks_stat') or 0
        disc = '✅' if ks.get(feat, {}).get('discriminative') else '  '

        print(f"{icon}{label:<16} {score:>6.3f} {perm_drop:>+7.3f} {spear:>+7.3f} "
              f"{mi_val:>6.3f} {ks_stat:>6.3f}  {disc}")

    print("-"*60)
    print("\n📋 Empfehlungen:")
    for rec in result.get('recommendations', []):
        print(f"  {rec}")

    # Data-Source Warnung
    if 'bootstrap' in result['data_source']:
        print(f"\n⚠️  ACHTUNG: Analyse basiert auf Backtest-Daten (synthetisch!)")
        print(f"   Ergebnisse werden zuverlässiger mit echten Trades (Ziel: 50+)")
        n_real = result['n_samples'] - (
            int(result['data_source'].split('bootstrap(')[1].split(')')[0])
            if 'bootstrap(' in result['data_source'] else result['n_samples']
        ) if 'mixed' in result['data_source'] else 0
        if n_real > 0:
            print(f"   Echte Trades bisher: {n_real}")

    print("="*60)


# ── Integration: Online Model Feature-Gewichtung ──────────────────────────────

def bridge_to_conviction_weights(composite: dict) -> dict | None:
    """K9 — Feature-Importance → Conviction-Weights Brücke.
    Aggregiert Feature-Scores zu den 4 Conviction-Faktoren und schreibt
    data/conviction_weights.json (wenn die Datei nicht in den letzten
    7 Tagen schon vom daily_learning_cycle aktualisiert wurde).

    Mapping:
      technical      ← rsi_at_entry, volume_ratio, atr_pct_at_entry, ma50_distance
      market_context ← vix_at_entry, hmm_regime, spy_5d_return, sector_momentum
      thesis         ← (kein Feature im Set; bleibt Default)
      risk_reward    ← (kein Feature im Set; bleibt Default)
    """
    try:
        from datetime import datetime as _dt, timezone as _tz
        out_path = WS / 'data' / 'conviction_weights.json'

        # Schreibe nur wenn aktuelle Datei älter als 7 Tage (daily_learning hat Vorrang)
        try:
            if out_path.exists():
                age_d = (_dt.now().timestamp() - out_path.stat().st_mtime) / 86400.0
                if age_d < 7:
                    return None  # daily_learning hat es schon kürzlich aktualisiert
        except Exception:
            pass

        tech_keys = ['rsi_at_entry', 'volume_ratio', 'atr_pct_at_entry', 'ma50_distance']
        mkt_keys = ['vix_at_entry', 'hmm_regime', 'spy_5d_return', 'sector_momentum']
        tech_scores = [composite[k] for k in tech_keys if k in composite]
        mkt_scores = [composite[k] for k in mkt_keys if k in composite]
        if not tech_scores or not mkt_scores:
            return None

        avg_tech = sum(tech_scores) / len(tech_scores)
        avg_mkt = sum(mkt_scores) / len(mkt_scores)
        # Defaults: thesis=35, technical=30, risk_reward=20, market_context=15
        # Adjust ±5pt basierend auf relativer Wichtigkeit von tech vs mkt
        ratio = avg_tech / (avg_tech + avg_mkt) if (avg_tech + avg_mkt) > 0 else 0.5
        # ratio > 0.5 → tech wichtiger → mehr Gewicht auf technical
        tech_w = max(20, min(40, round(30 + (ratio - 0.5) * 20)))
        mkt_w = max(10, min(25, round(15 + (0.5 - ratio) * 20)))
        # Constraint: Summe = 100
        thesis_w = 35
        rr_w = 100 - tech_w - mkt_w - thesis_w
        rr_w = max(15, min(25, rr_w))
        # final balance
        thesis_w = 100 - tech_w - mkt_w - rr_w

        weights = {'thesis': thesis_w, 'technical': tech_w,
                   'risk_reward': rr_w, 'market_context': mkt_w}

        out = {
            'weights': weights,
            'computed_at': _dt.now(_tz.utc).isoformat(),
            'source': 'feature_importance_bridge_K9',
            'feature_avg_tech': round(avg_tech, 3),
            'feature_avg_mkt': round(avg_mkt, 3),
        }
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
        return out
    except Exception as e:
        print(f'[bridge_to_conviction_weights] error: {e}')
        return None


def export_feature_weights(composite: dict) -> dict:
    """
    Konvertiert Composite Scores in Feature-Gewichte für Online Model.
    Normalisiert auf [0.5, 1.5] Range (kein Feature ganz ausschalten).
    """
    scores = list(composite.values())
    min_s, max_s = min(scores), max(scores)
    if max_s == min_s:
        return {feat: 1.0 for feat in composite}

    weights = {}
    for feat, score in composite.items():
        # Normalisiert 0→0.5, max→1.5
        weights[feat] = round(0.5 + (score - min_s) / (max_s - min_s), 3)

    return weights


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    args = sys.argv[1:]
    force_bootstrap = '--bootstrap' in args
    real_only = '--real-only' in args
    quick = '--quick' in args

    print("[Feature Importance] Starte Analyse...")
    result = run_analysis(force_bootstrap, real_only, quick)
    if result:
        print_report(result)

        # Feature-Gewichte exportieren
        weights = export_feature_weights(result['composite_scores'])
        weights_file = WS / 'data/feature_weights.json'
        weights_file.write_text(json.dumps(weights, indent=2))
        print(f"\n✅ Feature-Gewichte gespeichert: data/feature_weights.json")

        # K9 — Feature-Importance → Conviction-Weights Brücke
        bridged = bridge_to_conviction_weights(result['composite_scores'])
        if bridged:
            w = bridged['weights']
            print(f"✅ Conviction-Weights aktualisiert (K9-Bridge): "
                  f"thesis={w['thesis']} technical={w['technical']} "
                  f"risk_reward={w['risk_reward']} market_context={w['market_context']}")
        else:
            print("ℹ️  Conviction-Weights NICHT überschrieben (daily_learning hat Vorrang oder zu wenig Daten)")
