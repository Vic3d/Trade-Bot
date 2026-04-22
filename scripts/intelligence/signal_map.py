"""
Signal Map — Catalyst → Profiteer Lookup
=========================================
Phase 23: Reine Datenstruktur — wer profitiert von welcher News?

Regel-Format:
{
  'id':              'kurzer eindeutiger Name',
  'keywords':        ['liste', 'von', 'phrasen'],   # Headline muss MINDESTENS einen enthalten
  'sector':          'Anzeige-Name',
  'tickers':         ['STLD', 'NUE', ...],          # Profiteers (Long bei direction_up)
  'short_tickers':   ['CLF', ...],                  # optional: Verlierer (Short-Idee bei direction_up)
  'direction_up':    ['stark bullisch'],            # zusätzliche Modifier-Words → BULLISH HIGH
  'direction_down':  ['stark bearisch'],            # → BEARISH HIGH
  'base_confidence': 'medium' | 'high',             # ohne Modifier-Match
  'note':            'kurzer Kontext, was die These ist',
}

Engine sucht zuerst keyword-Match, dann direction-Modifier.
"""

SIGNAL_MAP: list[dict] = [
    # ── Industrie / Stahl / Aluminium ────────────────────────────────────────
    {
        'id': 'steel_tariffs',
        'keywords': [
            'section 232', 'steel tariff', 'aluminum tariff', 'stahlzoll',
            'steel import', 'tariff on steel', 'tariff on aluminum',
        ],
        'sector': 'Stahl/Aluminium (US)',
        'tickers': ['STLD', 'NUE', 'X', 'CLF', 'AA'],
        'direction_up': ['imposed', 'raised', 'doubled', 'increase', 'signed', 'extended'],
        'direction_down': ['lifted', 'removed', 'suspended', 'exemption', 'rolled back'],
        'base_confidence': 'high',
        'note': 'US-Stahlzölle = unmittelbar bullisch für US-Steel-Mills (Pricing Power)',
    },
    {
        'id': 'china_steel_dump',
        'keywords': ['china steel export', 'china oversupply', 'china dump', 'chinese steel'],
        'sector': 'Stahl (China-Druck)',
        'tickers': [],
        'short_tickers': ['STLD', 'NUE', 'X'],
        'direction_up': ['surge', 'flood', 'record export', 'overcapacity'],
        'direction_down': ['cuts', 'shutdown', 'export curb'],
        'base_confidence': 'medium',
        'note': 'Chinas Stahl-Export drückt globale Preise → US-Mills negativ',
    },

    # ── Verteidigung / Rüstung ───────────────────────────────────────────────
    {
        'id': 'defense_spending',
        'keywords': [
            'defense spending', 'rüstung', 'nato budget', 'military aid',
            'weapons package', 'arms deal', 'verteidigungshaushalt',
        ],
        'sector': 'Verteidigung',
        'tickers': ['RHM.DE', 'HAG.DE', 'HO.PA', 'LMT', 'RTX', 'NOC', 'GD', 'BA', 'KTOS'],
        'direction_up': ['increase', 'raises', 'approves', 'announces', 'signed', 'expand'],
        'direction_down': ['cut', 'reduce', 'freeze', 'block'],
        'base_confidence': 'high',
        'note': 'Erhöhte Verteidigungs-Budgets = direkte Order-Pipeline für Defense-Stocks',
    },
    {
        'id': 'ukraine_aid',
        'keywords': ['ukraine aid', 'ukraine package', 'patriot ukraine', 'ukraine weapons'],
        'sector': 'Verteidigung (Ukraine-Pipeline)',
        'tickers': ['RHM.DE', 'LMT', 'RTX', 'GD'],
        'direction_up': ['approved', 'signed', 'delivered', 'expanded'],
        'direction_down': ['paused', 'blocked', 'reduced'],
        'base_confidence': 'high',
        'note': 'Ukraine-Hilfspakete fließen direkt in Defense-Auftragsbücher',
    },

    # ── Pharma / Biotech (Politisches Risiko) ────────────────────────────────
    {
        'id': 'drug_price_cap',
        'keywords': [
            'drug price cap', 'medicare pricing', 'most favored nation drug',
            'inflation reduction act drug', 'drug pricing reform', 'arzneimittelpreis',
        ],
        'sector': 'Pharma (Preis-Druck)',
        'tickers': [],
        'short_tickers': ['NVO', 'LLY', 'PFE', 'MRK', 'BMY'],
        'direction_up': ['announces', 'imposes', 'caps', 'targets', 'investigates'],
        'direction_down': ['rejected', 'overturned', 'paused', 'exemption'],
        'base_confidence': 'high',
        'note': 'Trump/Biden-Drug-Pricing = unmittelbar bearisch für Big Pharma (siehe NVO -843€)',
    },
    {
        'id': 'fda_approval',
        'keywords': ['fda approval', 'fda approves', 'fda rejects', 'pdufa date'],
        'sector': 'FDA-Event',
        'tickers': [],  # company-spezifisch, manuell
        'direction_up': ['approves', 'breakthrough', 'fast track'],
        'direction_down': ['rejects', 'crl', 'complete response letter'],
        'base_confidence': 'high',
        'note': 'FDA-Decisions sind binäre Events — Ticker muss manuell erkannt werden',
    },

    # ── Halbleiter ───────────────────────────────────────────────────────────
    {
        'id': 'chip_export_ban',
        'keywords': [
            'chip export', 'semiconductor export', 'china chip ban',
            'asml export', 'nvidia china', 'export restrictions chip',
        ],
        'sector': 'Halbleiter (Export-Kontrollen)',
        'tickers': ['ASML.AS', 'AMAT', 'LRCX', 'KLAC'],
        'short_tickers': ['NVDA'],
        'direction_up': ['lifted', 'eased', 'exemption'],
        'direction_down': ['imposed', 'tightened', 'expanded', 'banned', 'restricted'],
        'base_confidence': 'high',
        'note': 'China-Chip-Beschränkungen treffen NVDA-Umsatz, ASML-Tools doppelschneidig',
    },
    {
        'id': 'ai_capex',
        'keywords': [
            'ai capex', 'ai infrastructure', 'data center investment',
            'hyperscaler capex', 'compute spending',
        ],
        'sector': 'AI Infrastruktur',
        'tickers': ['NVDA', 'SMCI', 'ANET', 'VRT', 'ASML.AS', 'TSM'],
        'direction_up': ['raises', 'expands', 'record', 'announces', 'doubles'],
        'direction_down': ['cuts', 'reduces', 'pauses', 'delays'],
        'base_confidence': 'medium',
        'note': 'Hyperscaler-Capex = NVDA + Pick&Shovel-Plays (Cooling, Networking)',
    },

    # ── Öl / Energie ─────────────────────────────────────────────────────────
    {
        'id': 'opec_cuts',
        'keywords': ['opec cut', 'opec+ cut', 'production cut', 'oil supply cut', 'opec ölförderung'],
        'sector': 'Öl (Supply Cuts)',
        'tickers': ['OXY', 'XOM', 'CVX', 'EQNR.OL', 'TTE.PA', 'BP'],
        'direction_up': ['extended', 'deepen', 'announce', 'agreed'],
        'direction_down': ['reverse', 'increase output', 'unwind'],
        'base_confidence': 'high',
        'note': 'OPEC-Cuts = unmittelbar bullisch für Öl-Major (höherer Brent-Preis)',
    },
    {
        'id': 'iran_oil',
        'keywords': ['iran oil', 'iran sanctions', 'hormuz', 'strait of hormuz', 'iran tanker'],
        'sector': 'Öl (Iran-Risk Premium)',
        'tickers': ['OXY', 'XOM', 'CVX', 'FRO', 'STNG', 'EQNR.OL'],
        'direction_up': ['attack', 'closed', 'sanctions imposed', 'seized', 'strike', 'missile'],
        'direction_down': ['ceasefire', 'deal signed', 'sanctions lifted', 'opened'],
        'base_confidence': 'high',
        'note': 'Hormuz = 20% des Welt-Öls; Eskalation = Risk-Premium auf Brent',
    },
    {
        'id': 'lng_disruption',
        'keywords': ['lng', 'natural gas', 'pipeline attack', 'gas supply', 'flüssiggas'],
        'sector': 'LNG / Erdgas',
        'tickers': ['LNG', 'TELL', 'EQNR.OL', 'TTE.PA'],
        'direction_up': ['attack', 'shutdown', 'cold wave', 'shortage', 'export ban'],
        'direction_down': ['warm winter', 'new supply', 'discovery'],
        'base_confidence': 'medium',
        'note': 'EU-LNG-Versorgung weiterhin sensibel (Russland-Pipeline-Ausfall)',
    },

    # ── Kupfer / Industriemetalle ────────────────────────────────────────────
    {
        'id': 'copper_supply',
        'keywords': ['copper', 'kupfer', 'chile mine', 'peru mine', 'kupfermine'],
        'sector': 'Kupfer',
        'tickers': ['FCX', 'TECK', 'SCCO', 'HBM'],
        'direction_up': ['strike', 'shortage', 'shutdown', 'mine close', 'flood', 'protest'],
        'direction_down': ['oversupply', 'china demand falls', 'restart'],
        'base_confidence': 'high',
        'note': 'Chile/Peru = ~40% Welt-Kupfer-Förderung — Streiks treffen sofort den Preis',
    },
    {
        'id': 'lithium',
        'keywords': ['lithium', 'lithium mine', 'lithium supply', 'ev battery'],
        'sector': 'Lithium / EV-Batterien',
        'tickers': ['ALB', 'SQM', 'LTHM', 'PLL'],
        'direction_up': ['shortage', 'mine closure', 'demand surge', 'china export ban'],
        'direction_down': ['oversupply', 'new mine', 'demand falls', 'ev slowdown'],
        'base_confidence': 'medium',
        'note': '2024-2025 war Oversupply — jetzt Bottom-Fishing-Phase',
    },
    {
        'id': 'rare_earth',
        'keywords': ['rare earth', 'seltene erden', 'neodymium', 'dysprosium', 'samarium'],
        'sector': 'Seltene Erden',
        'tickers': ['MP', 'TMC', 'LYC.AX'],
        'direction_up': ['china export ban', 'shortage', 'defense demand', 'restriction'],
        'direction_down': ['lifted', 'new mine', 'alternative'],
        'base_confidence': 'high',
        'note': 'China = 90% Verarbeitung — jede Export-Restriktion = MP-Rakete',
    },
    {
        'id': 'gold_silver',
        'keywords': ['gold price', 'silver price', 'gold rally', 'goldpreis', 'silberpreis'],
        'sector': 'Edelmetalle',
        'tickers': ['NEM', 'GOLD', 'AG', 'PAAS', 'HL'],
        'direction_up': ['record', 'surge', 'rally', 'breakout', 'safe haven'],
        'direction_down': ['plunge', 'crash', 'sell-off'],
        'base_confidence': 'medium',
        'note': 'Miner-Hebel auf Goldpreis ~3x',
    },

    # ── Agrar / Soft Commodities ─────────────────────────────────────────────
    {
        'id': 'grain_supply',
        'keywords': ['wheat', 'weizen', 'corn', 'soy', 'grain export', 'getreide'],
        'sector': 'Agrar (Grain)',
        'tickers': ['ADM', 'BG', 'MOS', 'NTR', 'CF'],
        'direction_up': ['drought', 'dürre', 'export ban', 'flood', 'frost', 'shortage'],
        'direction_down': ['record harvest', 'oversupply', 'good crop'],
        'base_confidence': 'medium',
        'note': 'Wettereignisse + Export-Bans = Ernten-Squeeze',
    },
    {
        'id': 'soft_commodities',
        'keywords': ['coffee', 'cocoa', 'kakao', 'palm oil', 'sugar'],
        'sector': 'Soft Commodities',
        'tickers': ['JO', 'NIB'],
        'direction_up': ['drought', 'disease', 'frost', 'shortage'],
        'direction_down': ['record crop', 'oversupply'],
        'base_confidence': 'medium',
        'note': 'Westafrika-Kakao + Brasilien-Kaffee = wetter-sensibel',
    },

    # ── Shipping / Tanker ────────────────────────────────────────────────────
    {
        'id': 'tanker_rates',
        'keywords': ['tanker rate', 'vlcc', 'product tanker', 'shipping rate', 'baltic dirty'],
        'sector': 'Tanker-Shipping',
        'tickers': ['FRO', 'STNG', 'INSW', 'DHT', 'TNK', 'EURN.BR'],
        'direction_up': ['surge', 'record', 'rally', 'spike', 'tighten'],
        'direction_down': ['collapse', 'plunge', 'oversupply'],
        'base_confidence': 'high',
        'note': 'Tanker-Spot-Rates korrelieren direkt mit Quartalsergebnissen',
    },
    {
        'id': 'red_sea',
        'keywords': ['red sea', 'houthi', 'suez', 'bab el-mandeb', 'gulf of aden'],
        'sector': 'Shipping (Red Sea Risk)',
        'tickers': ['FRO', 'STNG', 'ZIM', 'MAERSKb.CO'],
        'direction_up': ['attack', 'missile', 'closed', 'rerouted', 'avoid'],
        'direction_down': ['cease', 'deal', 'safe passage'],
        'base_confidence': 'high',
        'note': 'Red-Sea-Sperrung = Tanker-Routen-Verlängerung = Raten-Spike',
    },

    # ── Zentralbanken / Macro ────────────────────────────────────────────────
    {
        'id': 'fed_cut',
        'keywords': ['fed cut', 'fed pivot', 'fed pause', 'rate cut', 'zinssenkung'],
        'sector': 'Zinssensitive Assets',
        'tickers': ['TLT', 'IEF', 'GLD', 'VNQ', 'XLU', 'IWM'],
        'direction_up': ['cut', 'pivot', 'dovish', 'pause'],
        'direction_down': ['hike', 'hawkish', 'higher for longer'],
        'base_confidence': 'medium',
        'note': 'Rate-Cuts = bullisch für Bonds, Gold, REITs, Small-Caps',
    },
    {
        'id': 'inflation_hot',
        'keywords': ['inflation', 'cpi', 'ppi', 'core inflation', 'sticky inflation'],
        'sector': 'Inflation-Hedge',
        'tickers': ['GLD', 'XLE', 'XLB'],
        'direction_up': ['hot', 'surge', 'above forecast', 'sticky', 'reaccelerate'],
        'direction_down': ['cool', 'below forecast', 'soften', 'ease'],
        'base_confidence': 'medium',
        'note': 'Hot-CPI = Gold + Energy + Materials bullisch, Bonds bearisch',
    },

    # ── Krypto / Regulierung ─────────────────────────────────────────────────
    {
        'id': 'crypto_etf',
        'keywords': ['bitcoin etf', 'crypto etf', 'sec approves', 'spot etf'],
        'sector': 'Crypto-Equities',
        'tickers': ['COIN', 'MSTR', 'MARA', 'RIOT', 'HOOD'],
        'direction_up': ['approves', 'launch', 'inflow', 'record'],
        'direction_down': ['rejects', 'delays', 'outflow'],
        'base_confidence': 'high',
        'note': 'ETF-Approvals + Inflows = direkter COIN/MSTR-Hebel',
    },

    # ── Trade-War / China ────────────────────────────────────────────────────
    {
        'id': 'china_tariff',
        'keywords': [
            'china tariff', 'tariff on china', 'trade war china', 'chinazoll',
            'us china trade', 'biden tariff', 'trump tariff',
        ],
        'sector': 'China-Exposure',
        'tickers': ['CAT', 'BA', 'AAPL', 'TSLA'],
        'short_tickers': ['BABA', 'PDD', 'JD'],
        'direction_up': ['lifted', 'eased', 'exemption', 'paused'],
        'direction_down': ['imposed', 'raised', 'doubled', 'expanded', 'extended'],
        'base_confidence': 'high',
        'note': 'China-Zölle = Druck auf US-Multinationals + China-ADRs',
    },

    # ── Region-ETFs ──────────────────────────────────────────────────────────
    {
        'id': 'argentina',
        'keywords': ['argentina', 'milei', 'peso devaluation', 'argentine reform'],
        'sector': 'Argentinien',
        'tickers': ['ARGT', 'GGAL', 'YPF', 'BMA', 'PAM'],
        'direction_up': ['reform', 'imf deal', 'peso strong', 'inflation falls'],
        'direction_down': ['default', 'devaluation', 'protest', 'capital control'],
        'base_confidence': 'medium',
        'note': 'Milei-Reform-Trade weiterhin volatil',
    },
    {
        'id': 'brazil',
        'keywords': ['brazil', 'lula', 'real currency', 'brazilian'],
        'sector': 'Brasilien',
        'tickers': ['EWZ', 'VALE', 'PBR', 'ITUB'],
        'direction_up': ['rate cut', 'commodity boom', 'reform passes'],
        'direction_down': ['fiscal crisis', 'rate hike', 'real plunge'],
        'base_confidence': 'medium',
        'note': 'EWZ = Macro-Proxy via VALE (Eisenerz) + PBR (Öl)',
    },
    {
        'id': 'japan',
        'keywords': ['boj', 'yen', 'japan rate', 'nikkei', 'japanese intervention'],
        'sector': 'Japan',
        'tickers': ['EWJ', 'DXJ'],
        'direction_up': ['yen weak', 'rate cut', 'easing'],
        'direction_down': ['intervention', 'rate hike', 'yen strong'],
        'base_confidence': 'medium',
        'note': 'Yen-Schwäche = Nikkei-Exporteure bullisch',
    },

    # ── Lieferketten / Streiks ───────────────────────────────────────────────
    {
        'id': 'port_strike',
        'keywords': ['port strike', 'longshoremen', 'ila strike', 'hafenstreik'],
        'sector': 'Supply-Chain (Häfen)',
        'tickers': ['FRO', 'ZIM'],  # Tanker profitieren von Disruption
        'short_tickers': ['WMT', 'TGT', 'COST'],
        'direction_up': ['begins', 'extends', 'no deal', 'walkout'],
        'direction_down': ['deal reached', 'ends', 'agreement'],
        'base_confidence': 'medium',
        'note': 'US-East-Coast-Häfen = Containerflow → Retailer-Druck bei Streik',
    },

    # ── Klima / Wetter ───────────────────────────────────────────────────────
    {
        'id': 'hurricane',
        'keywords': ['hurricane', 'tropical storm', 'gulf of mexico storm'],
        'sector': 'Wetter-Disruption (Gulf)',
        'tickers': ['OXY', 'XOM', 'CVX'],  # Gulf-Production
        'direction_up': ['shut in', 'evacuates', 'platform damage', 'category 4', 'category 5'],
        'direction_down': ['weakens', 'misses', 'downgraded'],
        'base_confidence': 'medium',
        'note': 'Hurrikane in Gulf = Öl-Production-Shut-In = kurzer Brent-Spike',
    },
]


def all_tickers() -> set[str]:
    """Alle Ticker die in irgendeinem Mapping vorkommen."""
    out: set[str] = set()
    for rule in SIGNAL_MAP:
        for t in rule.get('tickers', []) + rule.get('short_tickers', []):
            if t and not t.startswith('depends_'):
                out.add(t.upper())
    return out


def rules_count() -> int:
    return len(SIGNAL_MAP)
