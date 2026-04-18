#!/usr/bin/env python3
"""
tmp_patch_thesis_kill.py
========================
Patch 3: Fügt zwei neue Funktionen an scripts/core/thesis_engine.py an:

  check_news_kill(ticker)    — Scannt letzte 3 Tage News auf Kill-Signale
  run_news_kill_check()      — Prüft alle offenen Positionen; schreibt
                               data/thesis_kill_signals.json

Vorgehen:
  1. Datei lesen
  2. Prüfen ob Funktionen bereits vorhanden
  3. Vor dem if __name__ == '__main__': Block einfügen
  4. py_compile prüfen
"""

import py_compile
import sys
from pathlib import Path

# ── Pfad-Setup ──────────────────────────────────────────────────────────────
WS_LOCAL = Path(__file__).resolve().parent
VPS_ROOT  = Path('/opt/trademind')

def _target(rel: str) -> Path:
    local = WS_LOCAL / rel
    if local.exists():
        return local
    vps = VPS_ROOT / rel
    if vps.exists():
        return vps
    raise FileNotFoundError(f"Weder {local} noch {vps} gefunden.")


TARGET_REL = 'scripts/core/thesis_engine.py'

# ── Neue Funktionen ──────────────────────────────────────────────────────────
NEW_FUNCTIONS = '''

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

'''


def patch_thesis_engine() -> None:
    target = _target(TARGET_REL)
    original = target.read_text(encoding='utf-8')

    if 'check_news_kill' in original:
        print("[thesis_engine.py] check_news_kill bereits vorhanden — übersprungen.")
        return

    # Vor __main__-Block einfügen; sonst anhängen
    MAIN_MARKER = "\nif __name__ == '__main__':"
    ALT_MARKER  = '\nif __name__ == "__main__":'

    if MAIN_MARKER in original:
        patched = original.replace(MAIN_MARKER, NEW_FUNCTIONS + MAIN_MARKER, 1)
    elif ALT_MARKER in original:
        patched = original.replace(ALT_MARKER, NEW_FUNCTIONS + ALT_MARKER, 1)
    else:
        # Kein __main__: einfach anhängen
        patched = original + NEW_FUNCTIONS

    target.write_text(patched, encoding='utf-8')
    print("[thesis_engine.py] check_news_kill + run_news_kill_check eingefügt.")

    try:
        py_compile.compile(str(target), doraise=True)
        print("[thesis_engine.py] py_compile OK")
    except py_compile.PyCompileError as e:
        target.write_text(original, encoding='utf-8')
        raise RuntimeError(f"[thesis_engine.py] Syntaxfehler — Patch zurückgerollt: {e}") from e


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    try:
        patch_thesis_engine()
        print("\nPatch 3 (News Kill-Check) erfolgreich abgeschlossen.")
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        sys.exit(1)
