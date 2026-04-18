#!/usr/bin/env python3
"""
tmp_patch_discord_transcript.py
================================
Patch 1: Fügt Transkript-Erkennung in discord_chat.py ein und
         store_manual_transcript() an trader_intel.py an.

Ziel-Dateien auf dem Server:
  /opt/trademind/scripts/discord_chat.py
  /opt/trademind/scripts/core/trader_intel.py

Läuft lokal gegen die Worktree-Kopien, damit py_compile vor dem Deploy prüfen kann.
"""

import py_compile
import sys
from pathlib import Path

# ── Pfad-Setup ──────────────────────────────────────────────────────────────
# Lokal: Worktree; auf VPS: /opt/trademind
WS_LOCAL = Path(__file__).resolve().parent          # .claude/worktrees/trusting-shannon/
VPS_ROOT  = Path('/opt/trademind')

def _target(rel: str) -> Path:
    """Bevorzugt die lokale Worktree-Datei; fällt auf VPS zurück."""
    local = WS_LOCAL / rel
    if local.exists():
        return local
    vps = VPS_ROOT / rel
    if vps.exists():
        return vps
    raise FileNotFoundError(f"Weder {local} noch {vps} gefunden.")


# ── Teil 1: discord_chat.py — Transkript-Block einfügen ─────────────────────

DISCORD_REL = 'scripts/discord_chat.py'

# Exakter Such-Anker (aus dem Original)
ANCHOR = '''        # ── Phase 4: Thesis suggestion intake ────────────────────────────
        # If Victor writes "These:", "Thesis:", or "Strategie:" → parse as thesis
        is_thesis_suggestion = any(
            content_lower.startswith(kw) or f'\\n{kw}' in content_lower
            for kw in ('these:', 'thesis:', 'strategie:')
        )
        if is_thesis_suggestion:
            _handle_thesis_suggestion(content)'''

TRANSCRIPT_BLOCK = '''        # ── Transkript-Erkennung ──────────────────────────────────────────
        # Lange Nachrichten (>400 Zeichen) mit Trading-Keywords = YouTube/Video-Transkript
        # Werden automatisch in intelligence.db gespeichert und von Albert analysiert
        _transcript_keywords = ('kanal', 'willkommen', 'aktien', 'depot', 'chart',
                                 'einstieg', 'ausbruch', 'setups', 'tagelinie', 'stopp',
                                 'channel', 'watchlist', 'konsolidierung', 'ausbruch')
        _is_transcript = (
            len(content) > 400 and
            sum(1 for kw in _transcript_keywords if kw in content_lower) >= 3
        )
        if _is_transcript:
            try:
                import sys as _sys
                _core = str(WS / 'scripts' / 'core')
                if _core not in _sys.path:
                    _sys.path.insert(0, _core)
                from trader_intel import store_manual_transcript, extract_tickers, extract_setups, get_db as _get_intel_db
                tickers_found = extract_tickers(content)
                setups_found  = extract_setups(content, tickers_found)
                store_manual_transcript(
                    source='victor_discord',
                    text=content,
                    tickers=tickers_found,
                    setups=setups_found,
                )
                _ticker_list = ', '.join(tickers_found[:8]) if tickers_found else 'keine erkannt'
                _send_message(
                    f'📊 Transkript gespeichert. Erkannte Ticker: {_ticker_list}. '
                    f'{len(setups_found)} Setups extrahiert. Fließt in nächsten CEO-Kontext ein.',
                    CHANNEL_ID
                )
            except Exception as _te:
                pass  # Transkript-Speicherung nie crashen lassen

'''

def patch_discord_chat() -> None:
    target = _target(DISCORD_REL)
    original = target.read_text(encoding='utf-8')

    if 'Transkript-Erkennung' in original:
        print(f"[discord_chat.py] Transkript-Block bereits vorhanden — übersprungen.")
        return

    if ANCHOR not in original:
        raise ValueError(
            "[discord_chat.py] FEHLER: Anker-Block nicht gefunden. "
            "Hat sich die Datei geändert? Bitte Anker prüfen."
        )

    patched = original.replace(ANCHOR, TRANSCRIPT_BLOCK + ANCHOR)
    target.write_text(patched, encoding='utf-8')
    print(f"[discord_chat.py] Transkript-Block eingefügt.")

    # Syntaxprüfung
    try:
        py_compile.compile(str(target), doraise=True)
        print(f"[discord_chat.py] py_compile OK")
    except py_compile.PyCompileError as e:
        # Änderung rückgängig machen
        target.write_text(original, encoding='utf-8')
        raise RuntimeError(f"[discord_chat.py] Syntaxfehler — Patch zurückgerollt: {e}") from e


# ── Teil 2: trader_intel.py — store_manual_transcript anhängen ──────────────

TRADER_INTEL_REL = 'scripts/core/trader_intel.py'

STORE_MANUAL_TRANSCRIPT = '''

def get_db() -> 'sqlite3.Connection':
    """Öffentlicher Alias auf _get_conn() — für Import durch discord_chat."""
    return _get_conn()


def store_manual_transcript(source: str, text: str, tickers: list, setups: list, channel: str = 'manual') -> None:
    """Store a manually provided transcript (e.g. from Victor via Discord) in intelligence.db."""
    import json as _json
    from datetime import datetime as _dt
    db = _get_conn()
    db.execute(
        """INSERT OR IGNORE INTO trader_signals
           (source, video_id, fetched_at, channel, tickers_mentioned, setups, raw_text, summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            source,
            f"manual_{_dt.now().strftime('%Y%m%d_%H%M%S')}",
            _dt.now().isoformat(),
            channel,
            _json.dumps(tickers),
            _json.dumps(setups),
            text[:8000],
            f"Manuelles Transkript: {len(tickers)} Ticker, {len(setups)} Setups"
        )
    )
    db.commit()
    db.close()
'''

def patch_trader_intel() -> None:
    target = _target(TRADER_INTEL_REL)
    original = target.read_text(encoding='utf-8')

    if 'store_manual_transcript' in original:
        print(f"[trader_intel.py] store_manual_transcript bereits vorhanden — übersprungen.")
        return

    # Vor dem __main__-Block einfügen, damit die Funktion importierbar ist
    if 'if __name__ == "__main__":' in original:
        patched = original.replace(
            'if __name__ == "__main__":',
            STORE_MANUAL_TRANSCRIPT + '\n\nif __name__ == "__main__":'
        )
    else:
        # Kein __main__-Block: einfach anhängen
        patched = original + STORE_MANUAL_TRANSCRIPT

    target.write_text(patched, encoding='utf-8')
    print(f"[trader_intel.py] store_manual_transcript + get_db alias eingefügt.")

    try:
        py_compile.compile(str(target), doraise=True)
        print(f"[trader_intel.py] py_compile OK")
    except py_compile.PyCompileError as e:
        target.write_text(original, encoding='utf-8')
        raise RuntimeError(f"[trader_intel.py] Syntaxfehler — Patch zurückgerollt: {e}") from e


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    errors = []
    for fn in (patch_trader_intel, patch_discord_chat):
        try:
            fn()
        except Exception as exc:
            print(f"FEHLER: {exc}", file=sys.stderr)
            errors.append(exc)

    if errors:
        sys.exit(1)
    print("\nPatch 1 (Transkript-Erkennung) erfolgreich abgeschlossen.")
