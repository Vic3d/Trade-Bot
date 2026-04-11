#!/usr/bin/env python3
"""
portfolio.py — Single Source of Truth für alle Positionen

JEDES Script importiert dieses Modul statt eigene Dateien zu lesen.
Zwei Portfolios:
  - REAL: trading_config.json (Victors echtes Geld)
  - PAPER: SQLite paper_portfolio (Alberts Übungsdepot)

Verwendung:
  from portfolio import Portfolio
  p = Portfolio()
  
  # Alle aktiven Ticker (real + paper)
  p.all_active_tickers()         → ['NVDA', 'MSFT', 'OXY', 'FRO', ...]
  
  # Nur echte Positionen
  p.real_positions()             → [Position(...), ...]
  p.real_active_tickers()        → ['NVDA', 'MSFT', ...]
  
  # Nur Paper
  p.paper_positions()            → [Position(...), ...]
  p.paper_active_tickers()       → ['OXY', 'FRO', ...]
  
  # Ist eine Position aktiv?
  p.is_active('RHM.DE')          → False (verkauft)
  p.is_active('NVDA')            → True
  
  # Position-Details
  p.get('NVDA')                  → Position(ticker='NVDA', entry=167.88, ...)
  
  # Watchlist (noch nicht gekauft, aber beobachtet)
  p.watchlist_tickers()          → ['AG', 'ASML']
  
  # Strategien: welche Tickers gehören zu welcher Strategie?
  p.tickers_for_strategy('PS1')  → ['OXY', 'TTE.PA', 'FRO']
  p.strategy_for_ticker('OXY')   → 'PS1'
  
  # Events: Was ist zuletzt passiert?
  p.recent_events(hours=24)      → [Event(type='CLOSED', ticker='RHM.DE', ...)]
"""

import json, sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
CONFIG_PATH = WS / "trading_config.json"
DB_PATH = WS / "data" / "trading.db"

def sync_config_from_github():
    """Zieht trading_config.json frisch aus GitHub — Single Source of Truth."""
    import urllib.request, base64, os
    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        return False
    try:
        url = 'https://api.github.com/repos/Vic3d/Trade-Bot/contents/trading_config.json'
        req = urllib.request.Request(url, headers={
            'Authorization': f'token {token}',
            'User-Agent': 'Albert-TradeMind'
        })
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        content = base64.b64decode(d['content']).decode()
        CONFIG_PATH.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        return False
EVENTS_PATH = WS / "data" / "portfolio_events.json"
STRATEGIES_PATH = WS / "data" / "strategies.json"

# Strategy → Tickers mapping (dynamisch aus config/DB)
# Wird NICHT hardcoded — wird aus den Daten gelesen

def _load_strategies_json():
    """Lädt strategies.json (Single Source of Truth). Returns {} on error."""
    if not STRATEGIES_PATH.exists():
        return {}
    try:
        data = json.loads(STRATEGIES_PATH.read_text(encoding="utf-8"))
        # Entferne emerging_themes — das ist kein Strategie-Eintrag
        data.pop("emerging_themes", None)
        return data
    except Exception:
        return {}


@dataclass
class Position:
    ticker: str
    name: str = ""
    portfolio: str = "real"  # "real" | "paper"
    status: str = "OPEN"     # "OPEN" | "CLOSED" | "WATCHLIST"
    strategy: str = ""
    entry_eur: float = 0
    stop_eur: float = 0
    target_eur: float = 0
    shares: float = 0
    entry_date: str = ""
    close_price: float = 0
    close_date: str = ""
    pnl_eur: float = 0
    pnl_pct: float = 0
    notes: str = ""
    yahoo: str = ""  # Yahoo Finance Ticker

    def is_open(self):
        return self.status == "OPEN"

    def is_closed(self):
        return self.status == "CLOSED"

    def is_watchlist(self):
        return self.status == "WATCHLIST"


@dataclass
class Event:
    timestamp: str
    event_type: str  # OPENED, CLOSED, STOP_UPDATED, STRATEGY_CHANGED
    ticker: str
    portfolio: str   # real | paper
    details: dict = field(default_factory=dict)


class Portfolio:
    def __init__(self):
        self._real = {}       # ticker → Position
        self._paper = {}      # ticker → Position
        self._watchlist = {}  # ticker → Position
        self._events = []
        self._load_real()
        self._load_paper()
        self._load_events()

    def _load_real(self):
        """
        Liest echte Positionen — IMMER aus positions-live.md (Single Source of Truth).
        Fallback: trading_config.json wenn positions-live.md fehlt.
        """
        import re, subprocess

        POSITIONS_MD = WS / "memory/positions-live.md"

        # ── Primär: positions-live.md ──────────────────────────────────────────
        if POSITIONS_MD.exists():
            try:
                text = POSITIONS_MD.read_text(encoding="utf-8")
                active_section = re.search(
                    r"## 🟢 Aktive Positionen\s*\n.*?\n\|[-|]+\|\n(.*?)(?=\n---|\n## |\Z)",
                    text, re.DOTALL
                )
                if active_section:
                    def to_float(s):
                        s = s.replace("€", "").replace("%", "").strip()
                        try: return float(s)
                        except: return 0.0

                    for line in active_section.group(1).strip().split("\n"):
                        line = line.strip()
                        if not line.startswith("|") or line.startswith("|---"):
                            continue
                        cols = [c.strip() for c in line.strip("|").split("|")]
                        if len(cols) < 4:
                            continue
                        name_ticker = cols[0]
                        ticker_match = re.search(r"\(([^)]+)\)", name_ticker)
                        if not ticker_match:
                            continue
                        ticker = ticker_match.group(1).upper()
                        name   = re.sub(r"\s*\([^)]+\)", "", name_ticker).strip()
                        entry  = to_float(cols[1])
                        stop   = to_float(cols[2])
                        notiz  = cols[5] if len(cols) > 5 else ""
                        p = Position(
                            ticker=ticker,
                            name=name,
                            portfolio="real",
                            status="OPEN",
                            entry_eur=entry,
                            stop_eur=stop,
                            notes=notiz,
                            yahoo=ticker,
                        )
                        self._real[ticker] = p
                    if self._real:
                        return  # Erfolgreich aus positions-live.md geladen
            except Exception as e:
                print(f"⚠ Portfolio: Fehler beim Lesen von positions-live.md: {e}")

        # ── Fallback: trading_config.json ─────────────────────────────────────
        print("⚠ Portfolio: positions-live.md nicht verfügbar — Fallback auf trading_config.json")
        sync_config_from_github()
        if not CONFIG_PATH.exists():
            return
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            positions = config.get("positions", {})
            if isinstance(positions, dict):
                items = positions.items()
            else:
                items = [(p.get("ticker", ""), p) for p in positions if isinstance(p, dict)]
            for ticker, pos in items:
                if not ticker:
                    continue
                status = pos.get("status", "OPEN")
                if pos.get("closed"):
                    status = "CLOSED"
                p = Position(
                    ticker=ticker.upper(),
                    name=pos.get("name", ticker),
                    portfolio="real",
                    status=status,
                    strategy=pos.get("strategy", ""),
                    entry_eur=pos.get("entry_eur", 0),
                    stop_eur=pos.get("stop_eur", 0),
                    target_eur=(pos.get("targets_eur", [None]) or [None])[0] or 0,
                    notes=pos.get("notes", ""),
                    yahoo=pos.get("yahoo", ticker),
                )
                self._real[ticker.upper()] = p
        except Exception as e:
            print(f"⚠ Portfolio: Fehler beim Laden von trading_config.json: {e}")

    def _load_paper(self):
        """Liest Paper-Positionen aus SQLite."""
        if not DB_PATH.exists():
            return
        try:
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM paper_portfolio ORDER BY entry_date").fetchall()
            for row in rows:
                p = Position(
                    ticker=row["ticker"],
                    portfolio="paper",
                    status=row["status"],
                    strategy=row["strategy"] or "",
                    entry_eur=row["entry_price"] or 0,
                    stop_eur=row["stop_price"] or 0,
                    target_eur=row["target_price"] or 0,
                    shares=row["shares"] or 0,
                    entry_date=row["entry_date"] or "",
                    close_price=row["close_price"] or 0,
                    close_date=row["close_date"] or "",
                    pnl_eur=row["pnl_eur"] or 0,
                    pnl_pct=row["pnl_pct"] or 0,
                    notes=row["notes"] or "",
                )
                # Paper kann mehrere Positionen gleicher Ticker haben
                key = f"{row['ticker']}_{row['id']}"
                self._paper[key] = p
            conn.close()
        except Exception as e:
            print(f"⚠ Portfolio: Fehler beim Laden von SQLite: {e}")

    def _load_events(self):
        """Liest Events."""
        if not EVENTS_PATH.exists():
            return
        try:
            data = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
            self._events = [
                Event(
                    timestamp=e.get("timestamp", ""),
                    event_type=e.get("event_type", ""),
                    ticker=e.get("ticker", ""),
                    portfolio=e.get("portfolio", ""),
                    details=e.get("details", {}),
                )
                for e in data
            ]
        except Exception:
            self._events = []

    # ── Abfragen ──

    def real_positions(self, include_closed=False):
        """Alle echten Positionen."""
        return [p for p in self._real.values()
                if include_closed or p.is_open()]

    def paper_positions(self, include_closed=False):
        """Alle Paper-Positionen."""
        return [p for p in self._paper.values()
                if include_closed or p.is_open()]

    def real_active_tickers(self):
        """Aktive echte Ticker."""
        return sorted(set(p.ticker for p in self._real.values() if p.is_open()))

    def paper_active_tickers(self):
        """Aktive Paper-Ticker."""
        return sorted(set(p.ticker for p in self._paper.values() if p.is_open()))

    def all_active_tickers(self):
        """Alle aktiven Ticker (real + paper, dedupliziert)."""
        return sorted(set(self.real_active_tickers() + self.paper_active_tickers()))

    def is_active(self, ticker):
        """Ist dieser Ticker in irgendeinem Portfolio aktiv?"""
        return ticker in self.all_active_tickers()

    def get(self, ticker, portfolio="any"):
        """Position holen. portfolio: 'real', 'paper', 'any'."""
        if portfolio in ("real", "any"):
            if ticker in self._real:
                return self._real[ticker]
        if portfolio in ("paper", "any"):
            for key, p in self._paper.items():
                if p.ticker == ticker and p.is_open():
                    return p
        return None

    def tickers_for_strategy(self, strategy):
        """Alle aktiven Ticker einer Strategie."""
        tickers = set()
        for p in self._real.values():
            if p.strategy == strategy and p.is_open():
                tickers.add(p.ticker)
        for p in self._paper.values():
            if p.strategy == strategy and p.is_open():
                tickers.add(p.ticker)
        return sorted(tickers)

    def strategy_for_ticker(self, ticker):
        """
        Strategie eines Tickers (sucht in real, dann paper, dann strategies.json).
        """
        p = self.get(ticker, "real")
        if p and p.strategy:
            return p.strategy
        p = self.get(ticker, "paper")
        if p and p.strategy:
            return p.strategy
        # Fallback: strategies.json durchsuchen
        strategies = _load_strategies_json()
        for strat_id, strat in strategies.items():
            all_tickers = (strat.get("tickers") or []) + (strat.get("watchlist_tickers") or [])
            if ticker in all_tickers:
                return strat_id
        return ""

    def strategy_details(self, strategy_id):
        """
        Gibt die vollständige Strategie-Definition aus strategies.json zurück.
        Enthält: genesis, thesis, health, kill_trigger, learning_question, etc.
        Returns None wenn nicht gefunden.
        """
        strategies = _load_strategies_json()
        return strategies.get(strategy_id)

    def strategies_summary(self):
        """
        Schnellübersicht aller Strategien mit Health-Status.
        Returns list of dicts mit: id, name, type, health, status, sector, tickers
        """
        strategies = _load_strategies_json()
        result = []
        for strat_id, strat in strategies.items():
            result.append({
                "id": strat_id,
                "name": strat.get("name", strat_id),
                "type": strat.get("type", "unknown"),
                "health": strat.get("health", "unknown"),
                "status": strat.get("status", "unknown"),
                "sector": strat.get("sector", ""),
                "tickers": strat.get("tickers", []),
                "thesis": strat.get("thesis", ""),
                "learning_question": strat.get("learning_question", ""),
            })
        return result

    def watchlist_tickers(self):
        """Ticker auf Watchlist (status=WATCHLIST in config)."""
        return sorted(set(
            p.ticker for p in self._real.values()
            if p.status == "WATCHLIST"
        ))

    # ── Events ──

    def log_event(self, event_type, ticker, portfolio="real", details=None):
        """Event loggen (OPENED, CLOSED, STOP_UPDATED, etc.)."""
        event = Event(
            timestamp=datetime.now().isoformat(),
            event_type=event_type,
            ticker=ticker,
            portfolio=portfolio,
            details=details or {},
        )
        self._events.append(event)
        self._save_events()

    def recent_events(self, hours=24):
        """Events der letzten N Stunden."""
        cutoff = datetime.now() - timedelta(hours=hours)
        result = []
        for e in self._events:
            try:
                ts = datetime.fromisoformat(e.timestamp)
                if ts > cutoff:
                    result.append(e)
            except:
                pass
        return result

    def _save_events(self):
        """Events auf Disk speichern (max 100)."""
        EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(e) for e in self._events[-100:]]
        EVENTS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # ── Ausgabe ──

    def summary(self):
        """Kurze Zusammenfassung."""
        real_open = len(self.real_active_tickers())
        paper_open = len(self.paper_active_tickers())
        watchlist = len(self.watchlist_tickers())
        return {
            "real_open": real_open,
            "real_tickers": self.real_active_tickers(),
            "paper_open": paper_open,
            "paper_tickers": self.paper_active_tickers(),
            "watchlist": self.watchlist_tickers(),
            "all_active": self.all_active_tickers(),
        }

    def __repr__(self):
        s = self.summary()
        return (f"Portfolio(real={s['real_open']} {s['real_tickers']}, "
                f"paper={s['paper_open']} {s['paper_tickers']}, "
                f"watchlist={s['watchlist']})")


# ── Mutationen: Echtes Portfolio ──

def close_real_position(ticker, exit_price=None, reason=""):
    """
    Schließt eine echte Position und aktualisiert ALLE relevanten Dateien.
    
    Aktualisiert:
      1. trading_config.json (status → CLOSED)
      2. portfolio_events.json (Event loggen)
      3. strategien.md (Position aus Strategie entfernen)  ← TODO
    
    NICHT aktualisiert (manuell bei Gelegenheit):
      - MEMORY.md (Portfolio-Tabelle)
      - trade-decisions.md
    """
    if not CONFIG_PATH.exists():
        return False, "trading_config.json nicht gefunden"

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    positions = config.get("positions", {})

    if ticker not in positions:
        return False, f"{ticker} nicht in trading_config.json"

    pos = positions[ticker]
    if pos.get("status") == "CLOSED":
        return False, f"{ticker} ist bereits geschlossen"

    # 1. Config updaten
    pos["status"] = "CLOSED"
    if exit_price:
        pos["exit_eur"] = exit_price
    if reason:
        pos["close_reason"] = reason
    pos["close_date"] = datetime.now().strftime("%Y-%m-%d")

    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))

    # 2. Event loggen
    p = Portfolio()
    p.log_event("CLOSED", ticker, "real", {
        "exit_price": exit_price,
        "reason": reason,
        "entry_price": pos.get("entry_eur", 0),
    })

    return True, f"{ticker} geschlossen in trading_config.json + Event geloggt"


def add_to_watchlist(ticker, name="", strategy="", notes=""):
    """Fügt Ticker zur Watchlist in trading_config.json hinzu."""
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    positions = config.setdefault("positions", {})

    positions[ticker] = {
        "name": name or ticker,
        "status": "WATCHLIST",
        "strategy": strategy,
        "notes": notes,
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    return True


def remove_from_watchlist(ticker):
    """Entfernt Ticker von der Watchlist."""
    if not CONFIG_PATH.exists():
        return False
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    positions = config.get("positions", {})
    if ticker in positions and positions[ticker].get("status") == "WATCHLIST":
        del positions[ticker]
        CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))
        return True
    return False


# ── Convenience ──

def get_portfolio():
    """Factory: neues Portfolio-Objekt."""
    return Portfolio()


if __name__ == "__main__":
    p = Portfolio()
    print(p)
    print()
    s = p.summary()
    print(f"Echtes Portfolio ({s['real_open']} Positionen): {', '.join(s['real_tickers'])}")
    print(f"Paper Portfolio ({s['paper_open']} Positionen): {', '.join(s['paper_tickers'])}")
    if s['watchlist']:
        print(f"Watchlist: {', '.join(s['watchlist'])}")
    print(f"\nAlle aktiven Ticker: {', '.join(s['all_active'])}")

    # Demonstriere is_active
    for t in ['NVDA', 'RHM.DE', 'OXY', 'MOS', 'AAPL']:
        print(f"  {t}: {'✅ aktiv' if p.is_active(t) else '❌ nicht im Portfolio'}")
