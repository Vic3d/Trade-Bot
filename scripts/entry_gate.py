#!/usr/bin/env python3
"""
Schicht 2 — Entry Gate
Pflicht-Validierung vor jedem Paper Trade.
"""
import sqlite3, json, re, os
from datetime import datetime, timedelta, timezone

# P1.7 — Thesis-Kill Quarantäne-Registry (48h Sperre nach THESIS_INVALIDATED)
KILL_REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'thesis_invalidation_log.json'
)
QUARANTINE_HOURS = 48


def check_thesis_quarantine(strategy: str) -> tuple[bool, str]:
    """P1.7 — Block-Check: gab es in den letzten 48h einen THESIS_INVALIDATED Exit
    für diese Strategie? Wenn ja → Quarantäne, kein neuer Entry."""
    try:
        if not os.path.exists(KILL_REGISTRY_PATH):
            return False, ''
        with open(KILL_REGISTRY_PATH, encoding='utf-8') as f:
            data = json.load(f) or {}
        kills = data.get('kills', [])
        if not kills:
            return False, ''
        cutoff = datetime.now(timezone.utc) - timedelta(hours=QUARANTINE_HOURS)
        sid = (strategy or '').upper()
        for k in reversed(kills):
            if (k.get('strategy') or '').upper() != sid:
                continue
            ts = k.get('killed_at') or k.get('timestamp')
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if dt >= cutoff:
                age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
                remain = QUARANTINE_HOURS - age_h
                return True, (
                    f"Strategie '{strategy}' in 48h-Quarantäne nach THESIS_INVALIDATED "
                    f"({k.get('ticker','?')}, vor {age_h:.1f}h, noch {remain:.1f}h gesperrt)."
                )
        return False, ''
    except Exception as e:
        print(f'[entry_gate] thesis-quarantine check failed: {e}')
        return False, ''

# ─── Permanent Blocked Strategies (NIEMALS traden) ────────────────────────────
# DT1-DT5: Day-Trade Strategien — Paper Fund macht keine Day Trades
# AR-AGRA: Blockiert nach Verlust-Serie (albert-accuracy.md)
# AR-HALB: Blockiert — Halbleiter-Momentum-Chasing, kein Edge gefunden
PERMANENTLY_BLOCKED_STRATEGIES = {
    'DT1', 'DT2', 'DT3', 'DT4', 'DT5',
    'AR-AGRA', 'AR-HALB',
}

# ─── Block 4b: Politisches/Regulatorisches Risiko Keywords ────────────────────
# Eingeführt 29.03.2026 nach NVO-Fehler (Trump-Preisdeal übersehen).
# Sektoren mit erhöhtem politischen Risiko → Advisory Warning (kein Hard Block, da
# manchmal trotzdem gute Trades, aber IMMER explizit im Discord warnen).
POLITICAL_RISK_SECTORS = {
    'pharma', 'drug', 'medicine', 'biotech', 'glp-1', 'insulin', 'medicare',
    'health', 'hospital',
}
POLITICAL_RISK_KEYWORDS = [
    'executive order', 'price cap', 'price control', 'price regulation',
    'government deal', 'mfn pricing', 'ira pricing', 'tariff impact',
    'nationalization', 'state intervention', 'medicare negotiation',
    'drug pricing', 'price freeze', 'windfall tax', 'windfall profit',
    'sanctions', 'export ban', 'import ban', 'trade restriction',
]

GARBAGE_SOURCES = [
    'usgs.gov', 'usgs', 'geological survey', '富途', 'futu', 'futubull',
    'reddit.com', 'reddit', 'stocktwits', 'weather.com', 'noaa.gov', 'noaa',
    '牛牛', 'xueqiu', '雪球', 'eastmoney', '东方财富', 'sina finance', '新浪',
    'weibo', 'wechat', 'zhihu', '知乎', 'toutiao', '今日头条'
]
GARBAGE_KEYWORDS = [
    'floods and drought', 'science to keep us safe', 'union strike vote',
    'weather forecast', 'earthquake magnitude', 'samsung union strike',
    'samsung strike vote', 'hurricane season', 'wildfire update',
    'drought monitor', 'flood warning', 'storm track'
]

TIER_1 = ['reuters', 'bloomberg', 'wsj', 'ft.com', 'apnews', 'liveuamap', 'maritime-executive']
TIER_2 = ['politico', 'aljazeera', 'bbc', 'cnbc', 'yahoo finance', 'seeking alpha', 'yahoo']
TIER_3 = ['reddit', 'stocktwits', 'futu', 'futubull', 'usgs', 'noaa', '富途']

# AR-* kompatible Regime — CRASH und BEAR explizit verboten
AR_ALLOWED_REGIMES = {'NEUTRAL', 'CORRECTION', 'BULL', 'PAPER_LEARN', ''}
AR_BLOCKED_REGIMES = {'BEAR', 'CRASH', 'TREND_DOWN', 'DEFENSIVE'}

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
        strategy_upper = (strategy or '').upper()  # benötigt in Gate 0 + Gate 3

        # ─── Gate 0: Permanent Blocked Strategies ──────────────────────
        # DT1-DT5, AR-AGRA, AR-HALB sind NIEMALS erlaubt (kein Regime-Check nötig)
        if strategy_upper in PERMANENTLY_BLOCKED_STRATEGIES:
            reason = (
                f"Strategie '{strategy}' ist PERMANENT BLOCKIERT. "
                f"Blockierte Strategien: {', '.join(sorted(PERMANENTLY_BLOCKED_STRATEGIES))}. "
                f"Neue These statt gesperrter Strategie erstellen."
            )
            self._log_blocked(ticker, strategy, 'GATE0_PERMANENTLY_BLOCKED', reason,
                               news_headline, news_source, regime, vix)
            return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': None}

        # ─── Gate 0q: Thesis-Kill Quarantäne (P1.7) ────────────────────
        # Strategien die in den letzten 48h einen THESIS_INVALIDATED Exit hatten
        # bekommen eine Auszeit (kein Re-Entry direkt nach Kill).
        _q_blocked, _q_reason = check_thesis_quarantine(strategy_upper)
        if _q_blocked:
            self._log_blocked(ticker, strategy, 'GATE0Q_THESIS_QUARANTINE', _q_reason,
                               news_headline, news_source, regime, vix)
            return {'allowed': False, 'reason': _q_reason, 'warnings': warnings, 'tier': None}

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

        # ─── Gate 2b: Block 4b — Politisches/Regulatorisches Risiko ───────
        # Pflicht seit 29.03.2026: Ticker in Pharma/Healthcare IMMER warnen.
        # Wenn politische Keywords in Headline → Warning (kein Hard Block, aber
        # wird in Discord sichtbar gemacht damit Victor entscheiden kann).
        ticker_l = ticker.lower()
        _pol_sector = any(s in ticker_l or s in headline_l for s in POLITICAL_RISK_SECTORS)
        _pol_kw_match = next((kw for kw in POLITICAL_RISK_KEYWORDS if kw in headline_l), None)
        if _pol_kw_match:
            warnings.append(
                f"⚠️ Block 4b: Politisches Risiko erkannt — '{_pol_kw_match}' in Headline. "
                f"Explizit prüfen: Preisregulierung, Staatliche Eingriffe, Zölle. "
                f"Erst wenn Block 4b sauber ist → Trade erlaubt."
            )
        elif _pol_sector:
            warnings.append(
                f"⚠️ Block 4b: Pharma/Healthcare-Ticker '{ticker}' — politisches Risiko "
                f"immer prüfen (IRA, MFN-Pricing, Trump-Deals). Deepdive-Protokoll Schritt 4b."
            )

        # ─── Gate 3: Regime Compatibility ──────────────────────────────
        regime_upper = (regime or '').upper()
        # strategy_upper bereits am Anfang von check() definiert

        if strategy_upper.startswith('DT-'):
            reason = f"DT-Strategie '{strategy}' ist im Paper Trading immer blockiert"
            self._log_blocked(ticker, strategy, 'GATE3_DT_BLOCKED', reason,
                               news_headline, news_source, regime, vix)
            return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': tier}

        if strategy_upper.startswith('AR-') and regime_upper in AR_BLOCKED_REGIMES:
            reason = f"AR-Strategie '{strategy}' blockiert im {regime}-Regime (nur NEUTRAL/CORRECTION/BULL erlaubt)"
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

        # ─── Gate 5b: Backtest Validation ────────────────────────────────
        # Strategien mit negativem Backtest-Ergebnis werden geblockt.
        # Daten kommen aus backtest_engine.py (läuft So+Mi).
        try:
            bt_path = os.path.join(os.path.dirname(self.db_path), 'backtest_results.json')
            if os.path.exists(bt_path):
                with open(bt_path, encoding='utf-8') as f:
                    bt_data = json.load(f)
                bt_strategy = bt_data.get(strategy, bt_data.get(strategy_upper, {}))
                if isinstance(bt_strategy, dict):
                    bt_orig = bt_strategy.get('original', bt_strategy)
                    bt_trades = bt_orig.get('trades', 0)
                    bt_pnl = bt_orig.get('pnl', 0)
                    bt_wr = bt_orig.get('wr', bt_orig.get('win_rate', 1.0))
                    # Hard Block: genug Trades + negativ + schlechte WR
                    if bt_trades >= 5 and bt_pnl < 0 and bt_wr < 0.35:
                        reason = (
                            f"Backtest-Gate: Strategie '{strategy}' hat negative Backtest-Ergebnisse "
                            f"({bt_trades} Trades, WR={bt_wr:.0%}, PnL={bt_pnl:+.0f}). "
                            f"Kein Entry bis Backtest positiv."
                        )
                        self._log_blocked(ticker, strategy, 'GATE5B_BACKTEST_NEGATIVE', reason,
                                           news_headline, news_source, regime, vix)
                        return {'allowed': False, 'reason': reason, 'warnings': warnings, 'tier': tier}
                    elif bt_trades >= 5 and bt_pnl < 0:
                        warnings.append(
                            f"Backtest-Warnung: Strategie '{strategy}' PnL negativ "
                            f"({bt_trades} Trades, PnL={bt_pnl:+.0f})"
                        )
        except Exception:
            pass  # Backtest-Daten optional

        # ─── ALLE GATES BESTANDEN ────────────────────────────────────────
        reason = "OK"
        if tier:
            reason = f"OK (Tier {tier} Quelle)"
        elif not news_source:
            reason = "OK (keine Quelle angegeben)"
        else:
            reason = "OK (Quelle unbekannt, Warnung)"

        # ── P25-5 Earnings-Blackout-Check ─────────────────────────────────
        # Block wenn Earnings in <3 Tagen — ausser Strategy-Genesis nennt
        # Earnings explizit als Katalysator (z.B. PM-Earnings-Plays).
        try:
            from earnings_calendar import is_earnings_blackout
            blocked, e_reason = is_earnings_blackout(ticker)
            if blocked:
                # Strategy-Override prüfen
                allow_earnings = False
                try:
                    import json as _j
                    s_path = self.db_path.parent.parent / 'data' / 'strategies.json' if hasattr(self, 'db_path') else None
                    if s_path and s_path.exists():
                        sd = _j.loads(s_path.read_text(encoding='utf-8'))
                        cfg = sd.get(strategy_id, {})
                        genesis = (cfg.get('genesis_thesis', '') or cfg.get('thesis', '')).lower()
                        if 'earnings' in genesis or 'quartal' in genesis or 'q1' in genesis or 'q2' in genesis or 'q3' in genesis or 'q4' in genesis:
                            allow_earnings = True
                            warnings.append(f'Earnings-Override: Strategy-Genesis erlaubt ({e_reason})')
                except Exception:
                    pass
                if not allow_earnings:
                    return {'allowed': False, 'reason': f'Earnings-Blackout: {e_reason}', 'warnings': warnings, 'tier': tier}
        except Exception:
            pass  # Modul fehlt oder Cache leer → kein Block

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
