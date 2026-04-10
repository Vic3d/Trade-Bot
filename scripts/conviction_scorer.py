# conviction_scorer.py — Shim
# Leitet alle Imports an scripts/intelligence/conviction_scorer.py weiter.
import importlib.util, sys
from pathlib import Path

_real = Path(__file__).resolve().parent / 'intelligence' / 'conviction_scorer.py'
_spec = importlib.util.spec_from_file_location('_conviction_scorer_real', _real)
_mod  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

calculate_conviction    = _mod.calculate_conviction
check_entry_allowed     = _mod.check_entry_allowed
_get_current_regime     = _mod._get_current_regime
_get_current_vix        = _mod._get_current_vix
get_conviction_threshold = _mod.get_conviction_threshold
score_all_open_trades   = _mod.score_all_open_trades
calibrate_weights       = _mod.calibrate_weights
