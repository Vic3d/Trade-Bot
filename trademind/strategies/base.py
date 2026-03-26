"""
trademind/strategies/base.py — Abstrakte Basis-Klasse für alle Strategien

Jede Strategie implementiert dieses Interface. Einheitliches Scanning,
Positionsmanagement und Post-Mortem-Analyse.

Usage:
    from trademind.strategies.base import Strategy

    class MyStrategy(Strategy):
        @property
        def name(self): return 'MY'
        @property
        def max_positions(self): return 3
        def scan(self): ...
        def should_enter(self, signal): ...
        def should_exit(self, position): ...
        def post_mortem(self, trade): ...
"""
from abc import ABC, abstractmethod


class Strategy(ABC):
    """
    Abstrakte Basis-Klasse für alle TradeMind-Strategien.

    Jede Strategie muss 4 Methoden + 2 Properties implementieren.
    Das ermöglicht einheitliches Reporting, Backtesting und Post-Mortem.
    """

    # ── Properties (PFLICHT) ──────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategiename, z.B. 'SA', 'DT4', 'PS1'"""
        ...

    @property
    @abstractmethod
    def max_positions(self) -> int:
        """Maximale Anzahl gleichzeitiger Positionen."""
        ...

    # ── Methoden (PFLICHT) ────────────────────────────────────────────────────

    @abstractmethod
    def scan(self) -> list:
        """
        Markt scannen und Signale zurückgeben.

        Returns:
            list of Signal dicts — leer wenn keine Setups gefunden.
            Jedes Signal enthält mindestens: ticker, score, reason
        """
        ...

    @abstractmethod
    def should_enter(self, signal: dict) -> dict | None:
        """
        Signal bewerten und Trade-Vorschlag erstellen.

        Args:
            signal: dict aus scan() — mindestens {ticker, score, reason}

        Returns:
            TradeProposal dict mit entry, stop, target, shares, risk_eur
            oder None wenn kein Entry (Filter nicht erfüllt).
        """
        ...

    @abstractmethod
    def should_exit(self, position: dict) -> dict | None:
        """
        Offene Position prüfen — Exit empfehlen oder halten.

        Args:
            position: dict — offene Position aus DB

        Returns:
            ExitDecision dict mit reason, exit_type ('stop'|'target'|'thesis_dead'|'manual')
            oder None wenn Position gehalten werden soll.
        """
        ...

    @abstractmethod
    def post_mortem(self, trade: dict) -> dict:
        """
        Geschlossenen Trade analysieren und Lektionen extrahieren.

        Args:
            trade: dict — vollständiger Trade aus DB inkl. P&L

        Returns:
            dict mit: lesson, what_worked, what_failed, quality_score (1-10)
        """
        ...

    # ── Optionale Methoden (mit Default-Implementierung) ─────────────────────

    @property
    def min_crv(self) -> float:
        """Mindest-CRV für Entry. Default: 3.0"""
        return 3.0

    @property
    def description(self) -> str:
        """Kurze Strategiebeschreibung."""
        return f"Strategy '{self.name}'"

    def __repr__(self) -> str:
        return f"<Strategy name={self.name!r} max_positions={self.max_positions}>"
