#!/usr/bin/env python3
"""
Regime Detector — Phase 5 des ML-Bauplans
==========================================
HMM-basierte Markt-Regime-Erkennung.
Ersetzt willkürliche VIX-Schwellenwerte durch datengetriebene Zustände.

Modell:
  GaussianHMM mit 4 Zuständen auf 5 Jahren S&P 500 + VIX + Anleihen-Rendite.
  Features:
    - S&P 500 Tagesrendite (%)
    - VIX-Niveau
    - VIX-Tagesveränderung (%)
    - 10Y Treasury Yield (Zinsumfeld)
    - S&P 500 5-Tage-Momentum

Zustände (automatisch aus Daten gelernt, nicht manuell definiert):
  → werden nach Training nach Volatilität/Rendite benannt:
    BULL     (niedrige Vola, positive Rendite)
    NEUTRAL  (moderate Vola, flache Rendite)
    RISK_OFF (hohe Vola, negative Rendite)
    CRASH    (extreme Vola, starke negative Rendite)

Usage:
  python3 regime_detector.py                  # Aktuelles Regime
  python3 regime_detector.py --train          # HMM (neu) trainieren
  python3 regime_detector.py --history 30     # Letzten 30 Tage Regime-History
  python3 regime_detector.py --integrate      # In CEO-Direktive einbauen
"""

import json
import pickle
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
from hmmlearn import hmm

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
CACHE = WS / 'data/price_cache'
MODEL_FILE = WS / 'data/hmm_regime.pkl'
REGIME_FILE = WS / 'data/regime_history.json'
CEO_FILE = WS / 'data/ceo_directive.json'

N_STATES = 4
REGIME_NAMES = ['BULL', 'NEUTRAL', 'RISK_OFF', 'CRASH']  # nach Training zugewiesen


# ── Daten laden ───────────────────────────────────────────────────────────────

def load_market_data() -> dict[str, dict]:
    """Lädt S&P 500, VIX, TNX aus Cache. Gibt gemeinsame Daten zurück."""
    sp_file  = CACHE / 'IXGSPC.json'
    vix_file = CACHE / 'IXVIX.json'
    tnx_file = CACHE / 'IXTNX.json'

    if not sp_file.exists():
        raise FileNotFoundError("S&P 500 Daten nicht gefunden. Erst: download_data('^GSPC')")

    sp  = json.loads(sp_file.read_text(encoding="utf-8"))
    vix = json.loads(vix_file.read_text(encoding="utf-8")) if vix_file.exists() else {}
    tnx = json.loads(tnx_file.read_text(encoding="utf-8")) if tnx_file.exists() else {}

    # Schnittmenge der Daten
    common_dates = sorted(set(sp.keys()) & (set(vix.keys()) if vix else set(sp.keys())))
    return {
        'd': common_dates,
        'sp': [sp[d]['c'] for d in common_dates],
        'vix': [vix.get(d, {}).get('c', 20.0) for d in common_dates],
        'tnx': [tnx.get(d, {}).get('c', 4.0) for d in common_dates],
    }


def build_feature_matrix(data: dict) -> np.ndarray:
    """
    Erstellt Feature-Matrix für HMM-Training.
    Shape: (n_days, 5)
    """
    sp = data['sp']
    vix = data['vix']
    tnx = data['tnx']
    n = len(sp)

    features = np.zeros((n, 5))

    for i in range(1, n):
        # 1. S&P 500 Tagesrendite
        features[i, 0] = (sp[i] - sp[i-1]) / sp[i-1] * 100

        # 2. VIX-Niveau (normalisiert)
        features[i, 1] = vix[i]

        # 3. VIX Tagesveränderung
        features[i, 2] = (vix[i] - vix[i-1]) / vix[i-1] * 100 if vix[i-1] > 0 else 0

        # 4. 10Y Treasury Yield
        features[i, 3] = tnx[i]

        # 5. S&P 500 5-Tage-Momentum
        if i >= 5:
            features[i, 4] = (sp[i] - sp[i-5]) / sp[i-5] * 100

    return features[1:]  # Ersten Tag weglassen (kein return berechenbar)


# ── HMM Training ──────────────────────────────────────────────────────────────

def train(force: bool = False) -> dict:
    """
    Trainiert GaussianHMM auf 5 Jahren Marktdaten.
    Automatische Regime-Benennung nach Volatilität + Rendite.
    """
    if MODEL_FILE.exists() and not force:
        print("  ℹ️  HMM bereits trainiert. --force zum Neu-Trainieren.")
        return load_model_meta()

    print("  Lade Marktdaten...")
    data = load_market_data()
    X = build_feature_matrix(data)
    dates = data['d'][1:]  # Sync mit Feature-Matrix

    print(f"  Training HMM ({N_STATES} Zustände) auf {len(X)} Tagen...")

    # Mehrere Random Starts → bestes Modell wählen (Robustheit)
    best_model = None
    best_score = -np.inf

    for seed in range(10):
        model = hmm.GaussianHMM(
            n_components=N_STATES,
            covariance_type='full',
            n_iter=200,
            random_state=seed,
            tol=1e-4,
        )
        try:
            model.fit(X)
            score = model.score(X)
            if score > best_score:
                best_score = score
                best_model = model
        except Exception:
            continue

    if best_model is None:
        raise RuntimeError("HMM Training fehlgeschlagen")

    # Regime-Sequenz für alle Tage berechnen
    hidden_states = best_model.predict(X)

    # Regime-Charakterisierung (aus Daten, nicht manuell)
    regime_stats = {}
    for state in range(N_STATES):
        mask = hidden_states == state
        state_returns = X[mask, 0]
        state_vix = X[mask, 1]
        regime_stats[state] = {
            'mean_return': float(np.mean(state_returns)),
            'std_return': float(np.std(state_returns)),
            'mean_vix': float(np.mean(state_vix)),
            'n_days': int(np.sum(mask)),
        }

    # Automatische Benennung: sortiert nach Volatilität (aufsteigend)
    sorted_by_vix = sorted(regime_stats.keys(), key=lambda s: regime_stats[s]['mean_vix'])
    state_to_name = {}
    name_labels = ['BULL', 'NEUTRAL', 'RISK_OFF', 'CRASH']
    for i, state in enumerate(sorted_by_vix):
        state_to_name[state] = name_labels[i]

    print(f"\n  Gelernte Regime-Zustände:")
    for state in sorted_by_vix:
        name = state_to_name[state]
        s = regime_stats[state]
        print(f"    {name:10s}: VIX Ø{s['mean_vix']:.1f} | "
              f"Return Ø{s['mean_return']:+.2f}% | σ{s['std_return']:.2f}% | "
              f"{s['n_days']} Tage ({s['n_days']/len(X)*100:.0f}%)")

    # Regime-History speichern
    regime_history = {}
    for i, (date, state) in enumerate(zip(dates, hidden_states)):
        regime_history[date] = {
            'state': int(state),
            'name': state_to_name[int(state)],
            'vix': float(X[i, 1]),
            'sp_return': float(X[i, 0]),
        }

    REGIME_FILE.write_text(json.dumps(regime_history, indent=2))

    # Modell + Mapping speichern
    meta = {
        'state_to_name': {str(k): v for k, v in state_to_name.items()},
        'regime_stats': {str(k): v for k, v in regime_stats.items()},
        'trained_on': len(X),
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'log_score': round(best_score, 2),
        'last_date': dates[-1],
    }

    with open(MODEL_FILE, 'wb') as f:
        pickle.dump({'model': best_model, 'meta': meta}, f)

    print(f"\n  ✅ HMM trainiert | Score: {best_score:.0f} | {len(X)} Tage")
    return meta


def load_model_meta() -> dict:
    """Lädt Modell-Metadaten."""
    if not MODEL_FILE.exists():
        return {}
    with open(MODEL_FILE, 'rb') as f:
        data = pickle.load(f)
    return data.get('meta', {})


# ── Regime-Erkennung ──────────────────────────────────────────────────────────

def detect_current_regime() -> dict:
    """
    Erkennt das aktuelle Markt-Regime.
    Nutzt letzte 60 Tage für Kontext-Window.
    """
    if not MODEL_FILE.exists():
        return {'name': 'UNKNOWN', 'error': 'Modell nicht trainiert'}

    with open(MODEL_FILE, 'rb') as f:
        saved = pickle.load(f)
    model = saved['model']
    meta = saved['meta']
    state_to_name = {int(k): v for k, v in meta['state_to_name'].items()}

    # Aktuellen Kontext laden
    data = load_market_data()
    X_all = build_feature_matrix(data)
    dates = data['d'][1:]

    if len(X_all) < 30:
        return {'name': 'INSUFFICIENT_DATA'}

    # Letzten 60 Tage → stabile Regime-Erkennung
    X_recent = X_all[-60:]
    states = model.predict(X_recent)
    probs = model.predict_proba(X_recent)

    current_state = int(states[-1])
    current_name = state_to_name.get(current_state, 'UNKNOWN')
    current_probs = {state_to_name.get(i, str(i)): round(float(p), 3)
                     for i, p in enumerate(probs[-1])}

    # Regime-Stabilität: wie lange sind wir schon in diesem Regime?
    streak = 1
    for s in reversed(states[:-1]):
        if s == current_state:
            streak += 1
        else:
            break

    # Transition-Wahrscheinlichkeit (Wechsel-Risiko)
    trans_matrix = model.transmat_
    stay_prob = float(trans_matrix[current_state, current_state])
    switch_risk = 1 - stay_prob

    # Letzten 5 Tage Trend
    last_5_states = [state_to_name.get(int(s), '?') for s in states[-5:]]
    trend = 'STABLE' if len(set(last_5_states)) == 1 else 'TRANSITIONING'

    # Regime-Statistiken
    regime_stat = meta.get('regime_stats', {}).get(str(current_state), {})

    result = {
        'name': current_name,
        'state': current_state,
        'probabilities': current_probs,
        'streak_days': streak,
        'trend': trend,
        'switch_risk': round(switch_risk, 3),
        'last_5_days': last_5_states,
        'vix_current': round(float(X_recent[-1, 1]), 2),
        'sp_return_today': round(float(X_recent[-1, 0]), 3),
        'sp_momentum_5d': round(float(X_recent[-1, 4]), 3),
        'historical_mean_return': round(regime_stat.get('mean_return', 0), 3),
        'historical_mean_vix': round(regime_stat.get('mean_vix', 0), 1),
        'detected_at': datetime.now(timezone.utc).isoformat(),
    }

    return result


def get_regime_history(days: int = 30) -> list[dict]:
    """Gibt Regime-History der letzten N Tage zurück."""
    if not REGIME_FILE.exists():
        return []
    history = json.loads(REGIME_FILE.read_text(encoding="utf-8"))
    dates = sorted(history.keys())[-days:]
    return [{'date': d, **history[d]} for d in dates]


# ── CEO Integration ───────────────────────────────────────────────────────────

def update_ceo_directive(regime: dict) -> bool:
    """Schreibt aktuelles Regime in CEO-Direktive."""
    try:
        ceo = json.loads(CEO_FILE.read_text(encoding="utf-8")) if CEO_FILE.exists() else {}
        ceo['hmm_regime'] = {
            'name': regime['name'],
            'probabilities': regime.get('probabilities', {}),
            'streak_days': regime.get('streak_days', 0),
            'trend': regime.get('trend', 'UNKNOWN'),
            'switch_risk': regime.get('switch_risk', 0),
            'vix': regime.get('vix_current'),
            'updated_at': regime.get('detected_at'),
        }
        # Auch das alte 'regime' Feld aktualisieren (Rückwärtskompatibilität)
        ceo['regime'] = regime['name']
        CEO_FILE.write_text(json.dumps(ceo, indent=2, ensure_ascii=False))
        return True
    except Exception as e:
        print(f"  ⚠️  CEO Update Fehler: {e}")
        return False


def regime_to_strategy_weights(regime_name: str) -> dict:
    """
    Gibt Strategie-Gewichtungen für das aktuelle Regime zurück.
    Wird vom Entry Gate genutzt um Strategie-Freigaben zu steuern.
    """
    weights = {
        'BULL': {
            'tech': 1.2, 'energy': 1.0, 'defense': 1.0,
            'metals': 1.0, 'shipping': 1.1, 'pharma': 0.8
        },
        'NEUTRAL': {
            'tech': 1.0, 'energy': 1.1, 'defense': 1.1,
            'metals': 1.0, 'shipping': 1.0, 'pharma': 1.0
        },
        'RISK_OFF': {
            'tech': 0.6, 'energy': 1.2, 'defense': 1.3,
            'metals': 1.1, 'shipping': 0.8, 'pharma': 1.2
        },
        'CRASH': {
            'tech': 0.2, 'energy': 0.8, 'defense': 1.0,
            'metals': 0.7, 'shipping': 0.5, 'pharma': 1.0
        },
    }
    return weights.get(regime_name, weights['NEUTRAL'])


# ── Online Model Integration ──────────────────────────────────────────────────

def get_regime_feature() -> float:
    """
    Gibt numerischen Regime-Score zurück für Online Model (Phase 4).
    BULL=0, NEUTRAL=1, RISK_OFF=2, CRASH=3
    Wird als Feature 'hmm_regime' in feature_collector eingebaut.
    """
    regime = detect_current_regime()
    name_to_score = {'BULL': 0.0, 'NEUTRAL': 1.0, 'RISK_OFF': 2.0, 'CRASH': 3.0}
    return name_to_score.get(regime.get('name', 'NEUTRAL'), 1.0)


# ── Cron-Funktion (täglich aufgerufen) ───────────────────────────────────────

def daily_regime_update() -> dict:
    """
    Täglich aufgerufen: aktuelles Regime erkennen + CEO updaten.
    Returns: Regime-Dict
    """
    # Frische Daten laden (Cache wird in backtest_engine aktualisiert)
    regime = detect_current_regime()
    update_ceo_directive(regime)

    # Regime-History updaten
    today = datetime.now().strftime('%Y-%m-%d')
    history = json.loads(REGIME_FILE.read_text(encoding="utf-8")) if REGIME_FILE.exists() else {}
    history[today] = {
        'state': regime.get('state'),
        'name': regime.get('name'),
        'vix': regime.get('vix_current'),
        'sp_return': regime.get('sp_return_today'),
    }
    REGIME_FILE.write_text(json.dumps(history, indent=2))

    return regime


# ── Visualisierung ────────────────────────────────────────────────────────────

REGIME_COLORS = {
    'BULL': '🟢',
    'NEUTRAL': '🟡',
    'RISK_OFF': '🟠',
    'CRASH': '🔴',
    'UNKNOWN': '⚫',
}


def print_regime_report(regime: dict, history: list[dict] | None = None):
    """Gibt formatierten Regime-Report aus."""
    name = regime.get('name', 'UNKNOWN')
    icon = REGIME_COLORS.get(name, '⚫')

    print("\n" + "="*55)
    print(f"Markt-Regime Detector — HMM Phase 5")
    print("="*55)
    print(f"\nAktuelles Regime: {icon} {name}")
    print(f"  VIX:             {regime.get('vix_current', '?'):.1f}")
    print(f"  S&P Return heute: {regime.get('sp_return_today', 0):+.2f}%")
    print(f"  5d Momentum:     {regime.get('sp_momentum_5d', 0):+.2f}%")
    print(f"  Streak:          {regime.get('streak_days', 0)} Tage in diesem Regime")
    print(f"  Trend:           {regime.get('trend', '?')}")
    print(f"  Wechsel-Risiko:  {regime.get('switch_risk', 0):.0%}")

    print(f"\n  Regime-Wahrscheinlichkeiten:")
    probs = regime.get('probabilities', {})
    for r_name in ['BULL', 'NEUTRAL', 'RISK_OFF', 'CRASH']:
        p = probs.get(r_name, 0)
        bar = '█' * int(p * 20) + '░' * (20 - int(p * 20))
        r_icon = REGIME_COLORS.get(r_name, '⚫')
        print(f"    {r_icon} {r_name:10s}: {p:.0%} {bar}")

    print(f"\n  Letzte 5 Tage: {' → '.join(regime.get('last_5_days', []))}")

    # Strategie-Gewichtungen
    weights = regime_to_strategy_weights(name)
    print(f"\n  Strategie-Gewichtungen in {name}:")
    for sector, w in sorted(weights.items(), key=lambda x: -x[1]):
        bar = '█' * int(w * 8)
        print(f"    {sector:10s}: {w:.1f}x {bar}")

    # History
    if history:
        print(f"\n  Regime-Verlauf (letzte {len(history)} Tage):")
        regime_line = ''
        for entry in history[-30:]:
            regime_line += REGIME_COLORS.get(entry['name'], '⚫')
        print(f"    {regime_line}")
        # Zusammenfassung
        from collections import Counter
        counts = Counter(e['name'] for e in history)
        total = len(history)
        for r_name, count in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"    {REGIME_COLORS.get(r_name,'⚫')} {r_name}: {count}/{total} Tage ({count/total:.0%})")

    print("="*55)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    args = sys.argv[1:]

    if '--train' in args:
        force = '--force' in args
        print("[Regime Detector] Trainiere HMM...")
        meta = train(force=force)

    days = 30
    if '--history' in args:
        idx = args.index('--history')
        if len(args) > idx + 1:
            try:
                days = int(args[idx + 1])
            except ValueError:
                pass

    print("[Regime Detector] Erkenne aktuelles Regime...")
    regime = detect_current_regime()
    history = get_regime_history(days)

    if '--integrate' in args:
        ok = update_ceo_directive(regime)
        print(f"  CEO-Direktive: {'✅ aktualisiert' if ok else '❌ Fehler'}")

    print_regime_report(regime, history if '--history' in args else None)

    if '--quick' not in args:
        weights = regime_to_strategy_weights(regime.get('name', 'NEUTRAL'))
        print(f"\nJSON für CEO: {json.dumps({'regime': regime['name'], 'weights': weights}, indent=2)}")
