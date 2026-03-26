"""
trademind/core/db.py — Einziger Datenbankzugang

Usage:
    from trademind.core.db import get_db

    with get_db() as db:
        rows = db.execute("SELECT * FROM trades").fetchall()
        # auto-commit on exit, rollback on exception
"""
import sqlite3
from contextlib import contextmanager
from trademind.core.config import DB_PATH


def get_db() -> sqlite3.Connection:
    """
    Gibt eine sqlite3-Connection mit row_factory zurück.
    Für einmaligen Gebrauch ohne Context-Manager (legacy-kompatibel).
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def managed_db():
    """
    Context-Manager mit auto-commit und rollback bei Exception.

    Usage:
        with managed_db() as db:
            db.execute("UPDATE trades SET ...")
        # → commit automatisch
    """
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
