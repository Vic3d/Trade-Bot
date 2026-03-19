"""
Stock-spezifische Keywords für NewsWire-Relevanz-Filter
Pro Aktie: confirm-Keywords (Thesis stärkt) + negate-Keywords (Thesis schwächt) + noise-Filter
"""

STOCK_KEYWORDS = {

    "EQNR": {
        "name": "Equinor ASA",
        "strategy": 1,
        "stop": 27.0,
        "entry": 27.04,
        # News die direkt diese Aktie betreffen
        "confirm": [
            "equinor", "eqnr", "norsk hydro", "north sea oil",
            "snorre", "norway oil", "norwegian energy",
            "hormuz", "oil supply disruption", "brent surges",
            "iran blockade", "tanker seized", "gulf escalation",
            "oil hits 100", "oil above 100", "crude rally",
        ],
        "negate": [
            "oil falls", "brent drops", "crude tumbles",
            "ceasefire iran", "hormuz open", "iran deal",
            "strategic reserve release", "iea emergency",
            "opec output increase", "russia oil waiver",
            "equinor profit warning", "equinor cuts",
        ],
        "noise": [
            # Ausschließen wenn diese Wörter auftauchen (zu generisch)
            "gas prices at pump", "petrol prices uk",
        ],
    },

    "NVDA": {
        "name": "Nvidia",
        "strategy": 3,
        "stop": None,
        "entry": 167.88,
        "confirm": [
            "nvidia", "nvda", "jensen huang",
            "blackwell", "h100", "h200", "gb200",
            "gpu demand", "datacenter demand", "ai chips",
            "ai infrastructure spending", "hyperscaler capex",
            "nvidia earnings beat", "nvidia revenue",
            "chip demand surge",
        ],
        "negate": [
            "nvidia export ban", "chip ban", "export controls nvidia",
            "nvidia china ban", "nvidia restricted",
            "helium shortage chip", "chip production risk",
            "nvidia miss", "nvidia guidance cut",
            "vix above 30", "tech selloff",
            "ai spending cut", "hyperscaler cuts capex",
            "burry nvidia", "nvidia short",
        ],
        "noise": [
            "nvidia shield", "nvidia geforce gaming",
            "nvidia graphics card review",
        ],
    },

    "MSFT": {
        "name": "Microsoft",
        "strategy": 3,
        "stop": 338.0,
        "entry": 351.85,
        "confirm": [
            "microsoft", "msft",
            "azure growth", "azure revenue", "cloud growth",
            "microsoft ai", "copilot adoption", "openai microsoft",
            "microsoft earnings beat", "microsoft guidance",
            "microsoft datacenter",
        ],
        "negate": [
            "microsoft layoffs", "microsoft job cuts",
            "azure outage", "microsoft miss",
            "microsoft antitrust", "microsoft regulation",
            "openai dispute microsoft",
        ],
        "noise": [
            "microsoft xbox", "microsoft windows update",
            "microsoft surface review",
        ],
    },

    "PLTR": {
        "name": "Palantir Technologies",
        "strategy": 3,
        "stop": 127.0,
        "entry": 132.11,
        "confirm": [
            "palantir", "pltr",
            "palantir contract", "palantir revenue",
            "palantir government", "palantir defense",
            "palantir earnings beat", "palantir guidance",
            "ai defense spending", "pentagon ai",
            "palantir nato", "palantir ukraine",
            "palantir iran", "palantir military",
            "palantir ontology", "foundry",
        ],
        "negate": [
            "palantir loses contract", "pentagon ai ban",
            "palantir investigation", "palantir doge",
            "palantir miss", "palantir guidance cut",
            "burry palantir", "palantir short",
            "palantir contract cancelled", "palantir review",
            "government ai moratorium",
        ],
        "noise": [
            "palantir airport", # place name
        ],
    },

    "BAYN": {
        "name": "Bayer AG",
        "strategy": None,
        "stop": 38.0,
        "entry": 39.95,
        "confirm": [
            "bayer", "bayn.de",
            "bayer earnings beat", "bayer guidance raised",
            "roundup settlement", "roundup final settlement",
            "bayer restructuring success", "bayer crop science",
            "bayer pharma approval", "bayer xarelto",
        ],
        "negate": [
            "bayer roundup verdict", "bayer liable",
            "bayer new lawsuit", "bayer profit warning",
            "bayer guidance cut", "bayer layoffs",
            "glyphosate ban", "bayer dividend cut",
            "bayer debt", "bayer downgrade",
        ],
        "noise": [],
    },

    "RHM": {
        "name": "Rheinmetall AG",
        "strategy": 2,
        "stop": None,
        "entry": None,  # Watchlist
        "confirm": [
            "rheinmetall", "rhm.de",
            "rheinmetall order", "rheinmetall contract",
            "rheinmetall earnings", "rheinmetall guidance",
            "defense spending europe", "nato budget increase",
            "bundeswehr auftrag", "european rearmament",
            "500 milliarden rüstung", "sondervermögen",
            "ukraine weapons supply", "artillery demand",
        ],
        "negate": [
            "rheinmetall profit warning", "rheinmetall guidance cut",
            "ceasefire ukraine", "ukraine peace deal",
            "defense budget cut europe", "nato spending freeze",
            "rheinmetall scandal", "rheinmetall miss",
        ],
        "noise": [],
    },

    "DR0": {
        "name": "Deutsche Rohstoff AG",
        "strategy": 1,
        "stop": 74.0,
        "entry": None,  # Watchlist
        "confirm": [
            "deutsche rohstoff", "dr0.de",
            "deutsche rohstoff earnings", "dr0 oil production",
            "wti above 95", "oil above 95", "crude above 90",
            "hormuz", "iran oil disruption",
        ],
        "negate": [
            "deutsche rohstoff warning", "dr0 production cut",
            "oil below 80", "wti falls below 80",
            "oil demand weak",
        ],
        "noise": [],
    },

    "RIO": {
        "name": "Rio Tinto",
        "strategy": 5,
        "stop": 73.0,
        "entry": 76.92,
        "confirm": [
            "rio tinto", "rio.l",
            "rio tinto copper", "rio tinto lithium",
            "oyu tolgoi production", "copper demand surge",
            "copper rally", "copper hits", "ev copper demand",
            "rio tinto earnings beat", "rio tinto guidance",
            "lithium demand", "energy transition metals",
        ],
        "negate": [
            "rio tinto dividend cut", "rio tinto miss",
            "oyu tolgoi renegotiation", "mongolia dispute",
            "china iron ore restrictions", "iron ore falls",
            "copper falls", "copper demand weak",
            "china stimulus disappoints",
        ],
        "noise": [],
    },

    "AG": {
        "name": "First Majestic Silver",
        "strategy": 4,
        "stop": 20.5,
        "entry": None,  # Watchlist
        "confirm": [
            "first majestic", "first majestic silver",
            "silver surges", "silver rally", "silver above 30",
            "precious metals rally", "silver safe haven",
            "solar silver demand", "industrial silver",
            "first majestic earnings beat", "ag earnings",
            "silver supply deficit",
        ],
        "negate": [
            "silver falls", "silver drops", "silver below 24",
            "usd strengthens", "dollar surges",
            "fed rate hike", "silver supply glut",
            "first majestic miss", "first majestic guidance cut",
            "mining strike first majestic",
        ],
        "noise": [],
    },

    "ISPA": {
        "name": "iShares Physical Silver ETC",
        "strategy": 4,
        "stop": None,
        "entry": None,  # Watchlist, Entry >36.90€
        "confirm": [
            "silver etf inflows", "silver demand",
            "silver surges", "silver rally",
            "physical silver", "silver backwardation",
        ],
        "negate": [
            "silver etf outflows", "silver falls",
            "silver contango", "silver oversupply",
        ],
        "noise": [],
    },

    # Makro-Keywords (kein spezifischer Stock, aber Portfolio-relevant)
    "_MACRO": {
        "name": "Makro / Portfolio-übergreifend",
        "strategy": None,
        "confirm": [],
        "negate": [],
        "critical": [
            "fed emergency", "market circuit breaker",
            "systemic risk", "bank run", "flash crash",
            "nuclear", "market halt", "trading suspended",
            "vix above 40", "black monday",
        ],
        "watchlist": [
            "vix above 30", "vix surges", "vix spikes",
            "fed surprise hike", "ecb emergency",
            "trump tariffs", "recession confirmed",
            "yield curve inversion", "credit crunch",
        ],
        "noise": [],
    },
}
