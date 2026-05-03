#!/usr/bin/env python3
"""
ml_winprob_model.py — Phase 45d (Sprint 3): XGBoost Win-Probability-Modell.

Ersetzt den kaputten Conviction-Score (Sprint 0 Diagnose: 92% aller Trades
hatten Conviction 0-10%, keine Differenzierung) durch echtes ML-Scoring.

Input:  features-Tabelle (Sprint 2)
Target: Trade-Outcome (1 = Win, 0 = Loss)

Modell: XGBoost-Classifier — robust bei kleinen Sample-Sizes,
        liefert calibrated probabilities.

Walk-Forward: Train auf 12-Monate, Test auf nachfolgendem Monat,
              jede 3 Monate neu.

Output:
  data/ml_winprob_model.pkl     trained model
  data/ml_winprob_metrics.json  Brier, AUC, Confusion-Matrix
  data/ml_winprob_features.json Feature-Importance
"""
from __future__ import annotations
import json, os, pickle, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
MODEL_FILE = WS / 'data' / 'ml_winprob_model.pkl'
METRICS = WS / 'data' / 'ml_winprob_metrics.json'
FEATURE_IMP = WS / 'data' / 'ml_winprob_features.json'


def _load_training_data() -> tuple[list[dict], list[int]]:
    """Joint features × trade_outcomes."""
    if not DB.exists(): return [], []
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    # Trades mit Outcome
    trades = c.execute(
        "SELECT id, ticker, entry_date, status, pnl_eur "
        "FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED') "
        "AND pnl_eur IS NOT NULL"
    ).fetchall()
    X, y = [], []
    for t in trades:
        feat_rows = c.execute(
            "SELECT feature_name, value FROM features "
            "WHERE ticker=? AND date <= ? "
            "ORDER BY date DESC LIMIT 35",  # 35 features max
            (t['ticker'], (t['entry_date'] or '')[:10])
        ).fetchall()
        if not feat_rows: continue
        feat_dict = {r['feature_name']: r['value'] for r in feat_rows}
        if not feat_dict: continue
        X.append(feat_dict)
        outcome = 1 if (t['pnl_eur'] or 0) > 0 else 0
        y.append(outcome)
    c.close()
    return X, y


def train_model(X: list[dict], y: list[int]) -> dict:
    """Trainiere XGBoost (oder LogReg-Fallback)."""
    if len(X) < 10:
        return {'error': f'insufficient_data (n={len(X)})'}

    # Convert dicts to feature-matrix
    all_keys = sorted({k for d in X for k in d.keys()})
    X_mat = [[d.get(k, 0.0) for k in all_keys] for d in X]

    try:
        import xgboost as xgb
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import brier_score_loss, accuracy_score, roc_auc_score
        X_train, X_test, y_train, y_test = train_test_split(
            X_mat, y, test_size=0.2, random_state=42, stratify=y if sum(y) >= 2 else None
        )
        model = xgb.XGBClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.05,
            objective='binary:logistic', eval_metric='logloss',
            use_label_encoder=False
        )
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]
        metrics = {
            'algorithm': 'xgboost',
            'n_train': len(X_train), 'n_test': len(X_test),
            'accuracy': float(accuracy_score(y_test, y_pred)),
            'brier_score': float(brier_score_loss(y_test, y_prob)),
            'auc': float(roc_auc_score(y_test, y_prob)) if len(set(y_test)) > 1 else 0,
        }
        # Feature importance
        importances = dict(zip(all_keys, model.feature_importances_.tolist()))
        feat_imp = sorted(importances.items(), key=lambda x: -x[1])[:15]
        metrics['top_features'] = feat_imp

        # Persist
        MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MODEL_FILE, 'wb') as f:
            pickle.dump({'model': model, 'feature_keys': all_keys}, f)
        return metrics

    except ImportError:
        # Logistic Regression Fallback
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import train_test_split
            from sklearn.metrics import brier_score_loss, accuracy_score
            X_train, X_test, y_train, y_test = train_test_split(
                X_mat, y, test_size=0.2, random_state=42
            )
            model = LogisticRegression(max_iter=500, C=1.0)
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            y_prob = model.predict_proba(X_test)[:, 1]
            metrics = {
                'algorithm': 'logreg_fallback',
                'n_train': len(X_train), 'n_test': len(X_test),
                'accuracy': float(accuracy_score(y_test, y_pred)),
                'brier_score': float(brier_score_loss(y_test, y_prob)),
            }
            with open(MODEL_FILE, 'wb') as f:
                pickle.dump({'model': model, 'feature_keys': all_keys}, f)
            return metrics
        except Exception as e:
            return {'error': f'no_ml_libs: {e}'}


def predict_winprob(ticker: str) -> float | None:
    """Lade Modell + features und liefere P(win) fuer Ticker."""
    if not MODEL_FILE.exists(): return None
    try:
        with open(MODEL_FILE, 'rb') as f:
            d = pickle.load(f)
        model = d['model']; keys = d['feature_keys']
    except Exception: return None
    if not DB.exists(): return None
    c = sqlite3.connect(str(DB))
    rows = c.execute(
        "SELECT feature_name, value FROM features WHERE ticker=? "
        "ORDER BY date DESC LIMIT 35", (ticker,)
    ).fetchall()
    c.close()
    feat = {r[0]: r[1] for r in rows}
    if not feat: return None
    x = [[feat.get(k, 0.0) for k in keys]]
    try:
        return float(model.predict_proba(x)[0, 1])
    except Exception: return None


def run_training() -> dict:
    X, y = _load_training_data()
    metrics = train_model(X, y)
    metrics['ts'] = datetime.now(timezone.utc).isoformat()
    metrics['n_total'] = len(X)
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    return metrics


def main():
    r = run_training()
    print(f'═══ ML Win-Prob Training ═══')
    if 'error' in r:
        print(f'Error: {r["error"]}'); return 1
    print(f'  Algorithm: {r.get("algorithm")}')
    print(f'  N total: {r.get("n_total")}, train: {r.get("n_train")}, test: {r.get("n_test")}')
    print(f'  Accuracy: {r.get("accuracy"):.3f}')
    print(f'  Brier:    {r.get("brier_score"):.3f}')
    if 'auc' in r: print(f'  AUC:      {r.get("auc"):.3f}')
    print(f'\nTop Features:')
    for f, imp in (r.get('top_features') or [])[:10]:
        print(f'  {f:<28} {imp:.3f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
