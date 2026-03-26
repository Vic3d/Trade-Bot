"""
trademind/execution/simulator.py — Realistischer Execution-Simulator

Modelliert Spread, Slippage und Handelskosten (Trade Republic) für Paper Trading.

Liquiditätsklassen:
  - large_cap:  Spread 0.05%, Slippage-Mult 0.005
  - mid_cap:    Spread 0.10%, Slippage-Mult 0.010
  - small_cap:  Spread 0.20%, Slippage-Mult 0.020
  - intl:       Spread 0.15%, Slippage-Mult 0.015

VIX-Multiplikator: bei VIX 20 → 1x, bei VIX 40 → 2x
"""

# ── Liquiditäts-Klassen ───────────────────────────────────────────────────────
LIQUIDITY: dict[str, dict] = {
    'large_cap': {
        'tickers': ['NVDA', 'MSFT', 'PLTR', 'BABA', 'SHEL.L'],
        'spread_pct': 0.05,     # Spread als % des Preises (je Seite: spread/2)
        'slippage_mult': 0.005, # Slippage = price * mult * (vix/20)
    },
    'mid_cap': {
        'tickers': ['OXY', 'FRO', 'DHT', 'EQNR.OL', 'TTE.PA', 'CCL', 'AG', 'PAAS', 'WPM'],
        'spread_pct': 0.10,
        'slippage_mult': 0.010,
    },
    'small_cap': {
        'tickers': ['EXK', 'HL', 'S.TO', 'MP'],
        'spread_pct': 0.20,
        'slippage_mult': 0.020,
    },
    'intl': {
        'tickers': ['DR0.DE', 'RHM.DE', 'BAYN.DE', 'RIO.L', 'BHP.L', '9988.HK', '0700.HK'],
        'spread_pct': 0.15,
        'slippage_mult': 0.015,
    },
}

# Standard-Klasse für unbekannte Ticker
_DEFAULT_CLASS = 'mid_cap'
_COMMISSION = 1.0  # Trade Republic Pauschalgebühr in EUR


def get_liquidity_class(ticker: str) -> tuple[str, dict]:
    """Gibt die Liquiditätsklasse und -parameter für einen Ticker zurück.

    Falls der Ticker nicht in einer Klasse gefunden wird, wird 'mid_cap' als
    Default verwendet.

    Returns:
        (class_name, params_dict)
    """
    ticker_up = ticker.upper()
    for cls_name, params in LIQUIDITY.items():
        if ticker_up in [t.upper() for t in params['tickers']]:
            return cls_name, params
    return _DEFAULT_CLASS, LIQUIDITY[_DEFAULT_CLASS]


def simulate_fill(price: float, side: str, ticker: str, vix: float = 20.0) -> dict:
    """Simuliert einen realistischen Order-Fill inkl. Spread, Slippage und Gebühr.

    Modell:
        - Spread: Der halbe Spread-% wird je Seite auf den Mid-Price aufgeschlagen
          (BUY → teurer, SELL → günstiger).
        - Slippage: proportional zum VIX. Bei VIX=20 → 1x Basis-Slippage,
          bei VIX=40 → 2x. Immer ungünstig (BUY teurer, SELL billiger).
        - Commission: pauschal 1€ (Trade Republic).

    Args:
        price:  Mid-/Yahoo-Kurs in EUR.
        side:   'BUY' oder 'SELL'.
        ticker: Ticker-Symbol (z.B. 'OXY', 'NVDA').
        vix:    Aktueller VIX-Wert (default 20).

    Returns:
        {
            'fill_price':     float,  # realistischer Fill-Preis (ohne Gebühr)
            'spread_cost':    float,  # EUR-Kosten durch Spread (pro Aktie)
            'slippage_cost':  float,  # EUR-Kosten durch Slippage (pro Aktie)
            'commission':     float,  # EUR pauschal (1.00€ TR Gebühr)
            'total_cost':     float,  # spread + slippage + commission (pro Trade)
            'effective_price': float, # fill_price ± commission/1 (alles eingepreist)
            'liquidity_class': str,   # Liquiditätsklasse des Tickers
        }
    """
    if price <= 0:
        raise ValueError(f"Ungültiger Preis: {price}")

    side_up = side.upper()
    if side_up not in ('BUY', 'SELL'):
        raise ValueError(f"Ungültige Seite: {side} (erwartet: BUY oder SELL)")

    cls_name, params = get_liquidity_class(ticker)

    # ── Spread ────────────────────────────────────────────────────────────────
    # Halber Spread je Seite; BUY = teurer, SELL = billiger
    half_spread_eur = price * (params['spread_pct'] / 100.0) / 2.0

    # ── Slippage ──────────────────────────────────────────────────────────────
    # Basis-Slippage × VIX-Multiplikator
    # slippage_mult ist in % (wie spread_pct), z.B. 0.01 = 0.01% pro Seite
    vix_mult = max(vix, 1.0) / 20.0  # Bei VIX 20 → 1.0, VIX 40 → 2.0
    slippage_eur = price * (params['slippage_mult'] / 100.0) * vix_mult

    # ── Richtungsabhängige Fill-Preise ────────────────────────────────────────
    if side_up == 'BUY':
        fill_price = price + half_spread_eur + slippage_eur
    else:  # SELL
        fill_price = price - half_spread_eur - slippage_eur

    # Gerundet auf 4 Dezimalstellen (realistisch für Aktienpreise)
    fill_price = round(fill_price, 4)
    spread_cost = round(half_spread_eur, 4)
    slippage_cost = round(slippage_eur, 4)

    # Total cost = Spread + Slippage + Gebühr (absolute EUR-Werte pro Trade)
    total_cost = round(spread_cost + slippage_cost + _COMMISSION, 4)

    # Effective price = der wahre wirtschaftliche Einstandspreis (inkl. Gebühr)
    if side_up == 'BUY':
        effective_price = round(fill_price + _COMMISSION, 4)
    else:
        effective_price = round(fill_price - _COMMISSION, 4)

    return {
        'fill_price':     fill_price,
        'spread_cost':    spread_cost,
        'slippage_cost':  slippage_cost,
        'commission':     _COMMISSION,
        'total_cost':     total_cost,
        'effective_price': effective_price,
        'liquidity_class': cls_name,
    }


def format_fill_line(fill: dict, shares: float = 1.0) -> str:
    """Formatiert den Fill als lesbaren Output-String (per Trade, alle Shares).

    Beispiel: "Fill: 55.87€ (inkl. 2.52€ Spread + 0.34€ Slippage + 1€ Gebühr)"
    """
    spread_total   = round(fill['spread_cost']   * shares, 2)
    slippage_total = round(fill['slippage_cost'] * shares, 2)
    return (
        f"Fill: {fill['fill_price']:.2f}€ "
        f"(inkl. {spread_total:.2f}€ Spread + "
        f"{slippage_total:.2f}€ Slippage + "
        f"{fill['commission']:.0f}€ Gebühr)"
    )
