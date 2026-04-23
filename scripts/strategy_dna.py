#!/usr/bin/env python3.13
"""
Strategy DNA — Phase 7 des ML-Bauplans
=======================================
Jede Strategie bekommt ein datengetriebenes DNA-Profil:
die optimalen Einstiegsbedingungen — nicht manuell definiert,
sondern aus echten Trade-Daten destilliert.

Was Strategy DNA enthält:
  - optimal_rsi_range:    In welchem RSI-Bereich gewinnt die Strategie am meisten?
  - optimal_vix_range:    Bei welchem VIX-Niveau läuft sie am besten?
  - volume_ratio_min:     Mindest-Volumen-Bestätigung
  - best_regime:          In welchem HMM-Regime performt sie am stärksten?
  - worst_weekday:        Welcher Wochentag ist zu vermeiden?
  - best_weekday:         Welcher Wochentag ist optimal?
  - ma50_sweet_spot:      Optimale MA50-Distanz
  - expected_win_rate:    Erwartete Win-Rate inkl. Konfidenz-Intervall
  - feature_importance:   Pro-Strategie Feature-Gewichtung
  - data_quality:         Wie verlässlich ist das DNA-Profil?

Integration:
  - DNA Gate in paper_trade_engine: Entry nur wenn im Optimal-Range
  - CEO-Direktive: DNA-basierte Conviction-Verfeineerung
  - Alert bei DNA-Verletzung (du tradest gegen dein eigenes Edge)

Usage:
  python3.13 strategy_dna.py                    # Alle DNAs berechnen + speichern
  python3.13 strategy_dna.py --show PS1         # DNA für eine Strategie
  python3.13 strategy_dna.py --check PS1 53 25  # DNA-Check: RSI=53, VIX=25
  python3.13 strategy_dna.py --gate-check       # Alle aktuellen Positionen prüfen
"""

import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

import numpy as np
from scipy import stats

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'
BOOTSTRAP_FILE = WS / 'data/bootstrap_samples.json'
BACKTEST_FILE = WS / 'data/backtest_results.json'
DNA_FILE = WS / 'data/strategy_dna.json'
CEO_FILE = WS / 'data/ceo_directive.json'

FEATURES = [
    'rsi_at_entry', 'volume_ratio', 'vix_at_entry', 'atr_pct_at_entry',
    'ma50_distance', 'day_of_week', 'sector_momentum', 'spy_5d_return', 'hmm_regime'
]

REGIME_MAP = {0.0: 'BULL', 1.0: 'NEUTRAL', 2.0: 'RISK_OFF', 3.0: 'CRASH'}
WEEKDAY_MAP = {0: 'Mo', 1: 'Di', 2: 'Mi', 3: 'Do', 4: 'Fr', 5: 'Sa', 6: 'So'}


# ── Daten laden ───────────────────────────────────────────────────────────────

def load_strategy_samples() -> dict[str, list]:
    """
    Gruppiert Bootstrap-Samples nach Strategie.
    Lädt zusätzlich echte Trades wenn vorhanden.
    """
    by_strategy = defaultdict(list)

    # Bootstrap-Samples
    if BOOTSTRAP_FILE.exists():
        samples = json.loads(BOOTSTRAP_FILE.read_text())
        for s in samples:
            # source = 'backtest_PS1_OXY' → Strategie = 'PS1'
            parts = s['source'].split('_')
            if len(parts) >= 2:
                strat = parts[1]
                by_strategy[strat].append(s)

    # Echte Trades (priorisiert) — in separaten Bucket
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    real_rows = conn.execute("""
        SELECT id, strategy, pnl_eur,
               rsi_at_entry, volume_ratio, vix_at_entry, atr_pct_at_entry,
               ma50_distance, day_of_week, sector_momentum, spy_5d_return, hmm_regime
        FROM paper_portfolio
        WHERE status IN ('WIN','CLOSED','LOSS')
          AND rsi_at_entry IS NOT NULL AND pnl_eur IS NOT NULL
    """).fetchall()
    conn.close()

    # hmm_regime kann String ('NEUTRAL'/'BULLISH'/'BEARISH') oder Zahl sein.
    # Bug AF (2026-04-23): vorher BULLISH→2.0 → wurde in compute_regime_performance
    # mit Modul-MAP {2.0:'RISK_OFF'} verwechselt → BULLISH-Trades als RISK_OFF
    # geloggt. Jetzt aligned mit Modul-MAP (Zeile 60): BULL=0, NEUTRAL=1, RISK_OFF=2.
    REGIME_MAP = {'BULLISH': 0.0, 'NEUTRAL': 1.0, 'BEARISH': 2.0, 'HALT': 2.0,
                  'CORRECTION': 2.0, 'BEAR': 2.0, 'CRASH': 3.0, 'BULL': 0.0}

    def _to_float(feat: str, val):
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            if feat == 'hmm_regime':
                return REGIME_MAP.get(val.upper(), 1.0)
            try:
                return float(val)
            except ValueError:
                return None
        return None

    real_count = 0
    for row in real_rows:
        strat = row['strategy'] or 'unknown'
        features = {feat: _to_float(feat, row[feat]) for feat in FEATURES}
        outcome = 1 if (row['pnl_eur'] or 0) > 0 else 0
        by_strategy[strat].append({'features': features, 'outcome': outcome, 'source': 'real'})
        real_count += 1

    print(f"  Quellen: {sum(1 for s in samples)} Bootstrap + {real_count} echte Trades")
    return dict(by_strategy)


def load_backtest_results() -> dict:
    if not BACKTEST_FILE.exists():
        return {}
    return json.loads(BACKTEST_FILE.read_text())


# ── DNA-Berechnung ────────────────────────────────────────────────────────────

def compute_optimal_range(values: list[float], outcomes: list[int],
                           n_bins: int = 8) -> dict:
    """
    Findet den Feature-Bereich mit der höchsten Win-Rate.
    Gibt optimal_range, win_rate_in_range, lift zurück.
    """
    if len(values) < 20:
        return {'range': None, 'win_rate': None, 'lift': None}

    arr = np.array(values)
    out = np.array(outcomes)
    overall_wr = float(np.mean(out))

    # Percentile-basierte Bins (robuster als gleichmäßige)
    bins = np.percentile(arr, np.linspace(0, 100, n_bins + 1))
    bins = np.unique(bins)  # Duplikate entfernen

    best_range = None
    best_wr = 0.0
    best_n = 0

    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i+1]
        mask = (arr >= lo) & (arr < hi)
        if mask.sum() < 5:
            continue
        wr = float(np.mean(out[mask]))
        if wr > best_wr:
            best_wr = wr
            best_range = [round(lo, 2), round(hi, 2)]
            best_n = int(mask.sum())

    lift = round((best_wr - overall_wr) / overall_wr, 3) if overall_wr > 0 else 0

    return {
        'range': best_range,
        'win_rate': round(best_wr, 3) if best_range else None,
        'overall_win_rate': round(overall_wr, 3),
        'lift': lift,
        'n_in_range': best_n,
    }


def compute_regime_performance(regime_vals: list[float],
                                outcomes: list[int]) -> dict:
    """Win-Rate pro Regime."""
    regime_stats = {}
    arr = np.array(regime_vals)
    out = np.array(outcomes)

    for score, name in REGIME_MAP.items():
        mask = arr == score
        if mask.sum() >= 3:
            wr = float(np.mean(out[mask]))
            regime_stats[name] = {
                'win_rate': round(wr, 3),
                'n_trades': int(mask.sum()),
            }

    if not regime_stats:
        return {'best': None, 'worst': None, 'breakdown': {}}

    best = max(regime_stats, key=lambda k: regime_stats[k]['win_rate'])
    worst = min(regime_stats, key=lambda k: regime_stats[k]['win_rate'])

    return {
        'best': best,
        'worst': worst,
        'breakdown': regime_stats,
    }


def compute_weekday_performance(weekdays: list[float],
                                 outcomes: list[int]) -> dict:
    """Win-Rate pro Wochentag."""
    wd_stats = {}
    arr = np.array([int(w) for w in weekdays])
    out = np.array(outcomes)

    for day in range(5):  # Mo-Fr
        mask = arr == day
        if mask.sum() >= 3:
            wr = float(np.mean(out[mask]))
            wd_stats[WEEKDAY_MAP[day]] = {
                'win_rate': round(wr, 3),
                'n_trades': int(mask.sum()),
            }

    if not wd_stats:
        return {'best': None, 'worst': None, 'breakdown': {}}

    best = max(wd_stats, key=lambda k: wd_stats[k]['win_rate'])
    worst = min(wd_stats, key=lambda k: wd_stats[k]['win_rate'])

    return {'best': best, 'worst': worst, 'breakdown': wd_stats}


def wilson_confidence_interval(wins: int, n: int,
                                 confidence: float = 0.95) -> tuple[float, float]:
    """Wilson-Konfidenzintervall für Win-Rate (besser als Normal-Approx bei kleinen N)."""
    if n == 0:
        return (0.0, 1.0)
    z = 1.96 if confidence == 0.95 else 1.645
    p = wins / n
    denominator = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominator
    return (round(max(0, centre - margin), 3), round(min(1, centre + margin), 3))


def compute_feature_importance_per_strategy(samples: list) -> dict:
    """Vereinfachte Feature-Importance per Strategie (Spearman + KS)."""
    if len(samples) < 20:
        return {}

    outcomes = [s['outcome'] for s in samples]
    importance = {}

    for feat in FEATURES:
        vals = [s['features'].get(feat) or 0.0 for s in samples]
        if len(set(vals)) < 3:
            importance[feat] = 0.0
            continue
        corr, pval = stats.spearmanr(vals, outcomes)
        corr_f = float(corr) if corr == corr else 0.0  # nan check
        # Wins vs Losses verteilen
        win_vals = [v for v, o in zip(vals, outcomes) if o == 1]
        loss_vals = [v for v, o in zip(vals, outcomes) if o == 0]
        if len(win_vals) >= 5 and len(loss_vals) >= 5:
            ks_stat, _ = stats.ks_2samp(win_vals, loss_vals)
            importance[feat] = round(float(ks_stat) * 0.6 + abs(corr_f) * 0.4, 4)
        else:
            importance[feat] = round(abs(corr_f), 4)

    # Normalisieren auf 0–1
    max_imp = max(importance.values()) if importance.values() else 1
    if max_imp > 0:
        importance = {k: round(v / max_imp, 4) for k, v in importance.items()}

    return dict(sorted(importance.items(), key=lambda x: -x[1]))


def compute_dna(strategy_id: str, samples: list, backtest_result: dict | None = None) -> dict:
    """
    Berechnet vollständiges DNA-Profil für eine Strategie.
    """
    outcomes = [s['outcome'] for s in samples]
    n = len(outcomes)
    wins = sum(outcomes)
    win_rate = wins / n if n > 0 else 0
    ci_lo, ci_hi = wilson_confidence_interval(wins, n)

    # Feature-Arrays
    def feat_vals(feat: str) -> list[float]:
        return [float(s['features'].get(feat) or 0.0) for s in samples]

    rsi_vals = feat_vals('rsi_at_entry')
    vol_vals = feat_vals('volume_ratio')
    vix_vals = feat_vals('vix_at_entry')
    ma50_vals = feat_vals('ma50_distance')
    regime_vals = feat_vals('hmm_regime')
    weekday_vals = feat_vals('day_of_week')

    # Optimal Ranges
    rsi_opt = compute_optimal_range(rsi_vals, outcomes)
    vix_opt = compute_optimal_range(vix_vals, outcomes)
    ma50_opt = compute_optimal_range(ma50_vals, outcomes)
    vol_opt = compute_optimal_range(vol_vals, outcomes)

    # Regime + Wochentag
    regime_perf = compute_regime_performance(regime_vals, outcomes)
    weekday_perf = compute_weekday_performance(weekday_vals, outcomes)

    # Feature Importance (pro Strategie)
    feat_imp = compute_feature_importance_per_strategy(samples)

    # Backtest-Ergebnisse einbinden
    backtest_summary = {}
    if backtest_result and backtest_result.get('status') == 'ok':
        ov = backtest_result.get('overall', {})
        backtest_summary = {
            'profit_factor': ov.get('profit_factor'),
            'sharpe_ratio': ov.get('sharpe_ratio'),
            'max_drawdown_pct': ov.get('max_drawdown_pct'),
            'consistency': backtest_result.get('walk_forward_consistency'),
            'verdict': backtest_result.get('verdict'),
        }

    # Datenqualität bewerten
    data_quality = _assess_data_quality(n, samples)

    # Optimale Filter-Bedingungen (für DNA Gate)
    gate_conditions = _build_gate_conditions(rsi_opt, vix_opt, ma50_opt, vol_opt,
                                              regime_perf, weekday_perf)

    dna = {
        'strategy_id': strategy_id,
        'n_samples': n,
        'n_real': sum(1 for s in samples if s.get('source') == 'real'),
        'win_rate': round(win_rate, 3),
        'confidence_interval': [ci_lo, ci_hi],
        'data_quality': data_quality,
        'optimal_rsi': rsi_opt,
        'optimal_vix': vix_opt,
        'optimal_ma50': ma50_opt,
        'optimal_volume': vol_opt,
        'regime_performance': regime_perf,
        'weekday_performance': weekday_perf,
        'feature_importance': feat_imp,
        'backtest': backtest_summary,
        'gate_conditions': gate_conditions,
        'computed_at': datetime.now(timezone.utc).isoformat(),
    }

    return dna


def _assess_data_quality(n: int, samples: list) -> str:
    """Bewertet Zuverlässigkeit des DNA-Profils."""
    n_real = sum(1 for s in samples if s.get('source') == 'real')
    if n_real >= 50:
        return 'HIGH'
    elif n_real >= 20:
        return 'MEDIUM'
    elif n >= 50:
        return 'LOW_SYNTHETIC'  # Nur Backtest-Daten
    else:
        return 'INSUFFICIENT'


def _build_gate_conditions(rsi_opt, vix_opt, ma50_opt, vol_opt,
                            regime_perf, weekday_perf) -> dict:
    """Baut konkrete Gate-Bedingungen aus DNA-Daten."""
    conditions = {}

    # RSI-Gate
    if rsi_opt.get('range') and (rsi_opt.get('lift') or 0) > 0.05:
        conditions['rsi'] = {
            'min': rsi_opt['range'][0],
            'max': rsi_opt['range'][1],
            'lift': rsi_opt['lift'],
            'required': False,  # Soft constraint
        }

    # VIX-Gate
    if vix_opt.get('range') and (vix_opt.get('lift') or 0) > 0.05:
        conditions['vix'] = {
            'min': vix_opt['range'][0],
            'max': vix_opt['range'][1],
            'lift': vix_opt['lift'],
            'required': False,
        }

    # MA50-Gate
    if ma50_opt.get('range') and (ma50_opt.get('lift') or 0) > 0.05:
        conditions['ma50_distance'] = {
            'min': ma50_opt['range'][0],
            'max': ma50_opt['range'][1],
            'lift': ma50_opt['lift'],
            'required': False,
        }

    # Regime-Gate
    if regime_perf.get('best'):
        conditions['regime'] = {
            'preferred': [regime_perf['best']],
            'avoid': [regime_perf['worst']] if regime_perf.get('worst') else [],
            'required': False,
        }

    # Weekday-Gate
    if weekday_perf.get('worst'):
        conditions['weekday'] = {
            'best': weekday_perf['best'],
            'avoid': weekday_perf['worst'],
            'required': False,
        }

    return conditions


# ── DNA Gate ──────────────────────────────────────────────────────────────────

def check_dna_gate(strategy_id: str, features: dict) -> dict:
    """
    Prüft ob aktuelle Marktbedingungen im DNA-optimalen Bereich liegen.
    Gibt Score 0–100 + konkrete Verletzungen zurück.
    """
    if not DNA_FILE.exists():
        return {'score': 50, 'violations': [], 'status': 'NO_DNA'}

    all_dna = json.loads(DNA_FILE.read_text())
    if strategy_id not in all_dna:
        return {'score': 50, 'violations': [], 'status': 'NO_DNA_FOR_STRATEGY'}

    dna = all_dna[strategy_id]
    gates = dna.get('gate_conditions', {})
    quality = dna.get('data_quality', 'INSUFFICIENT')

    if quality == 'INSUFFICIENT':
        return {'score': 50, 'violations': [], 'status': 'INSUFFICIENT_DATA',
                'note': f'Nur {dna["n_samples"]} Samples — DNA noch nicht zuverlässig'}

    violations = []
    bonuses = []
    base_score = 50

    # RSI-Check
    if 'rsi' in gates:
        rsi = features.get('rsi_at_entry', 50)
        lo, hi = gates['rsi']['min'], gates['rsi']['max']
        if lo <= rsi <= hi:
            bonuses.append(f'RSI {rsi:.0f} im Optimal-Range [{lo:.0f}–{hi:.0f}] +{gates["rsi"]["lift"]:.0%}')
            base_score += gates['rsi']['lift'] * 50
        else:
            violations.append(f'RSI {rsi:.0f} außerhalb Optimal-Range [{lo:.0f}–{hi:.0f}]')
            base_score -= 10

    # VIX-Check
    if 'vix' in gates:
        vix = features.get('vix_at_entry', 22)
        lo, hi = gates['vix']['min'], gates['vix']['max']
        if lo <= vix <= hi:
            bonuses.append(f'VIX {vix:.1f} im Optimal-Range [{lo:.0f}–{hi:.0f}]')
            base_score += gates['vix']['lift'] * 30
        else:
            violations.append(f'VIX {vix:.1f} außerhalb Optimal-Range [{lo:.0f}–{hi:.0f}]')
            base_score -= 8

    # MA50-Check
    if 'ma50_distance' in gates:
        ma50 = features.get('ma50_distance', 0)
        lo, hi = gates['ma50_distance']['min'], gates['ma50_distance']['max']
        if lo <= ma50 <= hi:
            bonuses.append(f'MA50-Distanz {ma50:+.1f}% im Optimum')
            base_score += gates['ma50_distance']['lift'] * 40
        else:
            violations.append(f'MA50-Distanz {ma50:+.1f}% außerhalb [{lo:+.1f}%–{hi:+.1f}%]')
            base_score -= 12

    # Regime-Check
    if 'regime' in gates:
        regime_names = {0.0: 'BULL', 1.0: 'NEUTRAL', 2.0: 'RISK_OFF', 3.0: 'CRASH'}
        current_regime = regime_names.get(features.get('hmm_regime', 1.0), 'NEUTRAL')
        preferred = gates['regime']['preferred']
        avoid = gates['regime']['avoid']
        if current_regime in preferred:
            bonuses.append(f'Regime {current_regime} = optimal für {strategy_id}')
            base_score += 15
        elif current_regime in avoid:
            violations.append(f'Regime {current_regime} = schlechtestes Regime für {strategy_id}')
            base_score -= 20

    final_score = max(0, min(100, round(base_score)))
    status = 'GREEN' if final_score >= 65 else 'YELLOW' if final_score >= 45 else 'RED'

    return {
        'score': final_score,
        'status': status,
        'violations': violations,
        'bonuses': bonuses,
        'data_quality': quality,
        'expected_win_rate': dna.get('win_rate'),
        'confidence_interval': dna.get('confidence_interval'),
    }


# ── Haupt-Funktion ────────────────────────────────────────────────────────────

def compute_all_dnas() -> dict:
    """Berechnet DNA für alle Strategien mit ausreichend Daten."""
    print("[Strategy DNA] Lade Daten...")
    strategy_samples = load_strategy_samples()
    backtest_results = load_backtest_results()

    all_dna = {}
    print(f"  {len(strategy_samples)} Strategien gefunden")

    for strat_id, samples in sorted(strategy_samples.items()):
        if len(samples) < 15:
            print(f"  ⏭️  {strat_id}: nur {len(samples)} Samples — übersprungen")
            continue

        print(f"  🧬 {strat_id}: {len(samples)} Samples...", end=' ')
        bt_result = backtest_results.get(strat_id)
        dna = compute_dna(strat_id, samples, bt_result)
        all_dna[strat_id] = dna

        quality_icon = {'HIGH': '🟢', 'MEDIUM': '🟡', 'LOW_SYNTHETIC': '🟠',
                        'INSUFFICIENT': '🔴'}.get(dna['data_quality'], '⚫')
        print(f"WR={dna['win_rate']:.0%} CI=[{dna['confidence_interval'][0]:.0%}–{dna['confidence_interval'][1]:.0%}] {quality_icon}{dna['data_quality']}")

    DNA_FILE.write_text(json.dumps(all_dna, indent=2, ensure_ascii=False))
    print(f"\n  ✅ {len(all_dna)} DNA-Profile gespeichert → data/strategy_dna.json")
    return all_dna


# ── Formatierter Report ───────────────────────────────────────────────────────

def print_dna(dna: dict):
    """Zeigt DNA-Profil einer Strategie."""
    sid = dna['strategy_id']
    quality_icon = {'HIGH': '🟢', 'MEDIUM': '🟡', 'LOW_SYNTHETIC': '🟠',
                    'INSUFFICIENT': '🔴'}.get(dna['data_quality'], '⚫')

    print(f"\n{'='*55}")
    print(f"🧬 Strategy DNA — {sid}")
    print(f"{'='*55}")
    print(f"Datenqualität: {quality_icon} {dna['data_quality']} "
          f"({dna['n_samples']} Samples, {dna['n_real']} echt)")
    ci = dna['confidence_interval']
    print(f"Win-Rate: {dna['win_rate']:.0%} [CI: {ci[0]:.0%}–{ci[1]:.0%}]")

    # Optimale Ranges
    print(f"\n📐 Optimale Einstiegsbedingungen:")
    for key, label in [('optimal_rsi', 'RSI'), ('optimal_vix', 'VIX'),
                        ('optimal_ma50', 'MA50-Distanz'), ('optimal_volume', 'Volume-Ratio')]:
        opt = dna.get(key, {})
        if opt.get('range'):
            lift_str = f'+{opt["lift"]:.0%}' if opt.get("lift") else ''
            print(f"  {label:14s}: {opt['range'][0]:.1f}–{opt['range'][1]:.1f} "
                  f"(WR {opt['win_rate']:.0%} {lift_str} vs Basis {opt['overall_win_rate']:.0%})")

    # Regime
    regime = dna.get('regime_performance', {})
    if regime.get('best'):
        print(f"\n🌊 Regime-Performance:")
        for r_name, r_stats in regime.get('breakdown', {}).items():
            icon = '🏆' if r_name == regime['best'] else ('⚠️ ' if r_name == regime['worst'] else '  ')
            print(f"  {icon} {r_name:10s}: WR {r_stats['win_rate']:.0%} ({r_stats['n_trades']} Trades)")

    # Wochentag
    wd = dna.get('weekday_performance', {})
    if wd.get('best'):
        print(f"\n📅 Wochentag: Bester={wd['best']}, Meiden={wd.get('worst','?')}")

    # Feature Importance
    feat_imp = dna.get('feature_importance', {})
    if feat_imp:
        print(f"\n⚖️  Feature-Wichtigkeit für {sid}:")
        for feat, imp in list(feat_imp.items())[:5]:
            bar = '█' * int(imp * 15) + '░' * (15 - int(imp * 15))
            labels = {'rsi_at_entry': 'RSI', 'volume_ratio': 'Volume',
                      'vix_at_entry': 'VIX', 'ma50_distance': 'MA50',
                      'hmm_regime': 'Regime', 'sector_momentum': 'Sektor',
                      'atr_pct_at_entry': 'ATR%', 'day_of_week': 'Wochentag',
                      'spy_5d_return': 'SPY 5d'}
            print(f"  {labels.get(feat,feat):12s}: {imp:.2f} {bar}")

    # Backtest
    bt = dna.get('backtest', {})
    if bt:
        pf = bt.get('profit_factor')
        sh = bt.get('sharpe_ratio')
        dd = bt.get('max_drawdown_pct')
        cons = bt.get('consistency')
        pf_str = f"{pf:.2f}" if pf is not None else "?"
        sh_str = f"{sh:.2f}" if sh is not None else "?"
        dd_str = f"{dd:.1f}%" if dd is not None else "?"
        cons_str = f"{cons:.0%}" if cons is not None else "?"
        print(f"\n📊 Backtest: PF={pf_str} | Sharpe={sh_str} | MaxDD={dd_str} | Konsistenz={cons_str}")

    # Gate-Bedingungen
    gates = dna.get('gate_conditions', {})
    print(f"\n🚦 DNA Gate ({len(gates)} Bedingungen aktiv):")
    if gates:
        for cond, details in gates.items():
            if 'min' in details:
                print(f"  {cond}: [{details['min']:.1f}–{details['max']:.1f}]")
            elif 'preferred' in details:
                print(f"  {cond}: Bevorzugt {details['preferred']}, Meiden {details.get('avoid',[])}")
            else:
                print(f"  {cond}: Bestes={details.get('best')}, Meiden={details.get('avoid')}")
    else:
        print("  (keine Bedingungen mit ausreichend Lift)")

    print(f"{'='*55}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    args = sys.argv[1:]

    if '--show' in args:
        idx = args.index('--show')
        strat = args[idx + 1] if len(args) > idx + 1 else None
        if strat and DNA_FILE.exists():
            all_dna = json.loads(DNA_FILE.read_text())
            if strat in all_dna:
                print_dna(all_dna[strat])
            else:
                print(f"❌ Keine DNA für {strat} — verfügbar: {list(all_dna.keys())}")
        else:
            print("Erst: python3.13 strategy_dna.py (ohne Argumente)")

    elif '--check' in args:
        idx = args.index('--check')
        try:
            strat = args[idx + 1]
            rsi = float(args[idx + 2]) if len(args) > idx + 2 else 50.0
            vix = float(args[idx + 3]) if len(args) > idx + 3 else 22.0
        except (IndexError, ValueError):
            print("Usage: --check STRATEGY_ID [RSI] [VIX]")
            sys.exit(1)
        features = {'rsi_at_entry': rsi, 'vix_at_entry': vix}
        result = check_dna_gate(strat, features)
        print(f"\nDNA Gate Check: {strat} | RSI={rsi} VIX={vix}")
        print(f"Score: {result['score']}/100 | Status: {result['status']}")
        if result.get('violations'):
            print("Verletzungen:", ' | '.join(result['violations']))
        if result.get('bonuses'):
            print("Bonuses:     ", ' | '.join(result['bonuses']))

    elif '--gate-check' in args:
        # Alle offenen Positionen gegen DNA-Profil prüfen
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        conn = sqlite3.connect(str(DB))
        conn.row_factory = sqlite3.Row
        positions = conn.execute("""
            SELECT ticker, strategy, rsi_at_entry, vix_at_entry, ma50_distance,
                   volume_ratio, hmm_regime
            FROM paper_portfolio WHERE status = 'OPEN'
              AND rsi_at_entry IS NOT NULL
        """).fetchall()
        conn.close()

        print(f"\n🚦 DNA Gate Check — {len(positions)} offene Positionen")
        print("-" * 60)
        for pos in positions:
            features = {
                'rsi_at_entry': pos['rsi_at_entry'],
                'vix_at_entry': pos['vix_at_entry'],
                'ma50_distance': pos['ma50_distance'],
                'volume_ratio': pos['volume_ratio'],
                'hmm_regime': pos['hmm_regime'] or 1.0,
            }
            result = check_dna_gate(pos['strategy'], features)
            icon = {'GREEN': '🟢', 'YELLOW': '🟡', 'RED': '🔴'}.get(result['status'], '⚫')
            print(f"{icon} {pos['ticker']:12s} [{pos['strategy']:6s}] "
                  f"Score={result['score']:3d}/100 | {result.get('note','') or ''}")
            if result.get('violations'):
                for v in result['violations'][:2]:
                    print(f"   ⚠️  {v}")

    else:
        # Default: alle DNAs berechnen
        all_dna = compute_all_dnas()

        # Übersicht
        print(f"\n{'='*55}")
        print("Strategy DNA — Übersicht")
        print(f"{'='*55}")
        print(f"{'Strategie':10s} {'WR':>5} {'CI':>14} {'Top Feature':>16} {'Qualität':>12}")
        print("-" * 55)
        for sid, dna in sorted(all_dna.items(), key=lambda x: -x[1]['win_rate']):
            ci = dna['confidence_interval']
            top_feat = list(dna['feature_importance'].keys())[0] if dna['feature_importance'] else '?'
            feat_labels = {'rsi_at_entry': 'RSI', 'volume_ratio': 'Volume',
                           'vix_at_entry': 'VIX', 'ma50_distance': 'MA50',
                           'hmm_regime': 'Regime', 'sector_momentum': 'Sektor',
                           'atr_pct_at_entry': 'ATR%', 'day_of_week': 'Wochentag',
                           'spy_5d_return': 'SPY 5d'}
            quality_icon = {'HIGH': '🟢', 'MEDIUM': '🟡', 'LOW_SYNTHETIC': '🟠',
                            'INSUFFICIENT': '🔴'}.get(dna['data_quality'], '⚫')
            print(f"{sid:10s} {dna['win_rate']:>5.0%} "
                  f"[{ci[0]:.0%}–{ci[1]:.0%}] "
                  f"{feat_labels.get(top_feat, top_feat):>16} "
                  f"{quality_icon}{dna['data_quality']:>10}")
