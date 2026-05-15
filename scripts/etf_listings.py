#!/usr/bin/env python3
"""
etf_listings.py — Phase 45be (Victor 2026-05-15).

Bug GDX (Trade #131): Bare-Ticker "GDX" ohne ISIN-Pin → yfinance loest auf
US-GDX (US92189F1066, ~$94/Aktie) auf. In Deutschland (Trade Republic /
finanzen.net) wird unter "GDX" aber primaer der UCITS-Fonds A12CCL
(IE00BQQP9F84, ~$109/Aktie) gehandelt — gleicher Index, unterschiedlicher
Unit-Preis. Folge: Position systematisch falsch bewertet im Vergleich zu
dem, was der reale Broker zeigt.

Loesung:
  - Liste bekannter Listing-ambiguer ETFs (Symbol → US-ISIN + UCITS-ISIN).
  - check_etf_listing() warnt bei Bare-Ticker ohne ISIN-Annotation.
  - Wird im autonomous_scanner aufgerufen → solche Tickers werden bis zur
    expliziten ISIN-Pinnung im Strategie-Eintrag ausgelassen.

So bleibt der Bug VISIBLE und blockiert, statt im Hintergrund weiterzulaufen.
"""
from __future__ import annotations

# Bekannte Listing-Ambiguitäten: gleiches Symbol, mehrere reale Fonds.
# Format: ticker → {'us': ISIN_US, 'ucits': ISIN_EU, 'note': str}
AMBIGUOUS_ETFS: dict[str, dict[str, str]] = {
    'GDX':  {'us': 'US92189F1066', 'ucits': 'IE00BQQP9F84',
             'note': 'VanEck Gold Miners — US-Listing ~$94 vs UCITS ~$109'},
    'GDXJ': {'us': 'US92189F7642', 'ucits': 'IE00BQQP9G91',
             'note': 'VanEck Junior Gold Miners — US vs UCITS Variante'},
    'SLV':  {'us': 'US46428Q1094', 'ucits': 'IE00B4NCWG09',
             'note': 'iShares Silver Trust (US, kein UCITS) vs WisdomTree Silver UCITS'},
    'GLD':  {'us': 'US78463V1070', 'ucits': 'IE00B4ND3602',
             'note': 'SPDR Gold Trust (US) vs Invesco Physical Gold UCITS'},
    'COPX': {'us': 'US37954Y8553', 'ucits': 'IE00BHWYHR71',
             'note': 'Global X Copper Miners — US vs UCITS'},
    'EEM':  {'us': 'US4642872349', 'ucits': 'IE00B4L5YC18',
             'note': 'iShares MSCI Emerging Markets — US vs UCITS Core'},
    'VWO':  {'us': 'US9220428588', 'ucits': 'IE00B3VVMM84',
             'note': 'Vanguard FTSE Emerging Markets — US vs UCITS'},
    'XLE':  {'us': 'US81369Y5069', 'ucits': 'IE00B4MGFW48',
             'note': 'Energy Select SPDR — US vs SPDR S&P US Energy UCITS'},
    'XLF':  {'us': 'US81369Y6059', 'ucits': 'IE00B4MGFB60',
             'note': 'Financial Select SPDR — US vs UCITS'},
    'TAN':  {'us': 'US37954Y8702', 'ucits': 'IE00B5BYK573',
             'note': 'Invesco Solar — US vs iShares Global Clean Energy UCITS Naehe'},
    'ARKG': {'us': 'US00214Q3020', 'ucits': 'IE000O5M6XO1',
             'note': 'ARK Genomic Revolution — US vs UCITS Variante'},
}


def check_etf_listing(ticker: str, strategy_meta: dict) -> tuple[bool, str]:
    """
    Returns (is_ok, message).
    is_ok=False → Ticker bis zur ISIN-Pinnung im Strategie-Eintrag skippen.

    strategy_meta sollte ein 'isin'-Feld oder ein 'isin_map' (ticker→isin)
    enthalten, wenn ein ambiguer ETF gehandelt werden soll.
    """
    t = (ticker or '').upper()
    if t not in AMBIGUOUS_ETFS:
        return True, 'ok'

    info = AMBIGUOUS_ETFS[t]
    # Akzeptierte Pinnung: 'isin' (single ticker) oder 'isin_map' (mehrere)
    pinned = None
    if isinstance(strategy_meta, dict):
        if strategy_meta.get('isin'):
            pinned = strategy_meta['isin']
        imap = strategy_meta.get('isin_map') or {}
        if isinstance(imap, dict) and imap.get(t):
            pinned = imap[t]

    if not pinned:
        return False, (
            f"AMBIGUOUS_ETF: '{t}' hat zwei reale Fonds-Varianten "
            f"(US: {info['us']}, UCITS: {info['ucits']}). "
            f"Strategie muss 'isin_map' setzen, sonst wird falscher Fonds "
            f"getrackt. Hinweis: {info['note']}."
        )

    # Pinnung gegen bekannte ISINs verifizieren
    if pinned not in (info['us'], info['ucits']):
        return False, (
            f"AMBIGUOUS_ETF: '{t}' isin='{pinned}' ist weder US ({info['us']}) "
            f"noch UCITS ({info['ucits']}). Tippfehler?"
        )

    return True, f"{t} pinned to {pinned}"


def audit_strategies(strats: dict) -> list[dict]:
    """Sucht alle ambigue ETFs ohne ISIN-Pin in strategies.json."""
    issues = []
    for sid, s in (strats or {}).items():
        if not isinstance(s, dict):
            continue
        for t in s.get('tickers', []) or []:
            if isinstance(t, (list, tuple)):
                t = t[0] if t else ''
            ok, msg = check_etf_listing(str(t), s)
            if not ok:
                issues.append({'strategy': sid, 'ticker': str(t).upper(),
                               'message': msg})
    return issues


def main() -> int:
    """CLI: scant strategies.json und gibt alle Listing-Konflikte aus."""
    import json, os, sys
    from pathlib import Path
    ws = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
    f = ws / 'data' / 'strategies.json'
    if not f.exists():
        print('strategies.json fehlt'); return 1
    s = json.loads(f.read_text(encoding='utf-8'))
    issues = audit_strategies(s)
    if not issues:
        print('OK: keine ambiguen ETF-Listings ohne ISIN-Pin gefunden.')
        return 0
    print(f'⚠️  {len(issues)} Konflikte:')
    for i in issues:
        print(f"  [{i['strategy']:25}] {i['ticker']:6} → {i['message']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
