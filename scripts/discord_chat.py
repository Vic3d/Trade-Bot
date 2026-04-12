#!/usr/bin/env python3.13
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

WS = Path('/data/.openclaw/workspace')
if not WS.exists():
    WS = Path(__file__).resolve().parent.parent

DATA = WS / 'data'
MEMORY = WS / 'memory'
SCRIPTS = WS / 'scripts'

OPENCLAW_CFG = Path('/data/.openclaw/openclaw.json')
STATE_FILE = DATA / 'discord_last_message.json'

# Discord-Konstanten
CHANNEL_ID    = '1492225799062032484'   # Victors DM-Kanal für Albert-Chat
VICTOR_USER_ID = '452053147620343808'   # Victor — nur seine Nachrichten verarbeiten
DISCORD_API    = 'https://discord.com/api/v10'

# Claude-Modell
CLAUDE_MODEL = 'claude-opus-4-5'


# ── Token & Hilfsfunktionen ───────────────────────────────────────────────────

def _get_bot_token() -> str:
    """Liest Bot-Token aus OpenClaw-Config."""
    cfg = json.loads(OPENCLAW_CFG.read_text())
    return cfg['channels']['discord']['token']


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
            return json.loads(STATE_FILE.read_text())
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
    Lädt alle verfügbaren Datenquellen für Alberts System-Prompt.
    Enthält: Regime, Direktive, Positionen, Performance, News (12h),
             Thesen-Status, Alpha Decay, Strategies.
    """
    parts: list[str] = []
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    parts.append(f'=== ALBERT KONTEXT (Stand: {now_str}) ===\n')

    db_file = DATA / 'trading.db'

    # 1. MARKT-REGIME + CEO-DIREKTIVE
    try:
        regime_file = DATA / 'market-regime.json'
        if regime_file.exists():
            regime = json.loads(regime_file.read_text())
            vix = regime.get('vix', '?')
            reg = regime.get('current_regime', regime.get('regime', '?'))
            parts.append(f'--- MARKT ---\nRegime: {reg} | VIX: {vix}')
    except Exception:
        parts.append('--- MARKT ---\n[nicht verfügbar]')

    try:
        directive_file = DATA / 'ceo_directive.json'
        if directive_file.exists():
            d = json.loads(directive_file.read_text())
            bias  = d.get('market_bias', d.get('mode', 'NEUTRAL'))
            focus = d.get('focus_sector', '')
            wlim  = d.get('weekly_trade_limit', 3)
            parts.append(f'Bias: {bias} | Fokus: {focus or "alle"} | Max {wlim} Trades/Woche')
            if d.get('updated_by') == 'albert_discord':
                parts.append('⚠️ Victor-Anweisung aktiv')
    except Exception:
        pass

    # 2. PORTFOLIO (Cash + offene Positionen + letzte Trades)
    try:
        if db_file.exists():
            conn = sqlite3.connect(str(db_file))
            conn.row_factory = sqlite3.Row

            cash_row = conn.execute(
                "SELECT value FROM paper_fund WHERE key='current_cash' OR key='cash' LIMIT 1"
            ).fetchone()
            cash = float(cash_row[0]) if cash_row else 0.0

            positions = conn.execute("""
                SELECT ticker, strategy, entry_price, stop_price, target_price,
                       shares, entry_date, conviction
                FROM paper_portfolio WHERE status='OPEN'
                ORDER BY entry_date DESC
            """).fetchall()

            closed = conn.execute("""
                SELECT ticker, strategy, pnl_eur, pnl_pct,
                       COALESCE(exit_date, entry_date) as exit_date
                FROM paper_portfolio
                WHERE status IN ('WIN','LOSS','CLOSED')
                ORDER BY COALESCE(exit_date, entry_date) DESC LIMIT 8
            """).fetchall()

            conn.close()

            parts.append(f'\n--- PORTFOLIO ---')
            parts.append(f'Cash: {cash:,.0f}€ | Offene Positionen: {len(positions)}')

            if positions:
                for p in positions:
                    risk = (p['entry_price'] or 0) - (p['stop_price'] or 0)
                    crv  = ((p['target_price'] or 0) - (p['entry_price'] or 0)) / risk if risk > 0 else 0
                    pnl  = p['pnl_eur'] or 0
                    parts.append(
                        f"  {p['ticker']:8s} | {p['strategy']:10s} | "
                        f"Entry {p['entry_price']:.2f}€ → Ziel {p['target_price']:.2f}€ "
                        f"(Stop {p['stop_price']:.2f}€, CRV {crv:.1f}) | "
                        f"PnL {pnl:+.0f}€ | seit {str(p['entry_date'])[:10]}"
                    )
            else:
                parts.append('  Keine offenen Positionen')

            if closed:
                wins  = sum(1 for t in closed if (t['pnl_eur'] or 0) > 0)
                total_pnl = sum(t['pnl_eur'] or 0 for t in closed)
                parts.append(f'\nLetzte {len(closed)} Trades: {wins}W/{len(closed)-wins}L | P&L {total_pnl:+.0f}€')
                for t in closed[:5]:
                    icon = '✅' if (t['pnl_eur'] or 0) > 0 else '❌'
                    parts.append(
                        f"  {icon} {t['ticker']} ({t['strategy']}) "
                        f"{t['pnl_eur']:+.0f}€ ({t['pnl_pct']:+.1f}%) | {str(t['exit_date'])[:10]}"
                    )
    except Exception as e:
        parts.append(f'\n--- PORTFOLIO ---\n[Fehler: {e}]')

    # 3. NACHRICHTEN (letzte 12h) — DAS IST DER KERN FÜR OVERNIGHT-FRAGEN
    try:
        if db_file.exists():
            conn = sqlite3.connect(str(db_file))
            conn.row_factory = sqlite3.Row
            news = conn.execute("""
                SELECT headline, impact_direction, strategies_affected,
                       created_at, actual_direction
                FROM overnight_events
                WHERE created_at >= datetime('now', '-12 hours')
                ORDER BY created_at DESC
                LIMIT 30
            """).fetchall()
            conn.close()

            parts.append(f'\n--- NACHRICHTEN (letzte 12h) ---')
            if news:
                # Nach Impact-Direction gruppieren
                bullish = [n for n in news if n['impact_direction'] and 'bullish' in n['impact_direction']]
                bearish = [n for n in news if n['impact_direction'] and 'bearish' in n['impact_direction']]
                neutral = [n for n in news if n not in bullish and n not in bearish]

                if bullish:
                    parts.append(f'🟢 BULLISH ({len(bullish)}):')
                    for n in bullish[:6]:
                        strats = n['strategies_affected'] or '[]'
                        parts.append(f"  [{n['impact_direction']}] {(n['headline'] or '')[:90]}")

                if bearish:
                    parts.append(f'🔴 BEARISH ({len(bearish)}):')
                    for n in bearish[:6]:
                        parts.append(f"  [{n['impact_direction']}] {(n['headline'] or '')[:90]}")

                if neutral:
                    parts.append(f'⚪ SONSTIGE ({len(neutral)}):')
                    for n in neutral[:4]:
                        parts.append(f"  {(n['headline'] or '')[:80]}")
            else:
                parts.append('  Keine neuen Ereignisse in den letzten 12h')
    except Exception as e:
        parts.append(f'\n--- NACHRICHTEN ---\n[Fehler: {e}]')

    # 4. THESEN-STATUS (aus DB + strategies.json)
    try:
        if db_file.exists():
            conn = sqlite3.connect(str(db_file))
            conn.row_factory = sqlite3.Row
            thesis_status = conn.execute("""
                SELECT thesis_id, status, health_score, last_checked
                FROM thesis_status
                ORDER BY last_checked DESC LIMIT 15
            """).fetchall()

            recent_checks = conn.execute("""
                SELECT thesis_id, news_headline, direction, kill_trigger_match, checked_at
                FROM thesis_checks
                WHERE checked_at >= datetime('now', '-24 hours')
                ORDER BY checked_at DESC LIMIT 10
            """).fetchall()
            conn.close()

            if thesis_status:
                parts.append('\n--- THESEN-STATUS ---')
                for t in thesis_status:
                    health = t['health_score'] or 100
                    icon   = '✅' if t['status'] == 'ACTIVE' else ('⚠️' if t['status'] == 'DEGRADED' else '🔴')
                    parts.append(f"  {icon} {t['thesis_id']:12s} | {t['status']:12s} | Health: {health}%")

            if recent_checks:
                parts.append('\nThesen-Checks (24h):')
                for c in recent_checks:
                    kill = ' ⚠️KILL-TRIGGER' if c['kill_trigger_match'] else ''
                    parts.append(
                        f"  {c['thesis_id']}: {c['direction'] or '?'}{kill} — "
                        f"{(c['news_headline'] or '')[:70]}"
                    )
    except Exception:
        pass

    # 5. ALPHA DECAY (Strategie-Trends)
    try:
        decay_file = DATA / 'alpha_decay.json'
        if decay_file.exists():
            decay = json.loads(decay_file.read_text())
            parts.append('\n--- STRATEGIE-TRENDS (Alpha Decay) ---')
            for sid, d in list(decay.items())[:10]:
                trend  = d.get('trend', '?')
                wr     = d.get('raw_win_rate', 0)
                n      = d.get('n_trades', 0)
                icon   = '📈' if trend == 'IMPROVING' else ('📉' if trend == 'DECAYING' else '➡️')
                parts.append(f'  {icon} {sid:12s} | WR {wr:.0%} | {n} Trades | {trend}')
    except Exception:
        pass

    # 6. AKTIVE STRATEGIEN (kompakt)
    try:
        strategies_file = DATA / 'strategies.json'
        if strategies_file.exists():
            strategies = json.loads(strategies_file.read_text(encoding='utf-8'))
            parts.append('\n--- AKTIVE STRATEGIEN ---')
            if isinstance(strategies, dict):
                for key, val in strategies.items():
                    if not isinstance(val, dict):
                        continue
                    status     = val.get('status', 'active')
                    conviction = val.get('conviction', '?')
                    name       = val.get('name', key)
                    if status in ('inactive', 'blocked'):
                        continue
                    icon = '⏸️' if status == 'paused' else '▶️'
                    parts.append(f'  {icon} {key:12s} | Conv {conviction} | {name[:40]}')
    except Exception as e:
        parts.append(f'\n--- STRATEGIEN ---\n[Fehler: {e}]')

    # 7. THESIS HUNTER FINDINGS (neueste KI-Analyse der Nachrichtenlage)
    try:
        hunter_file = DATA / 'thesis_hunter_summary.json'
        if hunter_file.exists():
            hunter = json.loads(hunter_file.read_text())
            findings = hunter.get('findings', [])
            updated  = hunter.get('updated_at', '')[:16]
            if findings:
                parts.append(f'\n--- THESIS NEWS HUNTER (Stand: {updated}) ---')
                for f in findings:
                    impact = f.get('impact', '')
                    icon   = {'STRENGTHENED': '🟢', 'WEAKENED': '🔴',
                              'KILL_TRIGGER_NEAR': '🚨'}.get(impact, '⚪')
                    new_flag = ' [NEU]' if f.get('new_info') else ''
                    parts.append(
                        f"  {icon} {f['thesis_id']:12s} | {impact}{new_flag}"
                    )
                    parts.append(f"     {f.get('key_finding','')[:110]}")
                    if f.get('priced_in'):
                        parts.append(f"     Eingepreist: {f['priced_in'][:90]}")
                    if f.get('action') and f['action'] != 'NONE':
                        parts.append(f"     ⚡ Action: {f['action']}")
    except Exception:
        pass

    # 8. PERFORMANCE-REPORT (kompakt)
    try:
        accuracy_file = MEMORY / 'albert-accuracy.md'
        if accuracy_file.exists():
            content = accuracy_file.read_text(encoding='utf-8')
            # Nur die ersten 800 Zeichen — Tabellen-Zusammenfassung
            parts.append('\n--- PERFORMANCE ---')
            parts.append(content[:800] + ('...' if len(content) > 800 else ''))
    except Exception:
        pass

    return '\n'.join(parts)


# ── Albert-Persona & Claude-API ───────────────────────────────────────────────

ALBERT_PERSONA = """Du bist Albert, autonomer CEO & Head of Research bei TradeMind.

PERSÖNLICHKEIT:
- Präzise, direkt, datengetrieben. Kein Bullshit.
- Sprichst wie ein erfahrener Hedgefonds-Manager mit 20+ Jahren Erfahrung.
- Du kennst alle offenen Positionen, das aktuelle Marktregime und die Performance-Daten.
- Du analysierst kühl, aber mit klarem Urteil.
- Antwortest IMMER auf Deutsch, egal in welcher Sprache die Frage gestellt wird.

DEINE FÄHIGKEITEN:
- Analyse offener Positionen (PnL, Stop, Target, Conviction)
- Marktregime-Einschätzung und deren Implikationen
- Geopolitische Einflüsse auf Sektoren und Strategien
- Risikomanagement und Exits
- Strategiebegründungen und Backtesting-Insights
- Performance-Analyse und Lernzyklen

KOMMUNIKATIONSSTIL:
- Kurze, präzise Sätze. Keine Füllwörter.
- Zahlen immer mit 2 Dezimalstellen für Preise, 1 für Prozent.
- Bei Positionen: Ticker, aktueller Status, Risiko in einem Satz.
- Bei Marktanalyse: Regime → These → Konsequenz.
- Emojis nur sparsam, wenn sie Signal-Wert haben (z.B. 🔴 für kritisches Risiko).

PERSISTENZ — WICHTIG:
Wenn Victor dir eine Anweisung gibt oder du eine Entscheidung triffst, die das System
dauerhaft ändern soll, hängst du am ENDE deiner Antwort unsichtbare SAVE-Marker an.
Diese werden automatisch verarbeitet und gespeichert — Victor sieht sie nicht.

SAVE-Marker Formate (NUR am Ende, eine pro Zeile):
[SAVE:bias:BULLISH]          → Markt-Bias setzen (BULLISH/NEUTRAL/BEARISH/HALT)
[SAVE:bias:DEFENSIVE]        → Defensiv-Modus (nur Thesis-Plays)
[SAVE:focus:OIL]             → Sektor-Fokus für nächste Trades
[SAVE:strategy_pause:PS1]    → Strategie pausieren
[SAVE:strategy_resume:PS1]   → Strategie wieder aktivieren
[SAVE:strategy_conviction:PS1:3]  → Conviction-Level setzen (1-5)
[SAVE:exit:TICKER]           → Position sofort schließen
[SAVE:weekly_limit:2]        → Max Trades pro Woche ändern
[SAVE:note:Freitext]         → Notiz ins Daily-Log

Beispiele wann du SAVE-Marker setzt:
- Victor: "Sei diese Woche konservativer" → [SAVE:bias:DEFENSIVE] + [SAVE:weekly_limit:2]
- Victor: "Fokus auf Rüstungsaktien" → [SAVE:focus:DEFENSE]
- Victor: "Pausiere PS3" → [SAVE:strategy_pause:PS3]
- Victor: "Exit OXY sofort" → [SAVE:exit:OXY]
- Victor: "Erhöhe Conviction für PS1" → [SAVE:strategy_conviction:PS1:4]

Setze SAVE-Marker NUR wenn Victor explizit eine Änderung will oder du eine klare
Entscheidung triffst. Bei reinen Fragen/Analysen keine Marker.
"""


def ask_albert(message: str) -> str:
    """
    Ruft Claude API mit Alberts Persona + aktuellem Kontext auf.
    Gibt Alberts Antwort zurück (oder Fallback-Nachricht).
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return (
            '⚠️ **Albert offline** — ANTHROPIC_API_KEY nicht gesetzt. '
            'Bitte Umgebungsvariable konfigurieren.'
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


# ── Persistenz: SAVE-Marker parsen & ausführen ───────────────────────────────

def _strip_save_markers(response: str) -> str:
    """Entfernt [SAVE:...] Marker aus der Antwort bevor sie an Victor gesendet wird."""
    import re
    return re.sub(r'\[SAVE:[^\]]+\]\n?', '', response).strip()


def _parse_and_persist(response: str) -> list[str]:
    """
    Parst [SAVE:...] Marker aus Alberts Antwort und führt sie aus.
    Gibt Liste der ausgeführten Aktionen zurück (für Logging).
    """
    import re
    markers = re.findall(r'\[SAVE:([^\]]+)\]', response)
    if not markers:
        return []

    actions = []
    for marker in markers:
        parts = marker.split(':')
        action = parts[0].lower() if parts else ''

        try:
            # ── Markt-Bias ────────────────────────────────────────────────
            if action == 'bias' and len(parts) >= 2:
                bias = parts[1].upper()
                directive_file = DATA / 'ceo_directive.json'
                directive = {}
                if directive_file.exists():
                    try:
                        directive = json.loads(directive_file.read_text())
                    except Exception:
                        pass
                old_bias = directive.get('market_bias', 'NEUTRAL')
                directive['market_bias'] = bias
                directive['updated_at']  = datetime.now().isoformat()
                directive['updated_by']  = 'albert_discord'
                directive_file.write_text(json.dumps(directive, indent=2, ensure_ascii=False))
                actions.append(f'bias: {old_bias} → {bias}')

            # ── Sektor-Fokus ──────────────────────────────────────────────
            elif action == 'focus' and len(parts) >= 2:
                focus = parts[1].upper()
                directive_file = DATA / 'ceo_directive.json'
                directive = {}
                if directive_file.exists():
                    try:
                        directive = json.loads(directive_file.read_text())
                    except Exception:
                        pass
                directive['focus_sector'] = focus
                directive['updated_at']   = datetime.now().isoformat()
                directive['updated_by']   = 'albert_discord'
                directive_file.write_text(json.dumps(directive, indent=2, ensure_ascii=False))
                actions.append(f'focus_sector → {focus}')

            # ── Strategie pausieren ───────────────────────────────────────
            elif action == 'strategy_pause' and len(parts) >= 2:
                sid = parts[1].upper()
                strats_file = DATA / 'strategies.json'
                if strats_file.exists():
                    strats = json.loads(strats_file.read_text(encoding='utf-8'))
                    if sid in strats:
                        strats[sid]['status'] = 'paused'
                        strats[sid]['paused_by'] = 'albert_discord'
                        strats[sid]['paused_at'] = datetime.now().isoformat()
                        strats_file.write_text(json.dumps(strats, indent=2, ensure_ascii=False))
                        actions.append(f'strategy_pause: {sid}')

            # ── Strategie reaktivieren ────────────────────────────────────
            elif action == 'strategy_resume' and len(parts) >= 2:
                sid = parts[1].upper()
                strats_file = DATA / 'strategies.json'
                if strats_file.exists():
                    strats = json.loads(strats_file.read_text(encoding='utf-8'))
                    if sid in strats:
                        strats[sid]['status'] = 'active'
                        strats[sid]['resumed_at'] = datetime.now().isoformat()
                        strats_file.write_text(json.dumps(strats, indent=2, ensure_ascii=False))
                        actions.append(f'strategy_resume: {sid}')

            # ── Conviction ändern ─────────────────────────────────────────
            elif action == 'strategy_conviction' and len(parts) >= 3:
                sid        = parts[1].upper()
                conviction = int(parts[2])
                strats_file = DATA / 'strategies.json'
                if strats_file.exists():
                    strats = json.loads(strats_file.read_text(encoding='utf-8'))
                    if sid in strats:
                        old_conv = strats[sid].get('conviction', '?')
                        strats[sid]['conviction'] = conviction
                        if 'genesis' not in strats[sid]:
                            strats[sid]['genesis'] = {}
                        history = strats[sid]['genesis'].get('feedback_history', [])
                        history.append({
                            'date':           datetime.now().strftime('%Y-%m-%d'),
                            'old_conviction': old_conv,
                            'new_conviction': conviction,
                            'source':         'albert_discord',
                        })
                        strats[sid]['genesis']['feedback_history'] = history[-20:]
                        strats_file.write_text(json.dumps(strats, indent=2, ensure_ascii=False))
                        actions.append(f'conviction: {sid} {old_conv}→{conviction}')

            # ── Position sofort schließen ─────────────────────────────────
            elif action == 'exit' and len(parts) >= 2:
                ticker = parts[1].upper()
                try:
                    import sys as _sys
                    _sys.path.insert(0, str(SCRIPTS / 'execution'))
                    # Aktuellen Preis holen und Position schließen
                    import urllib.request as _req
                    import json as _json
                    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d'
                    req = _req.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with _req.urlopen(req, timeout=6) as r:
                        data = _json.load(r)
                    price = data['chart']['result'][0]['meta'].get('regularMarketPrice')
                    if price:
                        db_path = DATA / 'trading.db'
                        conn = sqlite3.connect(str(db_path))
                        pos = conn.execute(
                            "SELECT id, entry_price, shares FROM paper_portfolio "
                            "WHERE ticker=? AND status='OPEN' LIMIT 1",
                            (ticker,)
                        ).fetchone()
                        if pos:
                            pnl = (price - pos[1]) * pos[2]
                            now_str = datetime.now().isoformat()
                            conn.execute("""
                                UPDATE paper_portfolio
                                SET status='CLOSED', exit_price=?, exit_date=?,
                                    pnl_eur=?, notes=COALESCE(notes,'')||?
                                WHERE id=?
                            """, (price, now_str, pnl,
                                  f'\n[ALBERT DISCORD EXIT] Victor-Anweisung', pos[0]))
                            conn.execute(
                                "UPDATE paper_fund SET value=value+? WHERE key='current_cash' OR key='cash'",
                                (price * pos[2] - 1.0,)
                            )
                            conn.commit()
                            actions.append(f'exit: {ticker} @ {price:.2f}€ P&L={pnl:+.0f}€')
                        conn.close()
                except Exception as e:
                    actions.append(f'exit_fehler: {ticker} ({e})')

            # ── Weekly Trade Limit ────────────────────────────────────────
            elif action == 'weekly_limit' and len(parts) >= 2:
                limit = int(parts[1])
                directive_file = DATA / 'ceo_directive.json'
                directive = {}
                if directive_file.exists():
                    try:
                        directive = json.loads(directive_file.read_text())
                    except Exception:
                        pass
                directive['weekly_trade_limit'] = limit
                directive['updated_at'] = datetime.now().isoformat()
                directive['updated_by'] = 'albert_discord'
                directive_file.write_text(json.dumps(directive, indent=2, ensure_ascii=False))
                actions.append(f'weekly_limit → {limit}')

            # ── Notiz ins Daily-Log ───────────────────────────────────────
            elif action == 'note' and len(parts) >= 2:
                note_text = ':'.join(parts[1:])
                daily_log = MEMORY / f"{datetime.now().strftime('%Y-%m-%d')}.md"
                entry = f"\n## {datetime.now().strftime('%H:%M')} — Albert-Entscheidung\n\n{note_text}\n"
                if daily_log.exists():
                    daily_log.write_text(daily_log.read_text() + entry)
                actions.append(f'note gespeichert')

        except Exception as e:
            print(f'[Albert] SAVE-Marker Fehler ({marker}): {e}', flush=True)

    if actions:
        print(f'[Albert] Persistiert: {", ".join(actions)}', flush=True)

    return actions


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
        directive = _json.loads(directive_path.read_text()) if directive_path.exists() else {}
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


# ── Deep Dive ─────────────────────────────────────────────────────────────────

def _handle_deep_dive(ticker: str) -> str:
    """
    Vollständiger 6-Schritt Deep Dive nach deepdive-protokoll.md.
    Victor: "Deep Dive RHM.DE" → strukturierte Analyse mit Leiche-im-Keller-Check.

    Schritt 1: Technisches Bild (Kurs, MA, RSI, 52W)
    Schritt 2: Fundamentals (DB oder Fallback-Hinweis)
    Schritt 3: Analyst-Konsens (News-DB letzte 30 Tage)
    Schritt 4: Leiche im Keller (8 Pflichtfragen)
    Schritt 5: Makro & Sektor
    Schritt 6: Trading-Verdict (KAUFEN / WARTEN / NICHT KAUFEN)
    """
    # ── Technische Daten holen ────────────────────────────────────────────
    tech = {}
    try:
        sys_path_backup = None
        import sys as _sys
        _sys.path.insert(0, str(SCRIPTS))
        from core.live_data import get_price_eur  # type: ignore
        price = get_price_eur(ticker)
        if price:
            tech['price'] = price
    except Exception:
        pass

    try:
        conn = sqlite3.connect(str(DATA / 'trading.db'))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT close, date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 252",
            (ticker,)
        ).fetchall()
        conn.close()
        closes = [r['close'] for r in rows if r['close']]
        if closes:
            tech['current_db'] = closes[0]
            tech['high_52w']   = max(closes[:min(252, len(closes))])
            tech['low_52w']    = min(closes[:min(252, len(closes))])
            tech['dist_52wh']  = (closes[0] - tech['high_52w']) / tech['high_52w'] * 100
            # MA50 / MA200
            if len(closes) >= 50:
                tech['ma50']  = round(sum(closes[:50]) / 50, 2)
            if len(closes) >= 200:
                tech['ma200'] = round(sum(closes[:200]) / 200, 2)
            # RSI(14)
            if len(closes) >= 15:
                gains = [max(closes[i-1] - closes[i], 0) for i in range(1, 15)]
                losses = [max(closes[i] - closes[i-1], 0) for i in range(1, 15)]
                ag = sum(gains) / 14 or 0.001
                al = sum(losses) / 14 or 0.001
                tech['rsi'] = round(100 - 100 / (1 + ag / al), 1)
            # 3M / 6M performance
            if len(closes) >= 63:
                tech['perf_3m'] = round((closes[0] - closes[62]) / closes[62] * 100, 1)
            if len(closes) >= 126:
                tech['perf_6m'] = round((closes[0] - closes[125]) / closes[125] * 100, 1)
            # Trend-Urteil
            ma50 = tech.get('ma50')
            c = tech.get('price') or tech.get('current_db', 0)
            tech['above_ma50'] = c > ma50 if ma50 else None
    except Exception:
        pass

    # ── Analyst-News letzte 30 Tage ──────────────────────────────────────
    recent_news = []
    try:
        conn = sqlite3.connect(str(DATA / 'trading.db'))
        rows = conn.execute("""
            SELECT title, source, published_at FROM overnight_events
            WHERE (ticker = ? OR headline LIKE ?)
              AND published_at >= date('now', '-30 days')
            ORDER BY published_at DESC LIMIT 8
        """, (ticker, f'%{ticker}%')).fetchall()
        conn.close()
        recent_news = [(r[0] or '')[:120] + f' [{r[1]}, {str(r[2])[:10]}]' for r in rows]
    except Exception:
        pass

    # ── Strategie in strategies.json bekannt? ────────────────────────────
    known_strategy = None
    try:
        strategies = json.loads((DATA / 'strategies.json').read_text(encoding='utf-8'))
        for sid, s in strategies.items():
            if isinstance(s, dict) and ticker in s.get('tickers', []):
                known_strategy = {'id': sid, 'name': s.get('name', ''), 'thesis': s.get('thesis', '')[:300]}
                break
    except Exception:
        pass

    # ── Deepdive-Protokoll als Claude-Prompt ─────────────────────────────
    deepdive_protocol = (MEMORY / 'deepdive-protokoll.md').read_text(encoding='utf-8') \
        if (MEMORY / 'deepdive-protokoll.md').exists() else ''

    tech_summary = '\n'.join(f'  {k}: {v}' for k, v in tech.items())
    news_summary = '\n'.join(f'  - {n}' for n in recent_news) if recent_news else '  Keine News in DB gefunden.'
    strat_info   = f"Bekannte Strategie: {known_strategy}" if known_strategy else "Keine Strategie in strategies.json für diesen Ticker."

    prompt = f"""Victor hat "Deep Dive {ticker}" angefordert.
Führe jetzt den vollständigen 6-Schritt Deep Dive durch — EXAKT nach dem Protokoll unten.
Kein Schritt darf übersprungen werden. Schritt 4 (Leiche im Keller) ist Pflicht.
Ende immer mit dem Trading-Verdict Block.

TECHNISCHE DATEN (aus DB/Live):
{tech_summary if tech_summary.strip() else '  Keine technischen Daten in DB verfügbar.'}

RECENT NEWS (letzte 30 Tage):
{news_summary}

STRATEGIE-INFO:
{strat_info}

DEEP DIVE PROTOKOLL (befolge dies exakt):
{deepdive_protocol[:3000]}

Führe jetzt den Deep Dive durch. Nutze die oben gegebenen Daten als Basis.
Wo Daten fehlen: sage "Daten fehlen — manuell prüfen: [Quelle]" statt zu halluzinieren.
Schritt 4 (Leiche im Keller): Alle 8 Fragen explizit beantworten.
Abschluss: Trading-Verdict mit KAUFEN / WARTEN / NICHT KAUFEN."""

    response = ask_albert(prompt)

    # ── Verdict extrahieren und speichern ─────────────────────────────────────
    # Damit conviction_scorer.py prüfen kann ob ein Deep Dive für diesen Ticker
    # durchgeführt wurde — und was das Ergebnis war (KAUFEN / WARTEN / NICHT KAUFEN).
    try:
        verdict = 'UNBEKANNT'
        resp_upper = response.upper() if response else ''
        # Suche nach dem Trading-Verdict Block
        if 'NICHT KAUFEN' in resp_upper or 'NOT BUY' in resp_upper:
            verdict = 'NICHT_KAUFEN'
        elif 'KAUFEN' in resp_upper and 'NICHT' not in resp_upper.split('KAUFEN')[0][-20:]:
            verdict = 'KAUFEN'
        elif 'WARTEN' in resp_upper or 'WAIT' in resp_upper:
            verdict = 'WARTEN'
        elif 'KAUFEN' in resp_upper:
            verdict = 'KAUFEN'

        verdicts_file = DATA / 'deep_dive_verdicts.json'
        verdicts = {}
        if verdicts_file.exists():
            try:
                verdicts = json.loads(verdicts_file.read_text(encoding='utf-8'))
            except Exception:
                verdicts = {}

        verdicts[ticker.upper()] = {
            'verdict':   verdict,
            'timestamp': datetime.now().isoformat(),
            'date':      datetime.now().strftime('%Y-%m-%d'),
        }
        verdicts_file.write_text(json.dumps(verdicts, indent=2, ensure_ascii=False))
        print(f'[Albert] Deep Dive {ticker}: Verdict={verdict} gespeichert', flush=True)
    except Exception as _e:
        print(f'[Albert] Deep Dive Verdict-Speicherung fehlgeschlagen: {_e}', flush=True)

    return response


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

        # ── Deep Dive Command ─────────────────────────────────────────────
        # Victor: "Deep Dive RHM.DE" oder "deep dive AAPL"
        # → Vollständige 6-Schritt-Analyse nach deepdive-protokoll.md
        deep_dive_prefixes = ('deep dive ', 'deepdive ', 'deep-dive ')
        matched_dd = next(
            (p for p in deep_dive_prefixes if content_lower.startswith(p)), None
        )
        if matched_dd:
            ticker_raw = content_stripped[len(matched_dd):].strip().upper()
            if ticker_raw:
                _send_typing(CHANNEL_ID)
                response = _handle_deep_dive(ticker_raw)
                if len(response) <= 2000:
                    _send_message(response, CHANNEL_ID)
                else:
                    for i in range(0, len(response), 1900):
                        _send_message(response[i:i + 1900], CHANNEL_ID)
                        time.sleep(0.5)
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

        # Typing-Indikator senden
        _send_typing(CHANNEL_ID)

        # Antwort von Albert holen
        response = ask_albert(content)

        # SAVE-Marker parsen & persistieren (bevor sie aus der Antwort entfernt werden)
        _parse_and_persist(response)

        # SAVE-Marker aus Antwort entfernen bevor sie Victor angezeigt wird
        response = _strip_save_markers(response)

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
