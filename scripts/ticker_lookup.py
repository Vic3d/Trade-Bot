#!/usr/bin/env python3
"""
ticker_lookup.py — Ticker → {name, wkn, isin, currency, exchange} Mapping.

Für Discord-Antworten: Victor will immer voller Name + Ticker + WKN.

Database: hardcoded für bekannte Tickers (sicher), Fallback für unbekannte:
nur Ticker zeigen mit Hinweis "WKN unbekannt".

Usage:
  from ticker_lookup import lookup
  info = lookup('XOM')
  # → {'name': 'Exxon Mobil', 'wkn': '852549', 'isin': 'US30231G1022',
  #    'currency': 'USD', 'exchange': 'NYSE'}
"""
from __future__ import annotations

# Hardcoded WKN/ISIN-Datenbank für aktiv getradete Tickers
# Quelle: WKN-Datenbanken, manuelle Verifikation
TICKERS = {
    # ── US Energy ────────────────────────────────────────────────────────
    'XOM':       {'name': 'Exxon Mobil',         'wkn': '852549', 'isin': 'US30231G1022', 'currency': 'USD', 'exchange': 'NYSE'},
    'CVX':       {'name': 'Chevron',             'wkn': '852552', 'isin': 'US1667641005', 'currency': 'USD', 'exchange': 'NYSE'},
    'OXY':       {'name': 'Occidental Petroleum','wkn': '851921', 'isin': 'US6745991058', 'currency': 'USD', 'exchange': 'NYSE'},
    'COP':       {'name': 'ConocoPhillips',      'wkn': '575302', 'isin': 'US20825C1045', 'currency': 'USD', 'exchange': 'NYSE'},
    'APA':       {'name': 'APA Corp',            'wkn': 'A2QQXG', 'isin': 'US03743Q1085', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'VLO':       {'name': 'Valero Energy',       'wkn': '908683', 'isin': 'US91913Y1001', 'currency': 'USD', 'exchange': 'NYSE'},
    'FRO':       {'name': 'Frontline plc',       'wkn': 'A0ERFB', 'isin': 'BMG3682E1921', 'currency': 'USD', 'exchange': 'NYSE'},
    'EQNR.OL':   {'name': 'Equinor ASA',         'wkn': '675213', 'isin': 'NO0010096985', 'currency': 'NOK', 'exchange': 'XOSL'},
    'TTE.PA':    {'name': 'TotalEnergies',       'wkn': '850727', 'isin': 'FR0000120271', 'currency': 'EUR', 'exchange': 'XPAR'},
    'BP.L':      {'name': 'BP plc',              'wkn': '850517', 'isin': 'GB0007980591', 'currency': 'GBP', 'exchange': 'XLON'},
    'SHEL.L':    {'name': 'Shell plc',           'wkn': 'A3C99G', 'isin': 'GB00BP6MXD84', 'currency': 'GBP', 'exchange': 'XLON'},
    'ENI.MI':    {'name': 'Eni S.p.A.',          'wkn': '897791', 'isin': 'IT0003132476', 'currency': 'EUR', 'exchange': 'XMIL'},
    'OMV.VI':    {'name': 'OMV AG',              'wkn': '874341', 'isin': 'AT0000743059', 'currency': 'EUR', 'exchange': 'XWBO'},
    'REP.MC':    {'name': 'Repsol',              'wkn': '876845', 'isin': 'ES0173516115', 'currency': 'EUR', 'exchange': 'XMAD'},

    # ── US Tech / AI ────────────────────────────────────────────────────
    'NVDA':      {'name': 'NVIDIA',              'wkn': '918422', 'isin': 'US67066G1040', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'MSFT':      {'name': 'Microsoft',           'wkn': '870747', 'isin': 'US5949181045', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'AAPL':      {'name': 'Apple',               'wkn': '865985', 'isin': 'US0378331005', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'GOOGL':     {'name': 'Alphabet (Class A)',  'wkn': 'A14Y6F', 'isin': 'US02079K3059', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'GOOG':      {'name': 'Alphabet (Class C)',  'wkn': 'A14Y6H', 'isin': 'US02079K1079', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'AMZN':      {'name': 'Amazon',              'wkn': '906866', 'isin': 'US0231351067', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'META':      {'name': 'Meta Platforms',      'wkn': 'A1JWVX', 'isin': 'US30303M1027', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'TSLA':      {'name': 'Tesla',               'wkn': 'A1CX3T', 'isin': 'US88160R1014', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'AVGO':      {'name': 'Broadcom',            'wkn': 'A2JG9Z', 'isin': 'US11135F1012', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'AMD':       {'name': 'Advanced Micro Devices','wkn': '863186', 'isin': 'US0079031078', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'INTC':      {'name': 'Intel',               'wkn': '855681', 'isin': 'US4581401001', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'PLTR':      {'name': 'Palantir Technologies','wkn': 'A2QA4J', 'isin': 'US69608A1088', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'SMCI':      {'name': 'Super Micro Computer','wkn': 'A0MKJF', 'isin': 'US86800U1043', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'ASML':      {'name': 'ASML Holding (US-ADR)','wkn': 'A1J4U4','isin': 'US0378331005',  'currency': 'USD', 'exchange': 'NASDAQ'},
    'ASML.AS':   {'name': 'ASML Holding',        'wkn': 'A1J4U4', 'isin': 'NL0010273215', 'currency': 'EUR', 'exchange': 'XAMS'},
    'TXN':       {'name': 'Texas Instruments',   'wkn': '852654', 'isin': 'US8825081040', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'IBM':       {'name': 'IBM',                 'wkn': '851399', 'isin': 'US4592001014', 'currency': 'USD', 'exchange': 'NYSE'},

    # ── Defense ─────────────────────────────────────────────────────────
    'LMT':       {'name': 'Lockheed Martin',     'wkn': '894648', 'isin': 'US5398301094', 'currency': 'USD', 'exchange': 'NYSE'},
    'RTX':       {'name': 'RTX Corporation',     'wkn': 'A2DSYC', 'isin': 'US75513E1010', 'currency': 'USD', 'exchange': 'NYSE'},
    'NOC':       {'name': 'Northrop Grumman',    'wkn': '351864', 'isin': 'US6668071029', 'currency': 'USD', 'exchange': 'NYSE'},
    'GD':        {'name': 'General Dynamics',    'wkn': '851143', 'isin': 'US3695501086', 'currency': 'USD', 'exchange': 'NYSE'},
    'BA':        {'name': 'Boeing',              'wkn': '850471', 'isin': 'US0970231058', 'currency': 'USD', 'exchange': 'NYSE'},
    'RHM.DE':    {'name': 'Rheinmetall',         'wkn': '703000', 'isin': 'DE0007030009', 'currency': 'EUR', 'exchange': 'XETR'},
    'TKA.DE':    {'name': 'thyssenkrupp',        'wkn': '750000', 'isin': 'DE0007500001', 'currency': 'EUR', 'exchange': 'XETR'},
    'BAE.L':     {'name': 'BAE Systems',         'wkn': '866131', 'isin': 'GB0002634946', 'currency': 'GBP', 'exchange': 'XLON'},

    # ── Pharma / Healthcare ─────────────────────────────────────────────
    'NVO':        {'name': 'Novo Nordisk (US-ADR)','wkn': 'A3EU6F','isin': 'US6701002056','currency': 'USD', 'exchange': 'NYSE'},
    'NOVO-B.CO':  {'name': 'Novo Nordisk B',     'wkn': 'A3EU6F', 'isin': 'DK0062498333', 'currency': 'DKK', 'exchange': 'XCSE'},
    'LLY':        {'name': 'Eli Lilly',          'wkn': '858560', 'isin': 'US5324571083', 'currency': 'USD', 'exchange': 'NYSE'},
    'PFE':        {'name': 'Pfizer',             'wkn': '852009', 'isin': 'US7170811035', 'currency': 'USD', 'exchange': 'NYSE'},
    'MRK':        {'name': 'Merck & Co',         'wkn': 'A0YD8Q', 'isin': 'US58933Y1055', 'currency': 'USD', 'exchange': 'NYSE'},
    'JNJ':        {'name': 'Johnson & Johnson',  'wkn': '853260', 'isin': 'US4781601046', 'currency': 'USD', 'exchange': 'NYSE'},
    'BAYN.DE':    {'name': 'Bayer',              'wkn': 'BAY001', 'isin': 'DE000BAY0017', 'currency': 'EUR', 'exchange': 'XETR'},
    'UNH':        {'name': 'UnitedHealth Group', 'wkn': '869561', 'isin': 'US91324P1021', 'currency': 'USD', 'exchange': 'NYSE'},
    'CVS':        {'name': 'CVS Health',         'wkn': '859034', 'isin': 'US1266501006', 'currency': 'USD', 'exchange': 'NYSE'},
    'HUM':        {'name': 'Humana',             'wkn': '854583', 'isin': 'US4448591028', 'currency': 'USD', 'exchange': 'NYSE'},
    'CI':         {'name': 'The Cigna Group',    'wkn': 'A2N6X3', 'isin': 'US1255231003', 'currency': 'USD', 'exchange': 'NYSE'},
    'IBB':        {'name': 'iShares Biotech ETF','wkn': 'A0H08H', 'isin': 'US4642875235', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'XBI':        {'name': 'SPDR S&P Biotech ETF','wkn': 'A0Q1HM','isin': 'US78464A4855', 'currency': 'USD', 'exchange': 'NYSE'},

    # ── Materials / Mining ──────────────────────────────────────────────
    'MOS':       {'name': 'Mosaic',              'wkn': 'A0NDCV', 'isin': 'US61945C1036', 'currency': 'USD', 'exchange': 'NYSE'},
    'CF':        {'name': 'CF Industries',       'wkn': 'A0JLZ7', 'isin': 'US1252691001', 'currency': 'USD', 'exchange': 'NYSE'},
    'NTR':       {'name': 'Nutrien',             'wkn': 'A2DRTW', 'isin': 'CA67077M1086', 'currency': 'USD', 'exchange': 'NYSE'},
    'ADM':       {'name': 'Archer-Daniels-Midland','wkn': '854161','isin': 'US0394831020','currency': 'USD', 'exchange': 'NYSE'},
    'AG':        {'name': 'First Majestic Silver','wkn': 'A0LHKJ','isin': 'CA32076V1031',  'currency': 'USD', 'exchange': 'NYSE'},
    'FCX':       {'name': 'Freeport-McMoRan',    'wkn': '896476', 'isin': 'US35671D8570', 'currency': 'USD', 'exchange': 'NYSE'},
    'RIO.L':     {'name': 'Rio Tinto',           'wkn': '852147', 'isin': 'GB0007188757', 'currency': 'GBP', 'exchange': 'XLON'},
    'BHP.L':     {'name': 'BHP Group',           'wkn': '850524', 'isin': 'GB00BH0P3Z91', 'currency': 'GBP', 'exchange': 'XLON'},
    'GLEN.L':    {'name': 'Glencore plc',        'wkn': 'A1JAGV', 'isin': 'JE00B4T3BW64', 'currency': 'GBP', 'exchange': 'XLON'},
    'KGX.DE':    {'name': 'Kion Group',          'wkn': 'KGX888', 'isin': 'DE000KGX8881', 'currency': 'EUR', 'exchange': 'XETR'},

    # ── DAX / EU Industrials ────────────────────────────────────────────
    'SAP.DE':    {'name': 'SAP SE',              'wkn': '716460', 'isin': 'DE0007164600', 'currency': 'EUR', 'exchange': 'XETR'},
    'SAP':       {'name': 'SAP SE (US-ADR)',     'wkn': '716460', 'isin': 'US8030542042', 'currency': 'USD', 'exchange': 'NYSE'},
    'SIE.DE':    {'name': 'Siemens',             'wkn': '723610', 'isin': 'DE0007236101', 'currency': 'EUR', 'exchange': 'XETR'},
    'ALV.DE':    {'name': 'Allianz',             'wkn': '840400', 'isin': 'DE0008404005', 'currency': 'EUR', 'exchange': 'XETR'},
    'MUV2.DE':   {'name': 'Munich Re',           'wkn': '843002', 'isin': 'DE0008430026', 'currency': 'EUR', 'exchange': 'XETR'},
    'BMW.DE':    {'name': 'BMW',                 'wkn': '519000', 'isin': 'DE0005190003', 'currency': 'EUR', 'exchange': 'XETR'},
    'MBG.DE':    {'name': 'Mercedes-Benz Group', 'wkn': '710000', 'isin': 'DE0007100000', 'currency': 'EUR', 'exchange': 'XETR'},
    'VOW3.DE':   {'name': 'Volkswagen Vz',       'wkn': '766403', 'isin': 'DE0007664039', 'currency': 'EUR', 'exchange': 'XETR'},
    'DTE.DE':    {'name': 'Deutsche Telekom',    'wkn': '555750', 'isin': 'DE0005557508', 'currency': 'EUR', 'exchange': 'XETR'},
    'LHA.DE':    {'name': 'Lufthansa',           'wkn': '823212', 'isin': 'DE0008232125', 'currency': 'EUR', 'exchange': 'XETR'},
    'HAG.DE':    {'name': 'Hensoldt',            'wkn': 'HAG000', 'isin': 'DE000HAG0005', 'currency': 'EUR', 'exchange': 'XETR'},
    'AIR.DE':    {'name': 'Airbus',              'wkn': '938914', 'isin': 'NL0000235190', 'currency': 'EUR', 'exchange': 'XETR'},
    'MTX.DE':    {'name': 'MTU Aero Engines',    'wkn': 'A0D9PT', 'isin': 'DE000A0D9PT0', 'currency': 'EUR', 'exchange': 'XETR'},

    # ── EU/UK weitere ───────────────────────────────────────────────────
    'MC.PA':     {'name': 'LVMH Moët Hennessy',  'wkn': '853292', 'isin': 'FR0000121014', 'currency': 'EUR', 'exchange': 'XPAR'},
    'LIN':       {'name': 'Linde plc',           'wkn': 'A2DSYC', 'isin': 'IE000S9YS762', 'currency': 'USD', 'exchange': 'NYSE'},

    # ── Misc S&P ────────────────────────────────────────────────────────
    'CME':       {'name': 'CME Group',           'wkn': 'A0MQQS', 'isin': 'US12572Q1058', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'AXP':       {'name': 'American Express',    'wkn': '850226', 'isin': 'US0258161092', 'currency': 'USD', 'exchange': 'NYSE'},
    'KO':        {'name': 'Coca-Cola',           'wkn': '850663', 'isin': 'US1912161007', 'currency': 'USD', 'exchange': 'NYSE'},
    'WMT':       {'name': 'Walmart',             'wkn': '860853', 'isin': 'US9311421039', 'currency': 'USD', 'exchange': 'NYSE'},
    'CAT':       {'name': 'Caterpillar',         'wkn': '850598', 'isin': 'US1491231015', 'currency': 'USD', 'exchange': 'NYSE'},
    'LEN':       {'name': 'Lennar Corp',         'wkn': '858593', 'isin': 'US5260571048', 'currency': 'USD', 'exchange': 'NYSE'},
    'DHR':       {'name': 'Danaher',             'wkn': '866197', 'isin': 'US2358511028', 'currency': 'USD', 'exchange': 'NYSE'},
    'TMO':       {'name': 'Thermo Fisher Scientific','wkn': '857209','isin': 'US8835561023','currency': 'USD','exchange': 'NYSE'},
    'PAAS':      {'name': 'Pan American Silver', 'wkn': '876617', 'isin': 'CA6979001089', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'KTOS':      {'name': 'Kratos Defense',      'wkn': 'A1JZ74', 'isin': 'US50077B2079', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'DHT':       {'name': 'DHT Holdings',        'wkn': 'A1H7AY', 'isin': 'MHY2065G1219', 'currency': 'USD', 'exchange': 'NYSE'},
    'HL':        {'name': 'Hecla Mining',        'wkn': '854693', 'isin': 'US4227041062', 'currency': 'USD', 'exchange': 'NYSE'},
    'DINO':      {'name': 'HF Sinclair',         'wkn': 'A3DS2N', 'isin': 'US4039131057', 'currency': 'USD', 'exchange': 'NYSE'},
    'MATX':      {'name': 'Matson Inc',          'wkn': 'A1JFLE', 'isin': 'US57686010001','currency': 'USD', 'exchange': 'NYSE'},
    'UEC':       {'name': 'Uranium Energy',      'wkn': 'A0MUSU', 'isin': 'US9168961038', 'currency': 'USD', 'exchange': 'NYSE'},
    'UUUU':      {'name': 'Energy Fuels',        'wkn': 'A2EJZS', 'isin': 'CA2926717083', 'currency': 'USD', 'exchange': 'NYSE'},
    'CCJ':       {'name': 'Cameco',              'wkn': '882017', 'isin': 'CA13321L1085', 'currency': 'USD', 'exchange': 'NYSE'},
    'VDC':       {'name': 'Vanguard Consumer Staples ETF','wkn': 'A0KEUK','isin': 'US92204A6071','currency':'USD','exchange':'NYSE'},
    'SIRI':      {'name': 'Sirius XM Holdings',  'wkn': 'A2P54Y', 'isin': 'US82968B1035', 'currency': 'USD', 'exchange': 'NASDAQ'},

    # ── Phase 43j — Tradermacher 29.04 ───────────────────────────────────
    'CRWV':      {'name': 'CoreWeave Inc',        'wkn': 'A40A9M', 'isin': 'US21873S1087', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'RKLB':      {'name': 'Rocket Lab USA',       'wkn': 'A3CWXJ', 'isin': 'US7731201098', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'ARM':       {'name': 'Arm Holdings',         'wkn': 'A3EVU1', 'isin': 'US0420682058', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'MRVL':      {'name': 'Marvell Technology',   'wkn': 'A2N9SC', 'isin': 'US5738741041', 'currency': 'USD', 'exchange': 'NASDAQ'},
    'SOXX':      {'name': 'iShares Semiconductor ETF','wkn':'A0YEDL','isin':'US4642875565','currency': 'USD', 'exchange': 'NASDAQ'},
}


def lookup(ticker: str) -> dict:
    """Lookup ticker → {name, wkn, isin, currency, exchange}.

    Fallback: {'name': ticker, 'wkn': '?', 'isin': '?', ...} wenn unbekannt."""
    t = (ticker or '').upper().strip()
    if t in TICKERS:
        return {'ticker': t, **TICKERS[t]}
    # Try without exchange suffix
    base = t.split('.')[0]
    if base != t and base in TICKERS:
        return {'ticker': t, **TICKERS[base]}
    return {
        'ticker': t,
        'name': t + ' (unbekannt)',
        'wkn': '?',
        'isin': '?',
        'currency': '?',
        'exchange': '?',
    }


def format_full(ticker: str) -> str:
    """Format: 'Equinor ASA (EQNR.OL, WKN 675213)'."""
    info = lookup(ticker)
    return f"{info['name']} ({info['ticker']}, WKN {info['wkn']})"


def main() -> int:
    import sys
    args = sys.argv[1:]
    if not args:
        print(f'Database: {len(TICKERS)} tickers')
        print('Usage: python3 ticker_lookup.py TICKER [TICKER ...]')
        return 0
    for t in args:
        print(format_full(t))
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
