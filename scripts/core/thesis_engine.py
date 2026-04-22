#!/usr/bin/env python3
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
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    # scripts/subdir/ -> go up 2 levels to reach WS root
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'execution'))
sys.path.insert(0, str(WS / 'scripts' / 'intelligence'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))
from atomic_json import atomic_write_json

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
            # Negations-Check: "ceasefire stalled" ≠ echte Feuerpause
            if _has_negation_context(combined_text, kw_lower):
                _log_thesis_check(
                    thesis_id=thesis_id,
                    news_headline=news_texts[0] if news_texts else '',
                    direction='neutral',
                    kill_trigger_match=0,
                    action_taken=f"Kill-Trigger '{kw_lower}' NEGIERT (Kontext-Check)"
                )
                continue  # Nächstes Keyword prüfen

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


def _parse_kill_trigger(kill_trigger) -> list:
    """
    Zerlegt Kill-Trigger in einzelne Schlüsselwörter.
    Akzeptiert String (Legacy) ODER Liste (Phase 22+).
    Trennt String bei 'ODER', 'OR', Pipe, Semikolon.
    """
    import re
    # Phase 22+: kill_trigger ist bereits eine Liste
    if isinstance(kill_trigger, list):
        return [str(x).strip().strip('.,!?()[]') for x in kill_trigger if str(x).strip()]
    if not isinstance(kill_trigger, str):
        return []
    parts = re.split(r'\bODER\b|\bOR\b|\||\;', kill_trigger, flags=re.IGNORECASE)
    keywords = []
    for part in parts:
        cleaned = part.strip().strip('.,!?()[]')
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


def _has_negation_context(text: str, keyword: str) -> bool:
    """
    Prüft ob ein Kill-Trigger-Keyword im Kontext negiert wird.
    z.B. "ceasefire talks stalled" → ceasefire ist negiert → kein Kill-Trigger.

    Returns True wenn Negation gefunden (= Kill-Trigger NICHT feuern).
    """
    NEGATION_WORDS = {
        'stalled', 'failed', 'rejected', 'unlikely', 'denied',
        'not', 'no ', 'postponed', 'delayed', 'collapsed',
        'canceled', 'cancelled', 'breaks down', 'broke down',
        'ruled out', 'dismissed', 'abandoned', 'scrapped',
    }
    text_lower = text.lower()
    kw_lower = keyword.lower()

    idx = text_lower.find(kw_lower)
    if idx < 0:
        return False

    # ±40 Zeichen Fenster um das Keyword
    start = max(0, idx - 40)
    end = min(len(text_lower), idx + len(kw_lower) + 40)
    window = text_lower[start:end]

    for neg in NEGATION_WORDS:
        if neg in window:
            return True
    return False


def _has_dual_source_confirmation(thesis_id: str, keyword: str, hours: int = 4) -> bool:
    """
    Prüft ob der Kill-Trigger von mindestens 2 verschiedenen Headlines bestätigt wird.
    Verhindert False Positives durch einzelne sensationalistische Artikel.

    Returns True wenn 2+ verschiedene Headlines matchen (= Kill-Trigger bestätigt).
    """
    try:
        conn = _get_db()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = conn.execute(
            """
            SELECT DISTINCT news_headline FROM thesis_checks
            WHERE thesis_id = ? AND kill_trigger_match = 1
              AND checked_at > ?
            ORDER BY checked_at DESC
            LIMIT 10
            """,
            (thesis_id, cutoff)
        ).fetchall()
        conn.close()

        unique_headlines = set()
        for row in rows:
            headline = (row[0] or '').strip()[:80]  # Normalisieren
            if headline:
                unique_headlines.add(headline)

        return len(unique_headlines) >= 2
    except Exception as e:
        print(f"[thesis_engine] _has_dual_source_confirmation Fehler: {e}")
        return True  # Bei Fehler konservativ = bestätigt


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
    """Sendet Discord-Alert via Dispatcher (Phase 22.4 Priority-Tiering).
    Thesis-Engine-Alerts:
      HIGH   — INVALIDATED (Thesis komplett tot, Positionen muessen raus)
      MEDIUM — DEGRADED (Warnung, keine neuen Entries erlaubt)
      LOW    — Updates ohne Action-Pflicht
    """
    try:
        import sys as _sys
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).parent.parent))
        from discord_dispatcher import send_alert as _dispatch, TIER_HIGH, TIER_MEDIUM, TIER_LOW
        m = message.upper()
        if 'INVALIDATED' in m or 'KILL' in m:
            tier = TIER_HIGH
        elif 'DEGRADED' in m:
            tier = TIER_MEDIUM
        else:
            tier = TIER_LOW
        # Thesis-ID als dedupe-key extrahieren (verhindert Spam bei Reruns)
        dk = None
        import re as _re
        mm = _re.search(r'(?:THESIS \w+:|thesis_id[=:])\s*([A-Z0-9_\-]+)', message)
        if mm:
            dk = f'thesis_{mm.group(1)}'
        return _dispatch(message, tier=tier, category='thesis', dedupe_key=dk)
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
            # ── Auto-Init: Baseline-Eintrag wenn noch keiner existiert ─
            existing = get_thesis_status(thesis_id)
            if not existing:
                set_thesis_status(thesis_id, 'ACTIVE', 'auto-initialized from strategies.json')
                results.setdefault('initialized', []).append(thesis_id)

            # ── Kill-Trigger prüfen ────────────────────────────────────
            triggered, match_text = check_thesis_kill_trigger(thesis_id, recent_news)
            if triggered:
                results['triggers_fired'].append({'thesis_id': thesis_id, 'match': match_text})
                # Zwei-Quellen-Bestätigung: Erst degradieren wenn 2+ Headlines matchen
                if _has_dual_source_confirmation(thesis_id, match_text, hours=4):
                    degrade_thesis(thesis_id, f"Kill-Trigger in News: '{match_text}' (2+ Quellen bestätigt)")
                    results['degraded'].append(thesis_id)
                else:
                    results.setdefault('pending_confirmation', []).append(
                        {'thesis_id': thesis_id, 'match': match_text}
                    )
                    print(f"[thesis_engine] {thesis_id}: Kill-Trigger '{match_text}' — warte auf 2. Quelle")

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


# ─── Strategies/DB Sync ─────────────────────────────────────────────────────

SYNC_LOG = WS / 'data' / 'sync_check.log'

def sync_strategies_and_db() -> dict:
    """
    Synchronisiert strategies.json (Datei) mit thesis_status (SQLite).
    Verhindert dass tote Thesen weiter gehandelt werden.

    Regeln:
      DB INVALIDATED + JSON active → JSON auf 'invalidated' setzen
      DB DEGRADED + JSON active → JSON auf 'degraded' setzen
      JSON invalidated + DB ACTIVE → DB auf INVALIDATED (manuelles Override)

    Returns: dict mit Anzahl Korrekturen
    """
    result = {'corrections': 0, 'details': [], 'errors': []}

    strategies = _load_strategies()
    if not strategies:
        result['errors'].append('strategies.json leer oder nicht lesbar')
        return result

    # Backup erstellen
    backup_path = STRATEGIES_JSON.with_suffix('.json.bak')
    try:
        backup_path.write_text(STRATEGIES_JSON.read_text(encoding='utf-8'), encoding='utf-8')
    except Exception as e:
        result['errors'].append(f'Backup fehlgeschlagen: {e}')

    modified = False

    try:
        conn = _get_db()
        db_rows = conn.execute("SELECT thesis_id, status FROM thesis_status").fetchall()
        conn.close()
        db_map = {row['thesis_id']: row['status'] for row in db_rows}
    except Exception as e:
        result['errors'].append(f'DB-Lese-Fehler: {e}')
        return result

    for sid, strategy in strategies.items():
        if not isinstance(strategy, dict):
            continue

        json_status = strategy.get('status', 'active').lower()
        db_status = db_map.get(sid, '')

        # DB INVALIDATED + JSON active → JSON korrigieren
        if db_status == 'INVALIDATED' and json_status == 'active':
            strategy['status'] = 'invalidated'
            strategy['_sync_note'] = f'Auto-sync: DB war INVALIDATED ({_now_iso()})'
            modified = True
            result['corrections'] += 1
            result['details'].append(f'{sid}: JSON active → invalidated (DB war INVALIDATED)')

        # DB DEGRADED + JSON active → JSON korrigieren
        elif db_status == 'DEGRADED' and json_status == 'active':
            strategy['status'] = 'degraded'
            strategy['_sync_note'] = f'Auto-sync: DB war DEGRADED ({_now_iso()})'
            modified = True
            result['corrections'] += 1
            result['details'].append(f'{sid}: JSON active → degraded (DB war DEGRADED)')

        # JSON invalidated + DB ACTIVE → DB korrigieren (manuelles Override)
        elif json_status in ('invalidated', 'blocked') and db_status == 'ACTIVE':
            set_thesis_status(sid, 'INVALIDATED', f'Sync: JSON war {json_status}')
            result['corrections'] += 1
            result['details'].append(f'{sid}: DB ACTIVE → INVALIDATED (JSON war {json_status})')

    # Atomic Write
    if modified:
        try:
            atomic_write_json(STRATEGIES_JSON, strategies)
        except Exception as e:
            result['errors'].append(f'JSON-Schreib-Fehler: {e}')

    # Sync-Log schreiben
    try:
        ts = datetime.now(_BERLIN).strftime('%Y-%m-%d %H:%M:%S')
        log_line = f'[{ts}] Sync: {result["corrections"]} Korrekturen'
        if result['details']:
            log_line += ' | ' + '; '.join(result['details'])
        log_line += '\n'
        with open(SYNC_LOG, 'a', encoding='utf-8') as f:
            f.write(log_line)
    except Exception:
        pass

    print(f"[thesis_engine] Sync: {result['corrections']} Korrekturen, {len(result['errors'])} Fehler")
    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────


# ─── News-Kill-Check ─────────────────────────────────────────────────────────

def check_news_kill(ticker: str) -> tuple[bool, str]:
    """
    Scannt News der letzten 3 Tage für den angegebenen Ticker auf Kill-Signale.

    Kill-Kategorien:
      1. Negative Earnings Surprise  — "misses", "verfehlt", "enttäuschend",
                                       "verlust warnung", "gewinnwarnung"
      2. Politisches Risiko          — "sanktionen", "sanctions", "verbot", "ban",
                                       "regulierung", "investigation", "sec charges"
      3. These-Invalidierung         — "deal geplatzt", "deal collapsed",
                                       "merger failed", "bankrupt", "insolvenz"
      4. Sektor-Kollaps              — "sektor kollaps", "industrie krise",
                                       "supply chain crisis"

    Returns:
        (True, reason_str)  wenn mindestens ein Kill-Signal gefunden
        (False, '')         sonst
    """
    KILL_PATTERNS: dict[str, list[str]] = {
        'earnings_miss': [
            'misses', 'miss estimates', 'misses estimates',
            'verfehlt', 'verfehlte', 'enttäuschend', 'enttäuschende',
            'verlust warnung', 'verlustwarnung', 'gewinnwarnung',
            'profit warning', 'earnings miss',
        ],
        'political_risk': [
            'sanktionen', 'sanktion', 'sanctions', 'sanction',
            'verbot', 'verbote', 'ban', 'banned',
            'regulierung', 'reguliert', 'regulation',
            'investigation', 'untersucht', 'ermittlung',
            'sec charges', 'sec klage', 'doj',
        ],
        'thesis_invalidation': [
            'deal geplatzt', 'deal gescheitert', 'deal collapsed', 'deal failed',
            'merger failed', 'merger collapsed', 'übernahme gescheitert',
            'bankrupt', 'bankruptcy', 'insolvenz', 'insolvent',
            'pleite', 'zahlungsunfähig',
        ],
        'sector_collapse': [
            'sektor kollaps', 'sector collapse',
            'industrie krise', 'industry crisis',
            'supply chain crisis', 'lieferkettenkrise',
        ],
    }

    ticker_upper = ticker.upper()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

    try:
        conn = _get_db()
        rows = conn.execute(
            """
            SELECT headline, source, published_at
            FROM   news_events
            WHERE  (ticker = ? OR ticker = ?)
              AND  published_at >= ?
            ORDER  BY published_at DESC
            LIMIT  100
            """,
            (ticker_upper, ticker_upper.lower(), cutoff),
        ).fetchall()
        conn.close()
    except Exception as exc:
        # DB fehlt oder Tabelle noch nicht vorhanden — kein Kill
        return (False, '')

    if not rows:
        return (False, '')

    for row in rows:
        headline = (row['headline'] or '').lower()
        source   = (row['source']   or '').lower()
        combined = headline + ' ' + source

        for category, keywords in KILL_PATTERNS.items():
            for kw in keywords:
                if kw in combined:
                    reason = (
                        f"Kill-Signal [{category}] für {ticker_upper}: "
                        f"'{kw}' in Headline '{row['headline']}' "
                        f"(Quelle: {row['source']}, {row['published_at']})"
                    )
                    return (True, reason)

    return (False, '')


def run_news_kill_check() -> list[dict]:
    """
    Prüft alle offenen Positionen gegen check_news_kill().

    - Liest offene Trades aus trading.db (status = 'OPEN')
    - Führt check_news_kill pro Ticker durch
    - Schreibt Kills in data/thesis_kill_signals.json (append-Semantik,
      d.h. bereits gespeicherte Kills werden nicht gelöscht)
    - Gibt Liste der gefundenen Kills zurück

    Schema eines Kill-Eintrags:
        {
            "ticker":      "NVDA",
            "trade_id":    42,
            "strategy_id": "PS17",
            "reason":      "Kill-Signal [political_risk] …",
            "detected_at": "2026-04-15T18:30:00+00:00"
        }
    """
    import json as _json

    # Offene Positionen lesen
    try:
        conn = _get_db()
        open_trades = conn.execute(
            """
            SELECT id, ticker, strategy_id
            FROM   trades
            WHERE  status = 'OPEN'
            """,
        ).fetchall()
        conn.close()
    except Exception as exc:
        return []

    kills_found: list[dict] = []

    for trade in open_trades:
        ticker      = (trade['ticker'] or '').upper()
        trade_id    = trade['id']
        strategy_id = trade['strategy_id'] or ''

        if not ticker:
            continue

        triggered, reason = check_news_kill(ticker)
        if triggered:
            kills_found.append({
                'ticker':      ticker,
                'trade_id':    trade_id,
                'strategy_id': strategy_id,
                'reason':      reason,
                'detected_at': datetime.now(timezone.utc).isoformat(),
            })

    # Ergebnisse in data/thesis_kill_signals.json persistieren
    kill_signals_path = DB.parent / 'thesis_kill_signals.json'
    try:
        if kill_signals_path.exists():
            existing = _json.loads(kill_signals_path.read_text(encoding='utf-8'))
            if not isinstance(existing, list):
                existing = []
        else:
            existing = []

        # Keine Duplikate: gleicher trade_id + gleiche Kategorie-Substring
        existing_keys = {
            (e.get('trade_id'), e.get('detected_at', '')[:10])
            for e in existing
        }
        for kill in kills_found:
            day_key = (kill['trade_id'], kill['detected_at'][:10])
            if day_key not in existing_keys:
                existing.append(kill)
                existing_keys.add(day_key)

        kill_signals_path.write_text(
            _json.dumps(existing, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
    except Exception:
        pass  # Persistierung nie crashen lassen

    return kills_found


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
            # Exit-Code != 0 damit Scheduler den Fehler erkennt (vorher: silent OK)
            _sys.exit(2)

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

    elif '--sync' in args:
        print("Starte Strategy/DB Sync...")
        res = sync_strategies_and_db()
        print(f"Korrekturen: {res['corrections']}")
        for d in res['details']:
            print(f"  {d}")
        if res['errors']:
            print(f"Fehler: {res['errors']}")

    else:
        print("Usage:")
        print("  python3.13 thesis_engine.py --active")
        print("  python3.13 thesis_engine.py --status S2")
        print("  python3.13 thesis_engine.py --monitor")
        print("  python3.13 thesis_engine.py --sync")
        print("  python3.13 thesis_engine.py --degrade PS17 'Grund'")
        print("  python3.13 thesis_engine.py --invalidate PS1 'Kill-Trigger: Iran Deal'")
