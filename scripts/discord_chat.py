#!/usr/bin/env python3
"""
discord_chat.py — Albert, AI-CEO von TradeMind, als Discord-Chatbot.
Pollt den Discord-DM-Kanal alle 30 Sekunden auf neue Nachrichten von Victor,
baut einen vollständigen Kontext aus allen Datenquellen auf und antwortet
via Claude API mit Alberts Persona.

Läuft als Hintergrund-Thread im scheduler_daemon.
"""

import json
import os
import sqlite3
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Pfade ─────────────────────────────────────────────────────────────────────

_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(os.getenv('TRADEMIND_HOME', _default_ws))
if not WS.exists():
    WS = Path(__file__).resolve().parent.parent

DATA = WS / 'data'
MEMORY = WS / 'memory'
SCRIPTS = WS / 'scripts'

OPENCLAW_CFG = Path('/data/.openclaw/openclaw.json')
STATE_FILE = DATA / 'discord_last_message.json'
CHAT_LOG = DATA / 'discord_chat_log.jsonl'  # Persistentes Chat-Log für Claude Code

# Discord-Konstanten
CHANNEL_ID    = '1492225799062032484'   # Victors DM-Kanal für Albert-Chat
VICTOR_USER_ID = '452053147620343808'   # Victor — nur seine Nachrichten verarbeiten
DISCORD_API    = 'https://discord.com/api/v10'

# Claude-Modell
CLAUDE_MODEL = 'claude-opus-4-5'


# ── Token & Hilfsfunktionen ───────────────────────────────────────────────────

def _get_bot_token() -> str:
    """Liest Bot-Token aus OpenClaw-Config, ENV oder lokaler .env."""
    # 1. Server-Pfad
    if OPENCLAW_CFG.exists():
        cfg = json.loads(OPENCLAW_CFG.read_text(encoding="utf-8"))
        return cfg['channels']['discord']['token']
    # 2. Environment Variable
    token = os.environ.get('DISCORD_BOT_TOKEN', '')
    if token:
        return token
    # 3. Lokale deploy/.env
    _env = WS / 'deploy' / '.env'
    if _env.exists():
        for line in _env.read_text(encoding="utf-8").splitlines():
            if line.startswith('DISCORD_BOT_TOKEN=') and len(line) > 19:
                return line.split('=', 1)[1].strip()
    raise FileNotFoundError('Discord Bot Token nicht gefunden')


def _discord_request(method: str, endpoint: str, payload: dict | None = None) -> dict | None:
    """Macht einen Discord-API-Request. Gibt geparste JSON-Antwort oder None zurück."""
    try:
        token = _get_bot_token()
        url = f'{DISCORD_API}{endpoint}'
        data = json.dumps(payload).encode() if payload else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                'Authorization': f'Bot {token}',
                'Content-Type': 'application/json',
                'User-Agent': 'TradeMind-Albert/1.0',
            },
            method=method,
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        print(f'[Albert] Discord HTTP-Fehler {e.code}: {e.reason}', flush=True)
        return None
    except Exception as e:
        print(f'[Albert] Discord Request Fehler: {e}', flush=True)
        return None


def _send_typing(channel_id: str = CHANNEL_ID) -> None:
    """Sendet Typing-Indikator (Albert "schreibt...")."""
    try:
        _discord_request('POST', f'/channels/{channel_id}/typing')
    except Exception:
        pass


def _send_message(content: str, channel_id: str = CHANNEL_ID) -> bool:
    """Sendet eine Nachricht in den Discord-Kanal."""
    try:
        result = _discord_request(
            'POST',
            f'/channels/{channel_id}/messages',
            {'content': content[:2000]},
        )
        return result is not None
    except Exception as e:
        print(f'[Albert] Sende-Fehler: {e}', flush=True)
        return False


def _fetch_messages(channel_id: str = CHANNEL_ID, after: str | None = None, limit: int = 10) -> list[dict]:
    """Ruft neue Nachrichten aus dem Kanal ab (neueste zuerst im API-Response)."""
    try:
        endpoint = f'/channels/{channel_id}/messages?limit={limit}'
        if after:
            endpoint += f'&after={after}'
        result = _discord_request('GET', endpoint)
        if isinstance(result, list):
            return result
        return []
    except Exception as e:
        print(f'[Albert] Fetch-Fehler: {e}', flush=True)
        return []


# ── State Tracking ────────────────────────────────────────────────────────────

def _load_state() -> dict:
    """Lädt den zuletzt verarbeiteten Message-ID State."""
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {'last_message_id': None}


def _save_state(state: dict) -> None:
    """Speichert den State."""
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        print(f'[Albert] State-Speicherfehler: {e}', flush=True)


# ── Kontext-Aufbau ────────────────────────────────────────────────────────────

def load_context() -> str:
    """
    Lädt alle verfügbaren Datenquellen und formatiert sie als String
    für Alberts System-Prompt.
    """
    parts: list[str] = []
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    parts.append(f'=== AKTUELLER KONTEXT (Stand: {now_str}) ===\n')

    # 1. Markt-Regime (current_regime.json ODER market-regime.json)
    try:
        regime_file = DATA / 'current_regime.json'
        if not regime_file.exists():
            regime_file = DATA / 'market-regime.json'
        if regime_file.exists():
            regime = json.loads(regime_file.read_text(encoding='utf-8'))
            parts.append('--- MARKT-REGIME ---')
            parts.append(json.dumps(regime, indent=2, ensure_ascii=False))
        else:
            parts.append('--- MARKT-REGIME ---\nKeine Regime-Daten verfügbar.')
    except Exception as e:
        parts.append(f'--- MARKT-REGIME ---\nKeine Regime-Daten verfügbar ({e})')

    # 2. CEO-Direktive
    try:
        directive_file = DATA / 'ceo_directive.json'
        if directive_file.exists():
            directive = json.loads(directive_file.read_text(encoding="utf-8"))
            parts.append('\n--- CEO DIREKTIVE / MODUS ---')
            parts.append(json.dumps(directive, indent=2, ensure_ascii=False))
        else:
            parts.append('\n--- CEO DIREKTIVE / MODUS ---\n[Datei nicht gefunden]')
    except Exception as e:
        parts.append(f'\n--- CEO DIREKTIVE / MODUS ---\n[Ladefehler: {e}]')

    # 3. Offene Positionen aus DB
    try:
        db_file = DATA / 'trading.db'
        if db_file.exists():
            conn = sqlite3.connect(str(db_file))
            conn.row_factory = sqlite3.Row
            try:
                # Offene Positionen
                cursor = conn.execute(
                    '''SELECT ticker, entry_price, stop_price, target_price,
                              conviction, pnl_pct, strategy,
                              entry_date, shares, status
                       FROM paper_portfolio
                       WHERE status = 'OPEN'
                       ORDER BY entry_date DESC'''
                )
                rows = cursor.fetchall()
                parts.append('\n--- OFFENE POSITIONEN (paper_portfolio) ---')
                if rows:
                    for row in rows:
                        d = dict(row)
                        pnl = d.get('pnl_pct', 0) or 0
                        pnl_str = f'+{pnl:.1f}%' if pnl >= 0 else f'{pnl:.1f}%'
                        parts.append(
                            f"  {d.get('ticker','?'):10s} | Entry: {d.get('entry_price','?')} "
                            f"| Stop: {d.get('stop_price','?')} | Target: {d.get('target_price','?')} "
                            f"| Conviction: {d.get('conviction','?')} | PnL: {pnl_str} "
                            f"| Strategie: {d.get('strategy','?')} | Einstieg: {d.get('entry_date','?')}"
                        )
                else:
                    parts.append('  Keine offenen Positionen.')

                # Fund-Status
                fund_rows = conn.execute('SELECT key, value FROM paper_fund').fetchall()
                if fund_rows:
                    parts.append('\n--- PAPER FUND ---')
                    for row in fund_rows:
                        parts.append(f"  {row['key']}: {row['value']}")
            except sqlite3.OperationalError as e:
                parts.append(f'  [DB-Fehler: {e}]')
            finally:
                conn.close()
        else:
            parts.append('\n--- OFFENE POSITIONEN ---\n[DB nicht gefunden]')
    except Exception as e:
        parts.append(f'\n--- OFFENE POSITIONEN ---\n[Fehler: {e}]')

    # 4. Performance-Statistiken
    try:
        accuracy_file = MEMORY / 'albert-accuracy.md'
        if accuracy_file.exists():
            content = accuracy_file.read_text(encoding='utf-8')
            # Auf max. 1500 Zeichen begrenzen um Token zu sparen
            if len(content) > 1500:
                content = content[:1500] + '\n...[gekürzt]'
            parts.append('\n--- PERFORMANCE / GENAUIGKEIT ---')
            parts.append(content)
        else:
            parts.append('\n--- PERFORMANCE / GENAUIGKEIT ---\n[Datei nicht gefunden]')
    except Exception as e:
        parts.append(f'\n--- PERFORMANCE / GENAUIGKEIT ---\n[Fehler: {e}]')

    # 5. System-Snapshot
    try:
        snapshot_file = MEMORY / 'state-snapshot.md'
        if snapshot_file.exists():
            content = snapshot_file.read_text(encoding='utf-8')
            if len(content) > 1500:
                content = content[:1500] + '\n...[gekürzt]'
            parts.append('\n--- SYSTEM-SNAPSHOT ---')
            parts.append(content)
        else:
            parts.append('\n--- SYSTEM-SNAPSHOT ---\n[Datei nicht gefunden]')
    except Exception as e:
        parts.append(f'\n--- SYSTEM-SNAPSHOT ---\n[Fehler: {e}]')

    # 6. Aktive Strategien (nur Name + Beschreibung)
    try:
        strategies_file = DATA / 'strategies.json'
        if strategies_file.exists():
            strategies = json.loads(strategies_file.read_text(encoding="utf-8"))
            parts.append('\n--- AKTIVE STRATEGIEN ---')
            # Nur Name und Beschreibung extrahieren — nicht die gesamten Daten
            if isinstance(strategies, list):
                for s in strategies:
                    name = s.get('name') or s.get('id') or '?'
                    desc = s.get('description') or s.get('desc') or ''
                    active = s.get('active', True)
                    status = 'aktiv' if active else 'inaktiv'
                    parts.append(f'  [{status}] {name}: {desc}')
            elif isinstance(strategies, dict):
                for key, val in strategies.items():
                    if isinstance(val, dict):
                        name = val.get('name') or key
                        desc = val.get('description') or val.get('desc') or ''
                        active = val.get('active', True)
                        status = 'aktiv' if active else 'inaktiv'
                        parts.append(f'  [{status}] {name}: {desc}')
                    else:
                        parts.append(f'  {key}: {val}')
        else:
            parts.append('\n--- AKTIVE STRATEGIEN ---\n[Datei nicht gefunden]')
    except Exception as e:
        parts.append(f'\n--- AKTIVE STRATEGIEN ---\n[Fehler: {e}]')

    # 7. Letzte Nachrichten aus news_events (mit Quelle + Datum)
    try:
        db_file = DATA / 'trading.db'
        if db_file.exists():
            conn = sqlite3.connect(str(db_file))
            conn.row_factory = sqlite3.Row
            try:
                news_rows = conn.execute(
                    '''SELECT headline, source, published_at, sentiment_label, sector
                       FROM news_events
                       ORDER BY published_at DESC
                       LIMIT 15'''
                ).fetchall()
                if news_rows:
                    parts.append('\n--- AKTUELLE NACHRICHTEN (letzte 15) ---')
                    for nr in news_rows:
                        d = dict(nr)
                        src = (d.get('source') or 'unbekannt').replace('_', ' ').title()
                        pub = (d.get('published_at') or '?')[:16]
                        sent = d.get('sentiment_label') or ''
                        sector = d.get('sector') or ''
                        headline = d.get('headline') or '?'
                        parts.append(f"  • {headline}")
                        parts.append(f"    [{src}, {pub}] {sent} {sector}")
            except Exception:
                pass
            finally:
                conn.close()
    except Exception:
        pass

    return '\n'.join(parts)


# ── Albert-Persona & Claude-API ───────────────────────────────────────────────

ALBERT_PERSONA = """Du bist Albert, CEO & Head of Research bei TradeMind — einem algorithmischen Handelsunternehmen.

PERSÖNLICHKEIT:
- Präzise, direkt, datengetrieben. Kein Bullshit.
- Sprichst wie ein erfahrener Hedgefonds-Manager mit 20+ Jahren Erfahrung.
- Du analysierst kühl, aber mit klarem Urteil.
- Antwortest IMMER auf Deutsch, egal in welcher Sprache die Frage gestellt wird.

DEINE FÄHIGKEITEN:
- Analyse offener Positionen (PnL, Stop, Target, Conviction)
- Marktregime-Einschätzung und deren Implikationen
- Geopolitische Einflüsse auf Sektoren und Strategien
- Risikomanagement-Empfehlungen
- Strategiebegründungen und Backtesting-Insights
- Performance-Analyse und Lernzyklen

KRITISCHE REGELN — LIES DAS SORGFÄLTIG:
1. Du arbeitest NUR mit den Daten, die dir im Kontext mitgegeben werden. ERFINDE NIEMALS Dateinamen, Verzeichnisse oder Code-Strukturen.
2. Wenn Daten fehlen oder eine Datei nicht gefunden wurde, sage klar: "Diese Daten liegen mir nicht vor." HALLUZINIERE NICHT.
3. Du kannst KEINE Dateien lesen, keinen Code ändern, keine Shell-Befehle ausführen. Du bist ein Chat-Interface, kein Code-Editor.
4. Bei Nachrichten: Nenne IMMER die Quelle und das Veröffentlichungsdatum aus dem Kontext. Ohne Quelle → nicht referenzieren.
5. Du kannst KEINE Trades direkt ausführen — du gibst Empfehlungen.
6. Wenn Victor nach Code-Änderungen, Bug-Fixes, Script-Anpassungen oder System-Problemen fragt:
   → Sage: "Das muss in Claude Code gemacht werden. Ich leite die Anfrage weiter."
   → Schreibe NICHT eigenen Code oder Pseudo-Lösungen.

KOMMUNIKATIONSSTIL:
- Kurze, präzise Sätze. Keine Füllwörter.
- Zahlen immer mit 2 Dezimalstellen für Preise, 1 für Prozent.
- Bei Positionen: Ticker, aktueller Status, Risiko in einem Satz.
- Bei Marktanalyse: Regime → These → Konsequenz.
- Bei Nachrichten: Immer mit [Quelle, Datum] angeben.
- Emojis nur sparsam, wenn sie Signal-Wert haben (z.B. 🔴 für kritisches Risiko).
"""


def ask_albert(message: str) -> str:
    """
    Ruft Claude API mit Alberts Persona + aktuellem Kontext auf.
    Gibt Alberts Antwort zurück (oder Fallback-Nachricht).
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    # Fallback: aus deploy/.env laden
    if not api_key:
        _env = WS / 'deploy' / '.env'
        if _env.exists():
            for _line in _env.read_text(encoding="utf-8").splitlines():
                if _line.startswith('ANTHROPIC_API_KEY=') and len(_line) > 19:
                    api_key = _line.split('=', 1)[1].strip()
                    break
    if not api_key:
        return (
            '⚠️ **Albert offline** — ANTHROPIC_API_KEY nicht gesetzt. '
            'Bitte in deploy/.env oder als Umgebungsvariable konfigurieren.'
        )

    try:
        import anthropic

        context = load_context()
        system_prompt = f'{ALBERT_PERSONA}\n\n{context}'

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            system=system_prompt,
            messages=[
                {'role': 'user', 'content': message}
            ],
        )
        return response.content[0].text.strip()

    except ImportError:
        return (
            '⚠️ **Albert offline** — `anthropic` Package nicht installiert. '
            'Bitte `pip install anthropic` ausführen.'
        )
    except Exception as e:
        error_str = str(e)[:200]
        print(f'[Albert] Claude API Fehler: {error_str}', flush=True)
        return (
            f'⚠️ **Albert temporär nicht verfügbar** — API-Fehler: {error_str}\n'
            f'Bitte in wenigen Minuten erneut versuchen.'
        )


# ── Phase 6: Thesis Stop (manual override) ───────────────────────────────────
# Note: _confirm_thesis and _reject_thesis removed — Albert now auto-activates.
# Victor's only remaining override is "Stopp: PSxx" to stop an active thesis.

def _stop_thesis(thesis_id: str) -> None:
    """
    Stops an active thesis immediately on Victor's request.
    Marks it INVALIDATED in DB and removes it from strategies.json active entries.
    """
    thesis_id = thesis_id.strip().upper()
    print(f'[Albert] Stopping thesis on Victor request: {thesis_id}', flush=True)

    # Update DB status via thesis_engine
    try:
        import sys as _sys
        _sys.path.insert(0, str(SCRIPTS))
        from core.thesis_engine import invalidate_thesis
        invalidate_thesis(thesis_id, 'Von Victor gestoppt')
    except Exception as e:
        print(f'[Albert] invalidate_thesis error: {e}', flush=True)

    # Mark as inactive in strategies.json if present
    strategies_file = DATA / 'strategies.json'
    try:
        if strategies_file.exists():
            strategies = json.loads(strategies_file.read_text(encoding='utf-8'))
            if isinstance(strategies, dict) and thesis_id in strategies:
                strategies[thesis_id]['status'] = 'inactive'
                strategies_file.write_text(
                    json.dumps(strategies, indent=2, ensure_ascii=False),
                    encoding='utf-8',
                )
                print(f'[Albert] {thesis_id} set inactive in strategies.json', flush=True)
    except Exception as e:
        print(f'[Albert] strategies.json update error: {e}', flush=True)

    # Send confirmation to Discord
    _send_message(
        f'🛑 **These {thesis_id} gestoppt.** Von Victor manuell deaktiviert.',
        CHANNEL_ID,
    )


def _extract_thesis_id(content: str, prefix: str) -> str:
    """Extract thesis ID from a command like 'Bestätigen: PS21' or 'Bestätigen PS21'."""
    # Remove the prefix (case-insensitive)
    remainder = content[len(prefix):].strip()
    # Optionally strip leading colon/space
    remainder = remainder.lstrip(':').strip()
    # Take first word-token (the ID)
    parts = remainder.split()
    return parts[0] if parts else ''


# ── Phase 4: Thesis Suggestion Intake ────────────────────────────────────────

def _handle_thesis_suggestion(content: str) -> None:
    """
    Parses a thesis suggestion from Victor and stores it in ceo_directive.json.
    Triggered when message starts with 'These:', 'Thesis:', or 'Strategie:'.

    The actual evaluation is done by Albert (ask_albert) in the normal flow.
    This function persists the raw suggestion for review.
    """
    import json as _json
    from datetime import datetime as _dt

    directive_path = DATA / 'ceo_directive.json'
    try:
        directive = _json.loads(directive_path.read_text(encoding="utf-8")) if directive_path.exists() else {}
    except Exception:
        directive = {}

    suggestions = directive.get('thesis_suggestions', [])
    suggestions.append({
        'raw_text': content,
        'received_at': _dt.now().isoformat(),
        'status': 'PENDING_EVALUATION',
        'evaluated_by': 'Albert',
    })
    directive['thesis_suggestions'] = suggestions[-20:]  # keep last 20

    try:
        directive_path.write_text(_json.dumps(directive, indent=2, ensure_ascii=False))
        print(f'[Albert] Thesis suggestion stored: {content[:80]}', flush=True)
    except Exception as e:
        print(f'[Albert] Failed to store thesis suggestion: {e}', flush=True)


# ── Chat-Log (persistent für Claude Code) ────────────────────────────────────

def _log_chat(role: str, content: str, ts: str | None = None) -> None:
    """Schreibt eine Nachricht ins persistente Chat-Log (JSONL).
    Damit kann Claude Code die Discord-Konversation nachlesen."""
    import json as _j
    entry = {
        'ts': ts or datetime.now().isoformat(),
        'role': role,   # 'victor' oder 'albert'
        'content': content,
    }
    try:
        with open(CHAT_LOG, 'a', encoding='utf-8') as f:
            f.write(_j.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass


# ── Polling-Logik ─────────────────────────────────────────────────────────────

def poll_once() -> None:
    """
    Prüft einmal auf neue Nachrichten und antwortet falls nötig.
    Wird alle 30 Sekunden von run_forever() aufgerufen.
    """
    state = _load_state()
    last_id = state.get('last_message_id')

    # Neue Nachrichten abrufen
    messages = _fetch_messages(CHANNEL_ID, after=last_id, limit=10)
    if not messages:
        return

    # Discord gibt Nachrichten in umgekehrter Reihenfolge zurück (neueste zuerst)
    # Wir sortieren aufsteigend (älteste zuerst) um chronologisch zu verarbeiten
    messages_sorted = sorted(messages, key=lambda m: int(m.get('id', '0')))

    # Höchste ID merken (auch wenn wir nicht antworten)
    highest_id = messages_sorted[-1].get('id') if messages_sorted else last_id

    for msg in messages_sorted:
        msg_id   = msg.get('id', '')
        author   = msg.get('author', {})
        user_id  = author.get('id', '')
        bot_flag = author.get('bot', False)
        content  = msg.get('content', '').strip()

        # Nur Victors Nachrichten verarbeiten (nicht Bot-Nachrichten)
        if bot_flag or user_id != VICTOR_USER_ID:
            continue

        # Leere Nachrichten ignorieren
        if not content:
            continue

        print(f'[Albert] Neue Nachricht von Victor: {content[:80]}', flush=True)
        _log_chat('victor', content, ts=msg.get('timestamp', ''))

        # ── Phase 6: Thesis stop (manual override) ────────────────────────
        # Victor can stop an active thesis: "Stopp: PS21" or "Stopp PS21"
        content_stripped = content.strip()
        content_lower = content_stripped.lower()

        stop_prefixes = ('stopp:', 'stopp ', 'stop:', 'stop ')

        matched_stop = next(
            (p for p in stop_prefixes if content_lower.startswith(p)), None
        )

        if matched_stop:
            thesis_id = _extract_thesis_id(content_stripped, content_stripped[:len(matched_stop)])
            if thesis_id:
                _stop_thesis(thesis_id)
                # Update state and continue (no Albert LLM call needed)
                state['last_message_id'] = highest_id
                state['last_poll'] = datetime.now().isoformat()
                _save_state(state)
                continue

        # ── Phase 4: Thesis suggestion intake ────────────────────────────
        # If Victor writes "These:", "Thesis:", or "Strategie:" → parse as thesis
        is_thesis_suggestion = any(
            content_lower.startswith(kw) or f'\n{kw}' in content_lower
            for kw in ('these:', 'thesis:', 'strategie:')
        )
        if is_thesis_suggestion:
            _handle_thesis_suggestion(content)

        # ── Eskalation an Claude Code bei System/Code-Anfragen ────────
        _code_keywords = ('fix', 'code', 'script', 'bug', 'fehler im system',
                          'anpassen', 'ändern', 'änder', 'umbauen', 'cron',
                          'pfad', 'path', 'deploy', 'scheduler', 'updaten')
        is_code_request = any(kw in content_lower for kw in _code_keywords)
        if is_code_request:
            try:
                _req_file = DATA / 'claude_code_requests.jsonl'
                _req = json.dumps({
                    'ts': datetime.now().isoformat(),
                    'from': 'victor_via_discord',
                    'message': content,
                    'status': 'pending',
                }, ensure_ascii=False)
                with open(_req_file, 'a', encoding='utf-8') as _f:
                    _f.write(_req + '\n')
            except Exception:
                pass

        # Typing-Indikator senden
        _send_typing(CHANNEL_ID)

        # Antwort von Albert holen
        response = ask_albert(content)

        # Antwort loggen
        _log_chat('albert', response)

        # Antwort senden (bei langen Antworten in Chunks aufteilen)
        if len(response) <= 2000:
            _send_message(response, CHANNEL_ID)
        else:
            # In 1900-Zeichen-Chunks aufteilen (Puffer für Markdown-Breaks)
            chunk_size = 1900
            for i in range(0, len(response), chunk_size):
                chunk = response[i:i + chunk_size]
                _send_message(chunk, CHANNEL_ID)
                time.sleep(0.5)  # Kurz warten um Rate-Limit zu vermeiden

    # State mit höchster gesehener ID aktualisieren
    if highest_id and highest_id != last_id:
        state['last_message_id'] = highest_id
        state['last_poll'] = datetime.now().isoformat()
        _save_state(state)


def run_forever() -> None:
    """
    Haupt-Loop: ruft poll_once() alle 30 Sekunden auf.
    Fehler werden geloggt, aber der Loop läuft weiter.
    Wird als Daemon-Thread vom scheduler_daemon gestartet.
    """
    print('[Albert] Discord-Chat-Polling gestartet (alle 30s)', flush=True)

    # Kurze Verzögerung beim Start damit der Daemon vollständig initialisiert ist
    time.sleep(5)

    while True:
        try:
            poll_once()
        except Exception as e:
            print(f'[Albert] poll_once Fehler: {e}', flush=True)

        time.sleep(30)


# ── CLI-Test ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        # Test: Kontext laden und ausgeben
        print('=== Kontext-Test ===')
        ctx = load_context()
        print(ctx[:3000])
        print('\n=== Claude-Test ===')
        antwort = ask_albert('Wie ist der aktuelle Status des Portfolios?')
        print(antwort)
    elif len(sys.argv) > 1 and sys.argv[1] == '--poll':
        # Einmalig pollen
        poll_once()
    else:
        # Dauerhaft laufen
        run_forever()
