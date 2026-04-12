#!/usr/bin/env python3
"""
Autonomous CEO — Albert's KI-Gehirn
=====================================
Läuft alle 2h während Marktzeiten (09-22h CET, Mo-Fr).

Ablauf:
  1. Vollständigen System-State lesen (Positionen, News, Candidates, Regime)
  2. Claude API aufrufen — Albert entscheidet autonom
  3. Entscheidungen ausführen: Entries, Exits, Deep Dives, Strategy-Updates
  4. Discord-Report an Victor

Entscheidungstypen:
  DEEP_DIVE       → Analyse einer Aktie, Verdict in deep_dive_verdicts.json
  ENTRY           → Trade eröffnen (alle Guards bleiben aktiv)
  EXIT_POSITION   → Position vorzeitig schließen
  UPDATE_STRATEGY → Conviction/Status in strategies.json ändern
  SEND_REPORT     → Discord-Nachricht an Victor
  HOLD            → Keine Aktion

Usage:
  python3 autonomous_ceo.py            # normaler Run
  python3 autonomous_ceo.py --dry-run  # Analyse ohne Trades
  python3 autonomous_ceo.py --force    # auch außerhalb Marktzeiten
"""

import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS      = Path('/data/.openclaw/workspace')
DATA    = WS / 'data'
MEMORY  = WS / 'memory'
SCRIPTS = WS / 'scripts'

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / 'execution'))
sys.path.insert(0, str(SCRIPTS / 'intelligence'))
sys.path.insert(0, str(SCRIPTS / 'core'))

CLAUDE_MODEL   = 'claude-opus-4-5'
VICTOR_USER_ID = '452053147620343808'
LOG_FILE       = DATA / 'autonomous_ceo.log'
DECISIONS_LOG  = DATA / 'ceo_decisions.json'


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str, level: str = 'INFO'):
    ts   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] [{level}] {msg}'
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


# ── Marktzeit-Check ───────────────────────────────────────────────────────────

def is_market_time() -> bool:
    """Nur zwischen 09-22h CET, Mo-Fr."""
    try:
        import zoneinfo
        now = datetime.now(zoneinfo.ZoneInfo('Europe/Berlin'))
        if now.weekday() >= 5:
            return False
        return 9 <= now.hour < 22
    except Exception:
        return True


# ── Kontext aufbauen ─────────────────────────────────────────────────────────

def build_context() -> str:
    """
    Erstellt einen vollständigen System-State-String für Albert's Entscheidung.
    Enthält: Positionen, Cash, News, Candidates, Regime, Performance, Strategien.
    """
    parts = []
    now   = datetime.now().strftime('%Y-%m-%d %H:%M')
    parts.append(f'=== ALBERT CEO KONTEXT (Stand: {now}) ===\n')

    db_path = DATA / 'trading.db'

    # 1. CASH + PORTFOLIO-ÜBERSICHT
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        cash_row = conn.execute(
            "SELECT value FROM paper_fund WHERE key='current_cash' OR key='cash' LIMIT 1"
        ).fetchone()
        cash = float(cash_row[0]) if cash_row else 0.0

        positions = conn.execute("""
            SELECT ticker, strategy, entry_price, stop_price, target_price,
                   shares, entry_date, conviction, notes
            FROM paper_portfolio WHERE status='OPEN'
            ORDER BY entry_date DESC
        """).fetchall()

        recent_trades = conn.execute("""
            SELECT ticker, strategy, pnl_eur, pnl_pct, exit_date, status
            FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
            ORDER BY exit_date DESC LIMIT 10
        """).fetchall()

        parts.append(f'--- PORTFOLIO ---')
        parts.append(f'Cash verfügbar: {cash:,.0f}€')
        parts.append(f'Offene Positionen: {len(positions)}')

        if positions:
            parts.append('\nOffene Positionen:')
            for p in positions:
                crv = 0
                risk = p['entry_price'] - p['stop_price']
                if risk > 0:
                    crv = (p['target_price'] - p['entry_price']) / risk
                parts.append(
                    f"  {p['ticker']:8s} | {p['strategy']:12s} | "
                    f"Entry {p['entry_price']:.2f}€ | Stop {p['stop_price']:.2f}€ | "
                    f"Target {p['target_price']:.2f}€ | CRV {crv:.1f} | "
                    f"seit {str(p['entry_date'])[:10]}"
                )

        if recent_trades:
            parts.append('\nLetzte 10 Trades:')
            wins   = sum(1 for t in recent_trades if t['pnl_eur'] and t['pnl_eur'] > 0)
            losses = sum(1 for t in recent_trades if t['pnl_eur'] and t['pnl_eur'] < 0)
            total_pnl = sum(t['pnl_eur'] or 0 for t in recent_trades)
            parts.append(f"  {wins}W / {losses}L | P&L: {total_pnl:+.0f}€")
            for t in recent_trades[:5]:
                parts.append(
                    f"  {'✅' if (t['pnl_eur'] or 0) > 0 else '❌'} "
                    f"{t['ticker']} ({t['strategy']}) "
                    f"{t['pnl_eur']:+.0f}€ | {str(t['exit_date'])[:10]}"
                )

        conn.close()
    except Exception as e:
        parts.append(f'[Portfolio-Fehler: {e}]')

    # 2. SCANNER KANDIDATEN (pending_setups)
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        candidates = conn.execute("""
            SELECT ticker, strategy, conviction, entry_trigger, current_price,
                   stop_suggestion, target_suggestion, notes
            FROM pending_setups
            WHERE status='WATCHING'
            ORDER BY conviction DESC
            LIMIT 15
        """).fetchall()
        conn.close()

        if candidates:
            parts.append('\n--- SCANNER KANDIDATEN (warten auf Entry) ---')
            for c in candidates:
                crv = 0
                risk = (c['entry_trigger'] or c['current_price'] or 0) - (c['stop_suggestion'] or 0)
                if risk and risk > 0:
                    crv = ((c['target_suggestion'] or 0) - (c['entry_trigger'] or 0)) / risk
                parts.append(
                    f"  {c['ticker']:8s} | {c['strategy']:10s} | "
                    f"Entry: {c['entry_trigger']:.2f}€ | Stop: {(c['stop_suggestion'] or 0):.2f}€ | "
                    f"Target: {(c['target_suggestion'] or 0):.2f}€ | CRV: {crv:.1f} | "
                    f"{(c['notes'] or '')[:60]}"
                )
        else:
            parts.append('\n--- SCANNER KANDIDATEN ---\n[Keine Kandidaten im Moment]')
    except Exception as e:
        parts.append(f'\n[Kandidaten-Fehler: {e}]')

    # 3. AKTUELLE NEWS (letzte 8h)
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        news = conn.execute("""
            SELECT headline, impact_direction, strategies_affected, timestamp
            FROM overnight_events
            WHERE timestamp >= datetime('now', '-8 hours')
            ORDER BY timestamp DESC
            LIMIT 20
        """).fetchall()
        conn.close()

        if news:
            parts.append('\n--- AKTUELLE NEWS (letzte 8h) ---')
            for n in news:
                parts.append(
                    f"  [{n['impact_direction'] or 'news'}] "
                    f"{(n['headline'] or '')[:90]}"
                )
        else:
            parts.append('\n--- AKTUELLE NEWS ---\n[Keine neuen Events]')
    except Exception as e:
        parts.append(f'\n[News-Fehler: {e}]')

    # 4. MARKT-REGIME
    try:
        regime_file = DATA / 'market-regime.json'
        if regime_file.exists():
            regime = json.loads(regime_file.read_text())
            vix    = regime.get('vix', '?')
            reg    = regime.get('current_regime', '?')
            parts.append(f'\n--- MARKT-REGIME ---')
            parts.append(f'Regime: {reg} | VIX: {vix}')
    except Exception:
        pass

    # 5. ALPHA DECAY (welche Strategien performen)
    try:
        decay_file = DATA / 'alpha_decay.json'
        if decay_file.exists():
            decay = json.loads(decay_file.read_text())
            parts.append('\n--- ALPHA DECAY ---')
            for sid, d in list(decay.items())[:8]:
                trend  = d.get('trend', '?')
                wr     = d.get('raw_win_rate', 0)
                n      = d.get('n_trades', 0)
                parts.append(f'  {sid:12s} | WR {wr:.0%} | {n} Trades | {trend}')
    except Exception:
        pass

    # 6. DEEP DIVE VERDICTS (welche Aktien frisch analysiert)
    try:
        verdicts_file = DATA / 'deep_dive_verdicts.json'
        if verdicts_file.exists():
            verdicts = json.loads(verdicts_file.read_text())
            fresh = {
                ticker: v for ticker, v in verdicts.items()
                if (datetime.now() - datetime.fromisoformat(v.get('timestamp', '2000-01-01'))).days <= 14
            }
            if fresh:
                parts.append('\n--- DEEP DIVE VERDICTS (≤14 Tage) ---')
                for ticker, v in fresh.items():
                    parts.append(f"  {ticker}: {v.get('verdict','?')} ({v.get('date','?')})")
    except Exception:
        pass

    # 7. CEO DIREKTIVE (inkl. Victor-Anweisungen aus Discord)
    try:
        directive_file = DATA / 'ceo_directive.json'
        if directive_file.exists():
            directive = json.loads(directive_file.read_text())
            bias         = directive.get('market_bias', directive.get('mode', 'NEUTRAL'))
            focus        = directive.get('focus_sector', '')
            weekly_limit = directive.get('weekly_trade_limit', 3)
            updated_by   = directive.get('updated_by', '')
            parts.append(f'\n--- CEO DIREKTIVE ---')
            parts.append(f'Markt-Bias: {bias} | Fokus: {focus or "alle Sektoren"} | Max Trades/Woche: {weekly_limit}')
            if updated_by == 'albert_discord':
                parts.append(f'⚠️ Victor-Anweisung aktiv (via Discord)')
    except Exception:
        pass

    return '\n'.join(parts)


# ── Claude API Call ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Du bist Albert — autonomer Trading-CEO des TradeMind Paper-Trading-Systems.
Du hast VOLLE ENTSCHEIDUNGSAUTORITÄT. Victor hat dir diese Autonomie bewusst gegeben.
Du MUSST eigenständig handeln — keine Anfragen, keine Bestätigungen.

DEINE AUFGABE:
1. Analysiere den aktuellen System-State
2. Identifiziere Chancen (aus Scanner-Kandidaten + eigenen Überlegungen)
3. Bewerte offene Positionen
4. Triff klare Entscheidungen

TRADING-REGELN (ABSOLUT):
- Nur Trades mit CRV ≥ 2:1
- Stop-Loss IMMER gesetzt
- Max 3 neue Trades pro Woche
- Cash-Reserve min. 10% halten
- Keine Aktien kaufen ohne begründete These
- Bei BEARISH/CRASH-Regime: nur Thesis-Plays, keine spekulativen Entries
- Blacklist: DT1-DT5, AR-AGRA, AR-HALB (NIEMALS aktivieren)

FÜR JEDEN TRADE DEN DU EINGEHST: Mach mental einen Quick-Deep-Dive:
- Was ist die Thesis? Warum jetzt?
- Was ist der Katalysator?
- Wo ist das Risiko? (Leiche im Keller?)
- Stimmt die Technik?

ANTWORTFORMAT — NUR GÜLTIGES JSON, KEIN ANDERER TEXT:
{
  "analysis": "2-3 Sätze: Marktlage, deine Einschätzung, was du siehst",
  "decisions": [
    {
      "action": "DEEP_DIVE",
      "ticker": "TICKER",
      "reason": "Warum jetzt analysieren"
    },
    {
      "action": "ENTRY",
      "ticker": "TICKER",
      "strategy": "PS1",
      "entry_price": 54.20,
      "stop_price": 49.86,
      "target_price": 63.00,
      "thesis": "Kurze These (1 Satz)",
      "verdict": "KAUFEN",
      "reason": "Begründung für Entry"
    },
    {
      "action": "EXIT_POSITION",
      "ticker": "TICKER",
      "reason": "Warum Exit"
    },
    {
      "action": "UPDATE_STRATEGY",
      "strategy_id": "PS1",
      "conviction": 3,
      "status": "active",
      "reason": "Warum Update"
    },
    {
      "action": "HOLD",
      "reason": "Keine Aktion nötig, weil..."
    }
  ]
}

Du kannst mehrere Decisions kombinieren. Mindestens eine Decision muss immer vorhanden sein.
Bei keiner Aktion: nur HOLD zurückgeben.
"""


def call_ai(context: str) -> dict | None:
    """Ruft Claude API auf und gibt die geparsten Decisions zurück."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        log('ANTHROPIC_API_KEY nicht gesetzt — abbruch', 'ERROR')
        return None

    try:
        import anthropic
        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{
                'role':    'user',
                'content': context + '\n\nTreff jetzt deine Entscheidungen. Antworte NUR mit JSON.'
            }],
        )
        raw = response.content[0].text.strip()

        # JSON aus Antwort extrahieren (manchmal mit ```json``` umhüllt)
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]

        result = json.loads(raw)
        log(f"KI-Analyse: {result.get('analysis', '')[:100]}")
        return result

    except json.JSONDecodeError as e:
        log(f'JSON-Parse-Fehler: {e} | Antwort: {raw[:200]}', 'ERROR')
        return None
    except Exception as e:
        log(f'Claude API Fehler: {e}', 'ERROR')
        return None


# ── Entscheidungen ausführen ─────────────────────────────────────────────────

def execute_deep_dive(ticker: str, reason: str, dry_run: bool = False) -> str:
    """
    Führt Deep Dive durch: ruft KI mit Deep-Dive-Prompt auf,
    speichert Verdict in deep_dive_verdicts.json.
    """
    log(f'DEEP DIVE: {ticker} — {reason}')
    if dry_run:
        return 'KAUFEN'  # Dry-run: assume positive

    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return 'WARTEN'

    try:
        import anthropic
        deepdive_prompt_file = MEMORY / 'deepdive-protokoll.md'
        protocol = deepdive_prompt_file.read_text(encoding='utf-8') if deepdive_prompt_file.exists() else ''

        prompt = f"""Führe einen Deep Dive für {ticker} durch.

{protocol[:2000] if protocol else '6-Schritt-Analyse: These, Katalysator, Risiken (Leiche im Keller), Technik, CRV, Verdict.'}

Aktie: {ticker}
Anlass: {reason}

Analysiere und gib am Ende ein klares Trading-Verdict:
KAUFEN — wenn Thesis stark, Katalysator klar, Risiken beherrschbar
WARTEN — wenn Setup noch nicht reif
NICHT_KAUFEN — wenn fundamentale Probleme oder zu hohes Risiko

Antworte mit: VERDICT: [KAUFEN/WARTEN/NICHT_KAUFEN]"""

        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            messages=[{'role': 'user', 'content': prompt}],
        )
        response_text = response.content[0].text

        # Verdict extrahieren
        verdict = 'WARTEN'
        for line in response_text.split('\n'):
            if 'VERDICT:' in line.upper() or 'KAUFEN' in line.upper():
                if 'NICHT_KAUFEN' in line.upper() or 'NICHT KAUFEN' in line.upper():
                    verdict = 'NICHT_KAUFEN'
                elif 'KAUFEN' in line.upper():
                    verdict = 'KAUFEN'
                elif 'WARTEN' in line.upper():
                    verdict = 'WARTEN'
                break

        # Verdict speichern
        verdicts_file = DATA / 'deep_dive_verdicts.json'
        verdicts = {}
        if verdicts_file.exists():
            try:
                verdicts = json.loads(verdicts_file.read_text())
            except Exception:
                pass
        verdicts[ticker.upper()] = {
            'verdict':    verdict,
            'timestamp':  datetime.now().isoformat(),
            'date':       datetime.now().strftime('%Y-%m-%d'),
            'source':     'autonomous_ceo',
            'reason':     reason,
        }
        verdicts_file.write_text(json.dumps(verdicts, indent=2, ensure_ascii=False))
        log(f'Deep Dive {ticker}: {verdict}')
        return verdict

    except Exception as e:
        log(f'Deep Dive Fehler ({ticker}): {e}', 'ERROR')
        return 'WARTEN'


def execute_entry(decision: dict, dry_run: bool = False) -> dict:
    """Führt ENTRY aus — alle Guards in paper_trade_engine bleiben aktiv."""
    ticker   = decision.get('ticker', '').upper()
    strategy = decision.get('strategy', 'PS_AUTO')
    entry    = decision.get('entry_price')
    stop     = decision.get('stop_price')
    target   = decision.get('target_price')
    thesis   = decision.get('thesis', 'Autonomous CEO Entry')
    verdict  = decision.get('verdict', 'KAUFEN')

    log(f'ENTRY: {ticker} | {strategy} | Entry={entry} | Stop={stop} | Target={target}')

    if dry_run:
        return {'success': False, 'skipped': True, 'reason': 'dry_run'}

    if not all([ticker, entry, stop, target]):
        return {'success': False, 'reason': 'Fehlende Parameter (entry/stop/target)'}

    # Verdict in deep_dive_verdicts.json sicherstellen
    verdicts_file = DATA / 'deep_dive_verdicts.json'
    verdicts = {}
    if verdicts_file.exists():
        try:
            verdicts = json.loads(verdicts_file.read_text())
        except Exception:
            pass
    if ticker not in verdicts or verdicts[ticker].get('verdict') != 'KAUFEN':
        if verdict == 'KAUFEN':
            verdicts[ticker] = {
                'verdict':   'KAUFEN',
                'timestamp': datetime.now().isoformat(),
                'date':      datetime.now().strftime('%Y-%m-%d'),
                'source':    'autonomous_ceo',
                'reason':    decision.get('reason', ''),
            }
            verdicts_file.write_text(json.dumps(verdicts, indent=2, ensure_ascii=False))
        else:
            return {'success': False, 'reason': f'Kein KAUFEN-Verdict (hat: {verdict})'}

    try:
        from paper_trade_engine import execute_paper_entry
        result = execute_paper_entry(
            ticker=ticker,
            strategy=strategy,
            entry_price=float(entry),
            stop_price=float(stop),
            target_price=float(target),
            thesis=f'[AUTO_CEO] {thesis}',
            source='autonomous_ceo',
        )
        if result.get('success'):
            log(f'  ✅ {ticker} eingetragen (ID {result.get("trade_id")})')
        else:
            log(f'  ❌ {ticker} blockiert: {result.get("reason", "?")}')
        return result
    except Exception as e:
        log(f'  ❌ execute_paper_entry Fehler: {e}', 'ERROR')
        return {'success': False, 'reason': str(e)}


def execute_exit(ticker: str, reason: str, dry_run: bool = False) -> dict:
    """Schließt eine offene Position vorzeitig."""
    log(f'EXIT: {ticker} — {reason}')
    if dry_run:
        return {'success': False, 'skipped': True, 'reason': 'dry_run'}

    try:
        db_path = DATA / 'trading.db'
        conn    = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        pos = conn.execute(
            "SELECT id, entry_price, shares, strategy FROM paper_portfolio "
            "WHERE ticker=? AND status='OPEN' LIMIT 1",
            (ticker.upper(),)
        ).fetchone()

        if not pos:
            conn.close()
            return {'success': False, 'reason': f'Keine offene Position für {ticker}'}

        # Aktuellen Preis holen
        exit_price = None
        try:
            url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.load(r)
            exit_price = data['chart']['result'][0]['meta'].get('regularMarketPrice')
        except Exception:
            pass

        if not exit_price:
            conn.close()
            return {'success': False, 'reason': 'Preis nicht abrufbar — Exit abgebrochen'}

        shares  = pos['shares']
        pnl_eur = (exit_price - pos['entry_price']) * shares
        pnl_pct = (exit_price / pos['entry_price'] - 1) * 100
        now_str = datetime.now(timezone.utc).isoformat()

        conn.execute("""
            UPDATE paper_portfolio
            SET status='CLOSED', exit_price=?, exit_date=?,
                pnl_eur=?, pnl_pct=?, notes=COALESCE(notes,'')||?
            WHERE id=?
        """, (exit_price, now_str, pnl_eur, pnl_pct,
              f'\n[AUTO_CEO EXIT {datetime.now().strftime("%Y-%m-%d")}] {reason}',
              pos['id']))
        conn.execute(
            "UPDATE paper_fund SET value = value + ? WHERE key='current_cash' OR key='cash'",
            (exit_price * shares - 1.0,)
        )
        conn.commit()
        conn.close()

        log(f'  ✅ {ticker} geschlossen: {exit_price:.2f}€ | P&L: {pnl_eur:+.0f}€ ({pnl_pct:+.1f}%)')
        return {'success': True, 'ticker': ticker, 'exit_price': exit_price,
                'pnl_eur': pnl_eur, 'pnl_pct': pnl_pct}

    except Exception as e:
        log(f'  ❌ Exit Fehler ({ticker}): {e}', 'ERROR')
        return {'success': False, 'reason': str(e)}


def execute_update_strategy(strategy_id: str, conviction: int | None,
                             status: str | None, reason: str, dry_run: bool = False):
    """Aktualisiert Conviction/Status einer Strategie in strategies.json."""
    log(f'UPDATE_STRATEGY: {strategy_id} | conviction={conviction} | status={status}')
    if dry_run:
        return

    strats_file = DATA / 'strategies.json'
    if not strats_file.exists():
        return

    try:
        strats = json.loads(strats_file.read_text(encoding='utf-8'))
        if strategy_id not in strats:
            log(f'  Strategie {strategy_id} nicht in strategies.json', 'WARN')
            return

        if conviction is not None:
            strats[strategy_id]['conviction'] = conviction
        if status is not None:
            strats[strategy_id]['status'] = status

        # Feedback-History updaten
        if 'genesis' not in strats[strategy_id]:
            strats[strategy_id]['genesis'] = {}
        history = strats[strategy_id]['genesis'].get('feedback_history', [])
        history.append({
            'date':   datetime.now().strftime('%Y-%m-%d'),
            'reason': reason[:100],
            'source': 'autonomous_ceo',
            'new_conviction': conviction,
            'new_status':     status,
        })
        strats[strategy_id]['genesis']['feedback_history'] = history[-20:]

        strats_file.write_text(json.dumps(strats, indent=2, ensure_ascii=False))
        log(f'  ✅ {strategy_id} aktualisiert')
    except Exception as e:
        log(f'  ❌ Strategy-Update Fehler: {e}', 'ERROR')


def send_discord_report(message: str):
    """Schickt Bericht an Victor per Discord DM."""
    token = os.environ.get('DISCORD_BOT_TOKEN', '')
    if not token:
        log('DISCORD_BOT_TOKEN nicht gesetzt — kein Report', 'WARN')
        return

    try:
        # DM-Kanal öffnen
        payload = json.dumps({'recipient_id': VICTOR_USER_ID}).encode()
        req = urllib.request.Request(
            'https://discord.com/api/v10/users/@me/channels',
            data=payload,
            headers={'Authorization': f'Bot {token}', 'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            channel = json.loads(r.read())
        channel_id = channel.get('id')

        if not channel_id:
            return

        # Nachricht senden (aufteilen wenn zu lang)
        chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
        for chunk in chunks:
            msg_payload = json.dumps({'content': chunk}).encode()
            msg_req = urllib.request.Request(
                f'https://discord.com/api/v10/channels/{channel_id}/messages',
                data=msg_payload,
                headers={'Authorization': f'Bot {token}', 'Content-Type': 'application/json'},
            )
            urllib.request.urlopen(msg_req, timeout=10)

        log('Discord-Report gesendet')
    except Exception as e:
        log(f'Discord-Send Fehler: {e}', 'WARN')


# ── Entscheidungs-Log ─────────────────────────────────────────────────────────

def save_decision_log(analysis: str, decisions: list, results: list):
    """Speichert alle Entscheidungen + Ergebnisse in ceo_decisions.json."""
    try:
        log_data = []
        if DECISIONS_LOG.exists():
            try:
                log_data = json.loads(DECISIONS_LOG.read_text())
            except Exception:
                pass

        entry = {
            'timestamp': datetime.now().isoformat(),
            'analysis':  analysis,
            'decisions': decisions,
            'results':   results,
        }
        log_data.append(entry)
        log_data = log_data[-100:]  # Letzte 100 Runs behalten
        DECISIONS_LOG.write_text(json.dumps(log_data, indent=2, ensure_ascii=False))
    except Exception as e:
        log(f'Decision-Log Fehler: {e}', 'WARN')


# ── Haupt-Run ─────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, force: bool = False):
    """Hauptfunktion — wird vom Scheduler aufgerufen."""
    if not force and not is_market_time():
        log('Außerhalb Marktzeiten (09-22h CET, Mo-Fr) — kein Run')
        return

    log(f'=== Autonomous CEO Run {"[DRY-RUN]" if dry_run else ""} ===')

    # 1. Kontext aufbauen
    context = build_context()
    log(f'Kontext: {len(context)} Zeichen')

    # 2. KI aufrufen
    ai_result = call_ai(context)
    if not ai_result:
        log('Kein KI-Ergebnis — abbruch', 'ERROR')
        return

    analysis  = ai_result.get('analysis', '')
    decisions = ai_result.get('decisions', [])
    log(f'{len(decisions)} Entscheidung(en) erhalten')

    # 3. Entscheidungen ausführen
    results      = []
    report_parts = [f'🤖 **Albert CEO — {datetime.now().strftime("%H:%M")}**\n']
    report_parts.append(f'📊 *{analysis}*\n')

    entries_done = 0
    for d in decisions:
        action = d.get('action', '').upper()
        reason = d.get('reason', '')

        if action == 'DEEP_DIVE':
            ticker  = d.get('ticker', '').upper()
            verdict = execute_deep_dive(ticker, reason, dry_run=dry_run)
            results.append({'action': action, 'ticker': ticker, 'verdict': verdict})
            report_parts.append(f'🔍 Deep Dive **{ticker}**: {verdict}')

            # Direkt Entry wenn KAUFEN + im context als Kandidat
            if verdict == 'KAUFEN' and not dry_run:
                log(f'  → KAUFEN Verdict für {ticker}, prüfe Scanner-Kandidaten...')

        elif action == 'ENTRY' and entries_done < 3:
            result = execute_entry(d, dry_run=dry_run)
            results.append({'action': action, 'ticker': d.get('ticker'), **result})
            if result.get('success'):
                entries_done += 1
                report_parts.append(
                    f"✅ Entry **{d.get('ticker')}** ({d.get('strategy')}) | "
                    f"Stop {d.get('stop_price')}€ → Ziel {d.get('target_price')}€"
                )
            elif result.get('skipped'):
                report_parts.append(f"⏭️ {d.get('ticker')} übersprungen (dry-run)")
            else:
                report_parts.append(
                    f"❌ Entry **{d.get('ticker')}** blockiert: {result.get('reason', '?')[:60]}"
                )

        elif action == 'EXIT_POSITION':
            ticker = d.get('ticker', '').upper()
            result = execute_exit(ticker, reason, dry_run=dry_run)
            results.append({'action': action, 'ticker': ticker, **result})
            if result.get('success'):
                report_parts.append(
                    f"💰 Exit **{ticker}**: {result.get('pnl_eur', 0):+.0f}€ | {reason[:50]}"
                )
            else:
                report_parts.append(f"❌ Exit {ticker} fehlgeschlagen: {result.get('reason', '?')[:50]}")

        elif action == 'UPDATE_STRATEGY':
            sid = d.get('strategy_id', '')
            execute_update_strategy(
                strategy_id=sid,
                conviction=d.get('conviction'),
                status=d.get('status'),
                reason=reason,
                dry_run=dry_run,
            )
            results.append({'action': action, 'strategy_id': sid})
            report_parts.append(
                f"📝 Strategie **{sid}** aktualisiert: conviction={d.get('conviction')} | {reason[:50]}"
            )

        elif action == 'HOLD':
            results.append({'action': 'HOLD', 'reason': reason})
            report_parts.append(f'⏸️ HOLD: {reason[:80]}')

    # 4. Entscheidungs-Log speichern
    save_decision_log(analysis, decisions, results)

    # 5. Discord-Report
    report = '\n'.join(report_parts)
    log(f'Report ({len(report)} Zeichen):\n{report}')
    if not dry_run:
        send_discord_report(report)

    log(f'=== CEO Run abgeschlossen: {len(decisions)} Entscheidungen ===')
    return results


# ── Standalone ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    force   = '--force' in sys.argv
    run(dry_run=dry_run, force=force)
