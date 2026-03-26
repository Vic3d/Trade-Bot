"""
trademind/core/vix.py — VIX holen und klassifizieren

Usage:
    from trademind.core.vix import get_vix, get_vix_zone

    vix  = get_vix()            # float, z.B. 23.4
    zone = get_vix_zone(vix)    # 'low' | 'medium' | 'high' | 'extreme'
"""
import json
from urllib.request import urlopen, Request
from urllib.error import URLError


# Letzter bekannter VIX als Fallback (wird bei erfolgreichem Fetch nicht genutzt)
_FALLBACK_VIX = 20.0


def get_vix() -> float:
    """Aktuellen VIX von Yahoo Finance laden."""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=1d"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urlopen(req, timeout=10).read())
        price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return float(price)
    except Exception as e:
        print(f"  ⚠️  VIX fetch failed: {e} — using fallback {_FALLBACK_VIX}")
        return _FALLBACK_VIX


def get_vix_zone(vix: float) -> str:
    """
    VIX → Zone klassifizieren.

    Zonen:
        low      VIX < 20
        medium   VIX 20-25
        high     VIX 25-35
        extreme  VIX > 35
    """
    if vix < 20:
        return "low"
    if vix < 25:
        return "medium"
    if vix < 35:
        return "high"
    return "extreme"
