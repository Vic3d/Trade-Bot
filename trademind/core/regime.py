"""
trademind/core/regime.py — Marktregime laden

Usage:
    from trademind.core.regime import get_regime

    regime = get_regime()
    print(regime['regime'])          # z.B. 'TRENDING_UP'
    print(regime.get('adx', 'N/A'))
"""
import json
from pathlib import Path
from trademind.core.config import MEMORY_DIR

REGIME_FILE = MEMORY_DIR / "market-regime.json"


def get_regime() -> dict:
    """
    Liest das aktuelle Marktregime aus market-regime.json.

    Erwartete Keys:
        regime           str  — z.B. 'TRENDING_UP', 'RANGING', 'VOLATILE'
        adx              float (optional)
        trend_direction  str  (optional) — 'bullish' | 'bearish' | 'neutral'
        updated          str  (optional) — ISO-Timestamp

    Gibt leeres Dict mit regime='UNKNOWN' zurück wenn Datei fehlt.
    """
    try:
        with open(REGIME_FILE) as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        return {"regime": "UNKNOWN", "note": "market-regime.json not found"}
    except json.JSONDecodeError as e:
        return {"regime": "UNKNOWN", "note": f"JSON parse error: {e}"}
    except Exception as e:
        return {"regime": "UNKNOWN", "note": str(e)}
