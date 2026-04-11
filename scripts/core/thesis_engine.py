#!/usr/bin/env python3.13
"""
thesis_engine.py — Thesen-Lifecycle-Management
===============================================
Verwaltet: PROPOSED → EVALUATING → ACTIVE → MONITORING → DEGRADED → INVALIDATED

Thesis-Status-Maschine:
  ACTIVE      : These ist aktiv, Entries erlaubt
  DEGRADED    : Kill-Trigger teilweise gefeuert, keine neuen Entries
  INVALIDATED : These ungültig, alle Positionen queuen für Exit
  PAUSED      : Manuell pausiert (CEO-Direktive o.ä.)
  WATCHING    : In Beobachtung, noch kein Entry

Status wird in thesis_status Tabelle (trading.db) gespeichert.
Kill-Trigger kommen aus data/strategies.json.

Albert | TradeMind v2 | 2026-04-10
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'execution'))
sys.path.insert(0, str(WS / 'scripts' / 'intelligence'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))

DB = WS / 'data' / 'trading.db'
STRATEGIES_JSON = WS / 'data' / 'strategies.json'

# Gültige Status-Werte
VALID_STATUSES = {'ACTIVE', 'DEGRADED', 'INVALIDATED', 'PAUSED', 'WATCHING', 'EVALUATING'}


# ─── DB Helpers ──────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _load_strategies() -> dict:
    """Lädt strategies.json — gibt leeres Dict bei Fehler."""
    try:
        return json.loads(STRATEGIES_JSON.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Kernfunktionen ───────────────────────────────────────────────────────────

def get_thesis_status(thesis_id: str) -> dict:
    """
    Liest aktuellen Status einer These aus DB.

    Returns dict mit Feldern: thesis_id, status, health_score,
    kill_trigger_fired, last_checked, notes, updated_at.
    Wenn nicht in DB: leeres Dict (These ist neu/unbekannt).
    """
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT * FROM thesis_status WHERE thesis_id = ?",
            (thesis_id,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {}
    except Exception as e:
        print(f"[thesis_engine] get_thesis_status({thesis_id}) Fehler: {e}")
        return {}


def set_thesis_status(thesis_id: str, status: str, notes: str = '') -> bool:
    """
    Schreibt/aktualisiert Status einer These in DB.

    Parameters:
        thesis_id : Strategie-ID (z.B. 'S2', 'PS17')
        status    : ACTIVE | DEGRADED | INVALIDATED | PAUSED | WATCHING
        notes     : Freitext-Notiz (Grund für Status-Änderung)

    Returns True bei Erfolg.
    """
    if status not in VALID_STATUSES:
        print(f"[thesis_engine] Ungültiger Status: {status}")
        return False

    now = _now_iso()
    try:
        conn = _get_db()
        existing = conn.execute(
            "SELECT id FROM thesis_status WHERE thesis_id = ?",
            (thesis_id,)
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE thesis_status
                SET status = ?, notes = ?, updated_at = ?
                WHERE thesis_id = ?
                """,
                (status, notes, now, thesis_id)
            )
        else:
            conn.execute(
                """
                INSERT INTO thesis_status
                    (thesis_id, status, health_score, kill_trigger_fired,
                     last_checked, notes, updated_at)
                VALUES (?, ?, 100, 0, ?, ?, ?)
                """,
                (thesis_id, status, now, notes, now)
            )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[thesis_engine] set_thesis_status({thesis_id}) Fehler: {e}")
        return False


def check_thesis_kill_trigger(thesis_id: str, news_texts: list) -> tuple:
    """
    Prüft ob einer der Kill-Trigger einer These in den News-Texten vorkommt.

    Parameters:
        thesis_id  : Strategie-ID
        news_texts : Liste von News-Headlines / Texten

    Returns:
        (True, matching_trigger_text)  wenn Kill-Trigger gefunden
        (False, '')                    wenn kein Match
    """
    strategies = _load_strategies()
    strategy = strategies.get(thesis_id)
    if not strategy:
        return (False, '')

    kill_trigger = strategy.get('kill_trigger', '')
    if not kill_trigger:
        return (False, '')

    # Kill-Trigger in Schlüsselwörter aufteilen (ODER-Logik)
    kill_keywords = _parse_kill_trigger(kill_trigger)

    combined_text = ' '.join(news_texts).lower()

    for keyword in kill_keywords:
        kw_lower = keyword.strip().lower()
        if kw_lower and kw_lower in combined_text:
            # Match gefunden — in thesis_checks loggen
            _log_thesis_check(
                thesis_id=thesis_id,
                news_headline=news_texts[0] if news_texts else '',
                direction='bearish',
                kill_trigger_match=1,
                action_taken=f"Kill-Trigger erkannt: '{kw_lower}'"
            )
            return (True, kw_lower)

    return (False, '')


def _parse_kill_trigger(kill_trigger: str) -> list:
    """
    Zerlegt Kill-Trigger-Text in einzelne Schlüsselwörter.
    Trennt bei 'ODER', 'OR', Semikolon, Komma.
    """
    import re
    # Trennzeichen: ODER, OR (Wortgrenze), |, ;
    parts = re.split(r'\bODER\b|\bOR\b|\||\;', kill_trigger, flags=re.IGNORECASE)
    keywords = []
    for part in parts:
        # Sonderzeichen entfernen, nur sinnvolle Schlüsselwörter
        cleaned = part.strip().strip('.,!?()[]')
        # Kurze Abkürzungen und Preis-Angaben (z.B. "$78") als Keyword erlaubt
        if len(cleaned) >= 4:
            keywords.append(cleaned)
    return keywords


def _log_thesis_check(thesis_id: str, news_headline: str, direction: str,
                      kill_trigger_match: int, action_taken: str):
    """Schreibt einen Eintrag in thesis_checks."""
    try:
        conn = _get_db()
        conn.execute(
            """
            INSERT INTO thesis_checks
                (thesis_id, checked_at, news_headline, direction,
                 kill_trigger_match, action_taken)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (thesis_id, _now_iso(), news_headline[:500], direction,
             kill_trigger_match, action_taken)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[thesis_engine] _log_thesis_check Fehler: {e}")


def get_active_theses() -> list:
    """
    Gibt Liste aller Thesen-IDs mit Status ACTIVE zurück.

    Kombiniert:
    1. Thesen in thesis_status Tabelle mit status='ACTIVE'
    2. Thesen aus strategies.json mit status='active' (die noch nicht in DB sind)

    Returns: list[str] z.B. ['S2', 'PS17', 'PS18', 'PS19', 'PS16', 'PS4', 'PS13', 'PS20']
    """
    active = set()

    # Aus DB lesen
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT thesis_id FROM thesis_status WHERE status = 'ACTIVE'"
        ).fetchall()
        conn.close()
        for row in rows:
            active.add(row['thesis_id'])
    except Exception as e:
        print(f"[thesis_engine] get_active_theses DB-Fehler: {e}")

    # Aus strategies.json — Thesen die noch nicht in DB sind
    try:
        strategies = _load_strategies()
        for thesis_id, strategy in strategies.items():
            s = strategy.get('status', '').lower()
            if s == 'active' and thesis_id not in active:
                # Noch kein DB-Eintrag — als ACTIVE betrachten (neu)
                active.add(thesis_id)
    except Exception as e:
        print(f"[thesis_engine] get_active_theses JSON-Fehler: {e}")

    return sorted(active)


def degrade_thesis(thesis_id: str, reason: str) -> bool:
    """
    Setzt eine These auf DEGRADED:
    - Keine neuen Entries mehr für diese These
    - Health Score reduziert auf 40
    - Discord-Alert wird gesendet

    Returns True bei Erfolg.
    """
    now = _now_iso()
    ok = set_thesis_status(thesis_id, 'DEGRADED', reason)
    if not ok:
        return False

    # Health Score reduzieren
    try:
        conn = _get_db()
        conn.execute(
            "UPDATE thesis_status SET health_score = 40, updated_at = ? WHERE thesis_id = ?",
            (now, thesis_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[thesis_engine] degrade_thesis health-update Fehler: {e}")

    # Discord Alert
    msg = (
        f"[TradeMind v2] THESIS DEGRADED: {thesis_id}\n"
        f"Grund: {reason}\n"
        f"Neue Entries fuer diese These werden blockiert.\n"
        f"Zeit: {now}"
    )
    _send_discord(msg)

    print(f"[thesis_engine] {thesis_id} -> DEGRADED: {reason}")
    return True


def invalidate_thesis(thesis_id: str, reason: str) -> bool:
    """
    Invalidiert eine These vollständig:
    - Status → INVALIDATED
    - Health Score → 0
    - Kill-Trigger-Flag setzen
    - Alle offenen Positionen dieser These werden für Exit gequeued
    - Discord-Alert wird gesendet

    Returns True bei Erfolg.
    """
    now = _now_iso()
    ok = set_thesis_status(thesis_id, 'INVALIDATED', reason)
    if not ok:
        return False

    # Health Score auf 0, kill_trigger_fired setzen
    try:
        conn = _get_db()
        conn.execute(
            """
            UPDATE thesis_status
            SET health_score = 0, kill_trigger_fired = 1, updated_at = ?
            WHERE thesis_id = ?
            """,
            (now, thesis_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[thesis_engine] invalidate_thesis update Fehler: {e}")

    # Offene Positionen für Exit queuen
    affected = _queue_positions_for_exit(thesis_id, reason)

    # Discord Alert
    msg = (
        f"[TradeMind v2] THESIS INVALIDATED: {thesis_id}\n"
        f"Grund: {reason}\n"
        f"Kill-Trigger ausgeloest!\n"
        f"Betroffene offene Positionen: {affected}\n"
        f"Zeit: {now}"
    )
    _send_discord(msg)

    print(f"[thesis_engine] {thesis_id} -> INVALIDATED: {reason} | {affected} Positionen betroffen")
    return True


def _queue_positions_for_exit(thesis_id: str, reason: str) -> int:
    """
    Markiert alle offenen Positionen einer These mit Exit-Notiz.
    Gibt Anzahl betroffener Positionen zurück.
    """
    now = _now_iso()
    try:
        conn = _get_db()
        result = conn.execute(
            """
            UPDATE paper_portfolio
            SET notes = notes || ' | EXIT_QUEUED: ' || ? || ' [' || ? || ']'
            WHERE strategy = ? AND status = 'OPEN'
            """,
            (reason[:100], now, thesis_id)
        )
        affected = result.rowcount
        conn.commit()
        conn.close()
        return affected
    except Exception as e:
        print(f"[thesis_engine] _queue_positions_for_exit Fehler: {e}")
        return 0


def _send_discord(message: str) -> bool:
    """Sendet Discord-Alert. Fehler werden unterdrückt."""
    try:
        from discord_sender import send
        return send(message)
    except Exception as e:
        print(f"[thesis_engine] Discord-Alert fehlgeschlagen: {e}")
        return False


def run_monitoring_cycle() -> dict:
    """
    Monitoring-Zyklus: Läuft alle 30min.
    Prüft alle aktiven Thesen gegen die neuesten News.

    Ablauf:
    1. Hole alle aktiven Thesen
    2. Lade neueste News aus DB (news_pipeline Tabelle)
    3. Prüfe Kill-Trigger für jede These
    4. Bei Match: degrade_thesis() oder invalidate_thesis()
    5. Aktualisiere last_checked

    Returns: dict mit Ergebnissen (für Logging/Monitoring)
    """
    now = _now_iso()
    results = {
        'checked_at': now,
        'theses_checked': 0,
        'triggers_fired': [],
        'degraded': [],
        'errors': [],
    }

    active_theses = get_active_theses()
    if not active_theses:
        return results

    # Neueste News aus DB holen (letzte 2 Stunden)
    recent_news = _get_recent_news(hours=2)
    if not recent_news:
        # Fallback: letzte 24h
        recent_news = _get_recent_news(hours=24)

    results['theses_checked'] = len(active_theses)

    strategies = _load_strategies()

    for thesis_id in active_theses:
        try:
            # ── Kill-Trigger prüfen ────────────────────────────────────
            triggered, match_text = check_thesis_kill_trigger(thesis_id, recent_news)
            if triggered:
                results['triggers_fired'].append({'thesis_id': thesis_id, 'match': match_text})
                degrade_thesis(thesis_id, f"Kill-Trigger in News: '{match_text}'")
                results['degraded'].append(thesis_id)

            # ── Entry-Trigger prüfen (positiver Match → thesis_checks) ─
            # Damit conviction_scorer._check_entry_trigger_bonus() Daten hat
            strategy_cfg = strategies.get(thesis_id, {})
            entry_trigger = strategy_cfg.get('entry_trigger', '')
            if entry_trigger and not triggered:
                import re as _re
                entry_kws = [
                    k.strip().lower() for k in
                    _re.split(r'[,;|]|\bOR\b|\bODER\b', entry_trigger, flags=_re.IGNORECASE)
                    if len(k.strip()) >= 5
                ]
                combined = ' '.join(recent_news).lower()
                entry_matches = [kw for kw in entry_kws if kw in combined]
                if entry_matches:
                    for match_kw in entry_matches[:3]:
                        matching_headline = next(
                            (h for h in recent_news if match_kw in h.lower()),
                            recent_news[0] if recent_news else ''
                        )
                        _log_thesis_check(
                            thesis_id=thesis_id,
                            news_headline=matching_headline,
                            direction='bullish',
                            kill_trigger_match=0,
                            action_taken=f"Entry-Trigger bestaetigt: '{match_kw}'"
                        )
                    results.setdefault('entry_confirmed', []).append(thesis_id)

            # last_checked aktualisieren
            try:
                conn = _get_db()
                conn.execute(
                    "UPDATE thesis_status SET last_checked = ? WHERE thesis_id = ?",
                    (now, thesis_id)
                )
                conn.commit()
                conn.close()
            except Exception:
                pass

        except Exception as e:
            results['errors'].append({'thesis_id': thesis_id, 'error': str(e)})

    return results


def _get_recent_news(hours: int = 2) -> list:
    """
    Holt aktuelle News-Headlines aus der DB.
    Versucht mehrere mögliche Tabellen-Namen.
    Gibt Liste von Strings zurück.
    """
    headlines = []
    try:
        conn = _get_db()

        # Versuche news_items Tabelle
        try:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            rows = conn.execute(
                """
                SELECT title, summary FROM news_items
                WHERE published_at > ?
                ORDER BY published_at DESC
                LIMIT 100
                """,
                (cutoff,)
            ).fetchall()
            for row in rows:
                if row[0]:
                    headlines.append(str(row[0]))
                if row[1]:
                    headlines.append(str(row[1]))
        except Exception:
            pass

        # Fallback: news_pipeline Tabelle
        if not headlines:
            try:
                from datetime import timedelta
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
                rows = conn.execute(
                    """
                    SELECT headline FROM news_pipeline
                    WHERE created_at > ?
                    ORDER BY created_at DESC
                    LIMIT 100
                    """,
                    (cutoff,)
                ).fetchall()
                for row in rows:
                    if row[0]:
                        headlines.append(str(row[0]))
            except Exception:
                pass

        conn.close()
    except Exception as e:
        print(f"[thesis_engine] _get_recent_news Fehler: {e}")

    return headlines


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys as _sys

    args = _sys.argv[1:]

    if '--status' in args and len(args) >= 2:
        idx = args.index('--status')
        tid = args[idx + 1] if idx + 1 < len(args) else None
        if tid:
            st = get_thesis_status(tid)
            print(f"Status [{tid}]: {st}")

    elif '--active' in args:
        active = get_active_theses()
        print(f"Aktive Thesen ({len(active)}): {active}")

    elif '--monitor' in args:
        print("Starte Monitoring-Zyklus...")
        res = run_monitoring_cycle()
        print(f"Geprueft: {res['theses_checked']}")
        print(f"Trigger gefeuert: {res['triggers_fired']}")
        print(f"Degradiert: {res['degraded']}")
        if res['errors']:
            print(f"Fehler: {res['errors']}")

    elif '--degrade' in args and len(args) >= 3:
        idx = args.index('--degrade')
        tid = args[idx + 1]
        reason = args[idx + 2]
        ok = degrade_thesis(tid, reason)
        print(f"degrade_thesis({tid}): {'OK' if ok else 'FEHLER'}")

    elif '--invalidate' in args and len(args) >= 3:
        idx = args.index('--invalidate')
        tid = args[idx + 1]
        reason = args[idx + 2]
        ok = invalidate_thesis(tid, reason)
        print(f"invalidate_thesis({tid}): {'OK' if ok else 'FEHLER'}")

    else:
        print("Usage:")
        print("  python3.13 thesis_engine.py --active")
        print("  python3.13 thesis_engine.py --status S2")
        print("  python3.13 thesis_engine.py --monitor")
        print("  python3.13 thesis_engine.py --degrade PS17 'Grund'")
        print("  python3.13 thesis_engine.py --invalidate PS1 'Kill-Trigger: Iran Deal'")
