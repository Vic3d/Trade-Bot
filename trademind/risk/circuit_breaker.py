"""
trademind/risk/circuit_breaker.py — Circuit Breaker System

Schützt das Portfolio vor katastrophalen Verlusten durch automatische
Handelsstopps bei definierten Schwellenwerten.

Breaker:
    daily_loss_limit:   Max -€500/Tag → Trades pausiert
    weekly_loss_limit:  Max -€1500/Woche → Nur Monitoring
    max_drawdown:       Max -€3000 vom Peak → ALLES schließen
    consecutive_losses: 5 Verlierer am Stück → 24h Pause
    vix_panic:          VIX > 45 → Nur schließen, keine neuen Trades
"""
from datetime import datetime, timedelta

from trademind.core.vix import get_vix

CIRCUIT_BREAKERS = {
    "daily_loss_limit":   -500,
    "weekly_loss_limit":  -1500,
    "max_drawdown":       -3000,
    "consecutive_losses": 5,
    "vix_panic":          45,
}

CLOSED_STATUSES = ("CLOSED", "WIN", "LOSS", "STOPPED")


def _daily_pnl(db) -> float:
    """P&L aller heute geschlossenen Trades."""
    today = datetime.now().strftime("%Y-%m-%d")
    row = db.execute(
        """
        SELECT COALESCE(SUM(pnl_eur), 0) AS total
        FROM trades
        WHERE status IN ('CLOSED','WIN','LOSS','STOPPED')
          AND exit_date LIKE ?
        """,
        (today + "%",),
    ).fetchone()
    return float(row["total"] or 0)


def _weekly_pnl(db) -> float:
    """P&L aller Trades der letzten 7 Tage."""
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    row = db.execute(
        """
        SELECT COALESCE(SUM(pnl_eur), 0) AS total
        FROM trades
        WHERE status IN ('CLOSED','WIN','LOSS','STOPPED')
          AND exit_date >= ?
        """,
        (cutoff,),
    ).fetchone()
    return float(row["total"] or 0)


def _max_drawdown(db) -> float:
    """
    Drawdown vom höchsten Portfolio-Stand (paper_performance.total_value).
    Negativ = Verlust vom Peak.
    """
    rows = db.execute(
        "SELECT total_value FROM paper_performance ORDER BY date ASC"
    ).fetchall()

    if not rows:
        # Fallback: aus paper_fund
        fund = db.execute(
            "SELECT value FROM paper_fund WHERE key='starting_capital'"
        ).fetchone()
        return 0.0

    values = [r["total_value"] for r in rows]
    peak = values[0]
    max_dd = 0.0
    running_peak = peak
    for v in values:
        running_peak = max(running_peak, v)
        dd = v - running_peak
        max_dd = min(max_dd, dd)

    return round(max_dd, 2)


def _consecutive_losses(db) -> int:
    """Anzahl der letzten geschlossenen Trades, die alle Verluste waren."""
    rows = db.execute(
        """
        SELECT pnl_eur
        FROM trades
        WHERE status IN ('CLOSED','WIN','LOSS','STOPPED')
        ORDER BY exit_date DESC
        LIMIT 20
        """
    ).fetchall()

    count = 0
    for r in rows:
        pnl = r["pnl_eur"] or 0
        if pnl < 0:
            count += 1
        else:
            break  # Gewinntrade → Streak unterbrochen
    return count


def _current_vix() -> float:
    """Aktueller VIX von Yahoo Finance."""
    try:
        return get_vix()
    except Exception:
        return 0.0


# ── Public API ────────────────────────────────────────────────────────────────

def check_circuit_breakers(db=None) -> dict:
    """
    Prüft alle Circuit Breakers gegen aktuelle Daten.

    Args:
        db: sqlite3.Connection (optional — wird selbst geholt wenn nicht übergeben)

    Returns:
        {
            'trading_allowed': bool,
            'breakers_triggered': ['daily_loss_limit', ...],
            'details': {
                'daily_pnl': -320.0,
                'weekly_pnl': -890.0,
                'drawdown': -1200.0,
                'consecutive_losses': 3,
                'current_vix': 27.5,
            },
            'resume_at': '2026-03-27 08:00' or None,
        }
    """
    _own_db = False
    if db is None:
        from trademind.core.db import get_db
        db = get_db()
        _own_db = True

    try:
        daily_pnl = _daily_pnl(db)
        weekly_pnl = _weekly_pnl(db)
        drawdown = _max_drawdown(db)
        consec = _consecutive_losses(db)
        vix = _current_vix()

        details = {
            "daily_pnl": round(daily_pnl, 2),
            "weekly_pnl": round(weekly_pnl, 2),
            "drawdown": round(drawdown, 2),
            "consecutive_losses": consec,
            "current_vix": round(vix, 2),
        }

        triggered = []

        if daily_pnl <= CIRCUIT_BREAKERS["daily_loss_limit"]:
            triggered.append("daily_loss_limit")

        if weekly_pnl <= CIRCUIT_BREAKERS["weekly_loss_limit"]:
            triggered.append("weekly_loss_limit")

        if drawdown <= CIRCUIT_BREAKERS["max_drawdown"]:
            triggered.append("max_drawdown")

        if consec >= CIRCUIT_BREAKERS["consecutive_losses"]:
            triggered.append("consecutive_losses")

        if vix >= CIRCUIT_BREAKERS["vix_panic"]:
            triggered.append("vix_panic")

        trading_allowed = len(triggered) == 0

        # Resume-Zeit berechnen
        resume_at = None
        if triggered:
            if "max_drawdown" in triggered:
                # Sehr ernst — kein automatisches Resume
                resume_at = "MANUELL (Max Drawdown überschritten)"
            elif "daily_loss_limit" in triggered:
                # Morgen früh
                tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 08:00")
                resume_at = tomorrow
            elif "consecutive_losses" in triggered:
                # 24h Pause
                resume_at = (datetime.now() + timedelta(hours=24)).strftime(
                    "%Y-%m-%d %H:%M"
                )
            elif "weekly_loss_limit" in triggered:
                # Nächste Woche Montag
                days_to_monday = (7 - datetime.now().weekday()) % 7 or 7
                resume_at = (datetime.now() + timedelta(days=days_to_monday)).strftime(
                    "%Y-%m-%d 08:00"
                )
            elif "vix_panic" in triggered:
                resume_at = "Wenn VIX < 45 (live prüfen)"

        return {
            "trading_allowed": trading_allowed,
            "breakers_triggered": triggered,
            "details": details,
            "resume_at": resume_at,
        }

    finally:
        if _own_db:
            db.close()


def get_breaker_summary(result: dict) -> str:
    """Formatiert Circuit-Breaker-Ergebnis als lesbaren String."""
    d = result["details"]
    lines = [
        f"  Daily P&L:         {d['daily_pnl']:+.0f}€  (Limit: {CIRCUIT_BREAKERS['daily_loss_limit']}€)",
        f"  Weekly P&L:        {d['weekly_pnl']:+.0f}€  (Limit: {CIRCUIT_BREAKERS['weekly_loss_limit']}€)",
        f"  Max Drawdown:      {d['drawdown']:+.0f}€  (Limit: {CIRCUIT_BREAKERS['max_drawdown']}€)",
        f"  Consec. Losses:    {d['consecutive_losses']}  (Limit: {CIRCUIT_BREAKERS['consecutive_losses']})",
        f"  Current VIX:       {d['current_vix']:.1f}  (Panic: >{CIRCUIT_BREAKERS['vix_panic']})",
    ]
    if result["breakers_triggered"]:
        lines.append(
            f"\n  🚨 TRIGGERED: {', '.join(result['breakers_triggered'])}"
        )
        if result["resume_at"]:
            lines.append(f"  ⏰ Resume: {result['resume_at']}")
    else:
        lines.append("\n  ✅ Alle Circuit Breaker OK — Trading erlaubt")
    return "\n".join(lines)
