#!/usr/bin/env python3
"""
Schicht 2 — Entry Gate
Pflicht-Validierung vor jedem Paper Trade.
"""
import sqlite3, json, re, os
from datetime import datetime

GARBAGE_SOURCES = [
    'usgs.gov', 'usgs', 'geological survey', '富途', 'futu', 'futubull',
    'reddit.com', 'reddit', 'stocktwits', 'weather.com', 'noaa.gov', 'noaa'
]
GARBAGE_KEYWORDS = [
    'floods and drought', 'science to keep us safe', 'union strike vote',
    'weather forecast', 'earthquake magnitude', 'samsung union strike',
    'samsung strike vote'
]

TIER_1 = ['reuters', 'bloomberg', 'wsj', 'ft.com', 'apnews', 'liveuamap', 'maritime-executive']
TIER_2 = ['politico', 'aljazeera', 'bbc', 'cnbc', 'yahoo finance', 'seeking alpha', 'yahoo']
TIER_3 = ['reddit', 'stocktwits', 'futu', 'futubull', 'usgs', 'noaa', '富途']

# AR-* kompatible Regime
AR_ALLOWED_REGIMES = {'NEUTRAL', 'CORRECTION', 'BULL', 'RISK_OFF', 'PAPER_LEARN', ''}

# High-VIX Whitelist (Ticker-Fragmente)
HIGH_VIX_WHITELIST = ['OXY', 'XOM', 'CVX', 'EQNR', 'FRO', 'DHT', 'TTE', 'BP',  # Oil
                       'GLD', 'SLV', 'GOLD', 'NEM', 'PAAS', 'HL', 'AG',          # Gold/Silver
                       'LMT', 'RTX', 'NOC', 'GD', 'BA', 'RHM', 'BAYN',          # Defense
                       'HAG', 'AIR']


def get_source_tier(source):
    """Gibt Tier 1/2/3 zurück, None = unbekannt"""
    s = (source or '').lower()
    for t1 in TIER_1:
        if t1 in s:
            return 1
    for t2 in TIER_2:
        if t2 in s:
            return 2
    for t3 in TIER_3:
        if t3 in s:
            return 3
    return None  # Unknown


CHINESE_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef]')


def has_chinese(text):
    return bool(CHINESE_RE.search(text or ''))


class EntryGate:
    def __init__(self, db_path):
        self.db_path = db_path
        self._strategies = None

    def _load_strategies(self):
        if self._strategies is not None:
            return self._strategies
        # Suche strategies.json relativ zu db_path oder workspace
        candidates = [
            os.path.join(os.path.dirname(self.db_path), 'strategies.json'),
            os.path.join(os.path.dirname(os.path.dirname(self.db_path)),
                         'data', 'strategies.json'),
        ]
        for path in candidates:
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        self._strategies = json.load(f)
                    return self._strategies
                except Exception:
                    pass
        self._strategies = {}
        return self._strategies

    def _is_ticker_open(self, ticker):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM paper_portfolio WHERE ticker=? AND status='OPEN'",
                      (ticker,))
            n = c.fetchone()[0]
            conn.close()
            return n > 0
        except Exception:
            return False

    def _log_blocked(self, ticker, strategy, gate, reason, headline, source, regime, vix):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            # Ensure table exists
            c.execute("""
                CREATE TABLE IF NOT EXISTS entry_gate_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    ticker TEXT,
                    strategy TEXT,
                    gate_triggered TEXT,
                    reason TEXT,
                    news_headline TEXT,
                    news_source TEXT,
                    regime TEXT,
                    vix REAL
                )
            """)
            c.execute("""
                INSERT INTO entry_gate_log
                (timestamp, ticker, strategy, gate_triggered, reason, news_headline,
                 news_source, regime, vix)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                datetime.now().isoformat(),
                ticker, strategy, gate, reason,
                (headline or '')[:200], (source or '')[:100],
                regime, vix
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ENTRY GATE LOG ERROR] {e}")

    def check(self, ticker, strategy, news_headline='', news_source='', regime='', vix=0) -> dict:
        """
        Returns: {'allowed': bool, 'reason': str, 'warnings': list, 'tier': int|None}
        """
        warnings = []
        headline_l = (news_headline or '').lower()
        source_l = (news_source or '').lower()

        # ─── Gate 1: Duplikat (ticker bereits OPEN?) ───────────────────
        if self._is_ticker_open(ticker):
            reason = f"Ticker {ticker} bereits OPEN im Portfolio"
            self._log_blocked(ticker, strategy, 'GATE1_DUPLICATE', reason,
                               news_headline, news_source, regime, vix)
            return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': None}

        # ─── Gate 2: News Source Quality ───────────────────────────────
        # Check Garbage Sources
        if has_chinese(news_source) or has_chinese(news_headline):
            reason = f"Chinesische Quelle / Text blockiert: '{news_source}'"
            self._log_blocked(ticker, strategy, 'GATE2_GARBAGE_SOURCE', reason,
                               news_headline, news_source, regime, vix)
            return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': None}

        for gs in GARBAGE_SOURCES:
            if gs.lower() in source_l:
                reason = f"Garbage-Quelle blockiert: '{news_source}' enthält '{gs}'"
                self._log_blocked(ticker, strategy, 'GATE2_GARBAGE_SOURCE', reason,
                                   news_headline, news_source, regime, vix)
                return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': None}

        for kw in GARBAGE_KEYWORDS:
            if kw.lower() in headline_l:
                reason = f"Garbage-Keyword in Headline: '{kw}'"
                self._log_blocked(ticker, strategy, 'GATE2_GARBAGE_KEYWORD', reason,
                                   news_headline, news_source, regime, vix)
                return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': None}

        tier = get_source_tier(news_source)
        if tier == 3:
            reason = f"Tier-3-Quelle blockiert: '{news_source}'"
            self._log_blocked(ticker, strategy, 'GATE2_TIER3_SOURCE', reason,
                               news_headline, news_source, regime, vix)
            return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': tier}

        if tier is None and news_source:
            warnings.append(f"Unbekannte Quelle '{news_source}' — Qualität nicht verifiziert")

        # ─── Gate 3: Regime Compatibility ──────────────────────────────
        regime_upper = (regime or '').upper()
        strategy_upper = (strategy or '').upper()

        if strategy_upper.startswith('DT-'):
            reason = f"DT-Strategie '{strategy}' ist im Paper Trading immer blockiert"
            self._log_blocked(ticker, strategy, 'GATE3_DT_BLOCKED', reason,
                               news_headline, news_source, regime, vix)
            return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': tier}

        if strategy_upper.startswith('AR-') and regime_upper == 'BEAR':
            reason = f"AR-Strategie '{strategy}' nicht erlaubt im BEAR-Regime"
            self._log_blocked(ticker, strategy, 'GATE3_REGIME_MISMATCH', reason,
                               news_headline, news_source, regime, vix)
            return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': tier}

        if strategy_upper.startswith('AR-') and regime_upper not in AR_ALLOWED_REGIMES:
            warnings.append(f"AR-Strategie im unbekannten Regime '{regime}' — prüfen")

        # ─── Gate 4: VIX Sanity ─────────────────────────────────────────
        if vix and vix > 50:
            # Nur Oil/Defense/Gold erlaubt
            allowed_by_vix = any(w in ticker.upper() for w in HIGH_VIX_WHITELIST)
            if not allowed_by_vix:
                reason = f"VIX={vix:.1f} > 50 — nur Oil/Defense/Gold erlaubt, '{ticker}' nicht auf Whitelist"
                self._log_blocked(ticker, strategy, 'GATE4_HIGH_VIX', reason,
                                   news_headline, news_source, regime, vix)
                return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': tier}
            else:
                warnings.append(f"VIX={vix:.1f} sehr hoch — erhöhtes Risiko, aber '{ticker}' auf VIX-Whitelist")

        # ─── Gate 5: Strategy Active Check ──────────────────────────────
        strategies = self._load_strategies()
        if strategy in strategies:
            strat_data = strategies[strategy]
            if isinstance(strat_data, dict):
                if strat_data.get('locked', False):
                    reason = f"Strategie '{strategy}' ist gesperrt (locked=true)"
                    self._log_blocked(ticker, strategy, 'GATE5_STRATEGY_LOCKED', reason,
                                       news_headline, news_source, regime, vix)
                    return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': tier}
                if strat_data.get('active') is False:
                    reason = f"Strategie '{strategy}' ist inaktiv (active=false)"
                    self._log_blocked(ticker, strategy, 'GATE5_STRATEGY_INACTIVE', reason,
                                       news_headline, news_source, regime, vix)
                    return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': tier}

        # ─── ALLE GATES BESTANDEN ────────────────────────────────────────
        reason = "OK"
        if tier:
            reason = f"OK (Tier {tier} Quelle)"
        elif not news_source:
            reason = "OK (keine Quelle angegeben)"
        else:
            reason = "OK (Quelle unbekannt, Warnung)"

        return {'allowed': True, 'reason': reason, 'warnings': warnings, 'tier': tier}


if __name__ == '__main__':
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else 'data/trading.db'
    gate = EntryGate(db)

    print("=== ENTRY GATE SELBSTTEST ===\n")

    tests = [
        ('AMAT', 'AR-HALB', 'Could a Samsung union strike vote this week...', '富途牛牛', 'BEAR', 31.0),
        ('EQNR.OL', 'PS1', 'Iran blockiert Hormuz', 'reuters.com', 'RISK_OFF', 31.0),
        ('ADM', 'AR-AGRA', 'USGS Science to Keep Us Safe: Floods and Drought', 'USGS (.gov)', 'NEUTRAL', 18.0),
        ('NVDA', 'AR-HALB', 'TSMC raises outlook on AI demand', 'bloomberg.com', 'NEUTRAL', 22.0),
    ]

    for ticker, strat, headline, source, regime, vix in tests:
        r = gate.check(ticker, strat, headline, source, regime, vix)
        status = "✅ ALLOWED" if r['allowed'] else "❌ BLOCKED"
        print(f"{status} | {ticker}/{strat}")
        print(f"  Reason: {r['reason']}")
        if r['warnings']:
            print(f"  Warnings: {r['warnings']}")
        print()
