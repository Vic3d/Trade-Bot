#!/usr/bin/env python3
"""
daily_memory_proposal.py — Tägliches Memory-Proposal (21:30 CEST).

Albert liest die letzten 24h aus:
  - data/conversation_log.jsonl (Discord + CLI-Marker)
  - data/strategies.json Änderungen (via mtime)
  - heutige Trades (paper_portfolio mit close_date oder entry_date today)

Fragt Claude (LLM): "Welche 3-5 Erkenntnisse sind merkenswert für die
Wissensbasis (memory/*.md)?" Pro Vorschlag: Ziel-Datei + Markdown-Block.

Speichert Vorschläge in `data/memory_proposals.json` (mit IDs 1..N) und
postet in Discord:

    📝 Memory-Vorschlag — heute habe ich 3 Erkenntnisse die ins Gedächtnis sollten:

    [1] → memory/trading-lessons.md
        "Trump-Pharma-Deals sind politisches Risiko Tier 1..."
    [2] → memory/strategien.md
        "PS_AMZN: Entry-Trigger neu kalibriert auf $260..."
    [3] → memory/victor-profil.md
        "Victor bevorzugt Sync via UserPromptSubmit-Hook..."

    Antworte: "Speichern 1,3" oder "Speichern alle" oder "Verwerfen".

Discord-Handler in `discord_chat.py` schreibt dann die Markdown-Blöcke
an die jeweiligen MD-Dateien (mit Datums-Header) und commits.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from core.llm_client import call_llm
from conversation_log import tail as conv_tail

PROPOSALS_FILE = WS / 'data' / 'memory_proposals.json'
LOG_FILE       = WS / 'data' / 'conversation_log.jsonl'
DB_FILE        = WS / 'data' / 'trading.db'

# Erlaubte Ziel-MD-Dateien (Albert darf nicht beliebige Dateien anlegen)
ALLOWED_TARGETS = {
    'memory/trading-lessons.md',
    'memory/strategien.md',
    'memory/strategie-albert.md',
    'memory/victor-profil.md',
    'memory/trade-decisions.md',
    'memory/strategy-changelog.md',
    'memory/feedback-log.md',
    'memory/learning-log.md',
    'memory/entscheidungs-log.md',
}

BERLIN = ZoneInfo('Europe/Berlin')


def _gather_today_context() -> str:
    """Sammelt 24h Kontext: Discord-Konversation + heutige Trades."""
    parts = []

    # 1. Letzte 24h Conversation-Log
    cutoff = datetime.now() - timedelta(hours=24)
    entries = conv_tail(n=80)
    recent = []
    for e in entries:
        try:
            ts = datetime.fromisoformat(e.get('ts', '')[:19])
            if ts >= cutoff:
                recent.append(e)
        except Exception:
            continue

    if recent:
        parts.append('## Discord/CLI Konversation letzte 24h')
        for e in recent[-40:]:
            t = e.get('ts', '')[11:16]
            spk = e.get('speaker', '?')
            content = (e.get('content') or '').replace('\n', ' ')[:300]
            parts.append(f'[{t}] {spk}: {content}')

    # 2. Heutige Trade-Aktivität
    today = datetime.now(BERLIN).strftime('%Y-%m-%d')
    try:
        c = sqlite3.connect(DB_FILE)
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT ticker, strategy, status, pnl_eur, pnl_pct, exit_type, notes,
                   COALESCE(close_date, entry_date) as date
            FROM paper_portfolio
            WHERE substr(COALESCE(close_date, entry_date), 1, 10) = ?
            ORDER BY date DESC
        """, (today,)).fetchall()
        c.close()
        if rows:
            parts.append(f'\n## Trade-Aktivität heute ({today})')
            for r in rows:
                pnl = f"{r['pnl_eur']:+.0f}€" if r['pnl_eur'] is not None else '—'
                parts.append(f"  {r['ticker']} ({r['strategy']}) {r['status']} {pnl} {r['exit_type'] or ''}")
    except Exception as e:
        parts.append(f'\n[Trade-Fetch-Fehler: {e}]')

    return '\n'.join(parts) if parts else '(keine Aktivität letzte 24h)'


def _build_prompt(context: str) -> str:
    targets_list = '\n'.join(f'  - {t}' for t in sorted(ALLOWED_TARGETS))
    return f"""Du bist Albert, der Trading-Bot von Victor. Du analysierst die letzten
24 Stunden Diskussion+Trading-Aktivität und schlägst 0–5 Einträge für die
Wissensbasis vor (Markdown-Dateien in memory/).

REGELN:
- Nur ECHTE Erkenntnisse, keine Floskeln. Wenn nichts Neues passiert: leeres Array zurück.
- Pro Eintrag max 4 Sätze. Konkret, falsifizierbar, datiert.
- Ziel-Datei aus folgender Whitelist:
{targets_list}
- Kein Trade-Spam (PnL-Reporting läuft separat). Fokus: Lehren, neue Regeln,
  Victor-Präferenzen, methodische Änderungen.

ANTWORT-FORMAT — STRIKTES JSON, NUR DAS, KEIN PROSA-TEXT DAVOR/DANACH:
{{
  "proposals": [
    {{
      "target": "memory/trading-lessons.md",
      "title": "kurzer Titel",
      "content": "1-4 Sätze Inhalt für den MD-Eintrag.",
      "reason": "warum merkenswert (1 Satz)"
    }},
    ...
  ]
}}

Wenn nichts merkenswert: {{"proposals": []}}.

────────── KONTEXT (letzte 24h) ──────────
{context}
──────────────────────────────────────────
"""


def _parse_response(text: str) -> list[dict]:
    """Extrahiert das JSON aus der LLM-Antwort (tolerant gegen ```json fences)."""
    text = (text or '').strip()
    # Strip markdown code fences
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text
        if text.endswith('```'):
            text = text.rsplit('```', 1)[0]
    # Find first { ... last }
    i = text.find('{')
    j = text.rfind('}')
    if i == -1 or j == -1:
        return []
    try:
        data = json.loads(text[i:j+1])
        props = data.get('proposals', [])
        # Validate each
        clean = []
        for p in props:
            if not isinstance(p, dict):
                continue
            tgt = p.get('target', '')
            if tgt not in ALLOWED_TARGETS:
                continue
            content = (p.get('content') or '').strip()
            if not content or len(content) < 20:
                continue
            clean.append({
                'target': tgt,
                'title': (p.get('title') or 'Notiz').strip()[:100],
                'content': content[:1200],
                'reason': (p.get('reason') or '').strip()[:200],
            })
        return clean[:5]
    except Exception as e:
        print(f'[parse error] {e}', file=sys.stderr)
        return []


def _format_for_discord(proposals: list[dict]) -> str:
    if not proposals:
        return '📝 **Memory-Check** — heute war nichts Neues merkenswert. Nichts zu speichern.'
    lines = [f'📝 **Memory-Vorschlag** — heute {len(proposals)} Erkenntnis'
             f'{"se" if len(proposals)>1 else ""} fürs Gedächtnis:\n']
    for i, p in enumerate(proposals, 1):
        lines.append(f"**[{i}]** → `{p['target']}`")
        lines.append(f"  *{p['title']}*")
        # Kürzen für Discord
        body = p['content'][:280]
        lines.append(f"  {body}{'…' if len(p['content']) > 280 else ''}")
        if p['reason']:
            lines.append(f"  _Grund: {p['reason']}_")
        lines.append('')
    lines.append('Antworte: **`Speichern 1,3`** oder **`Speichern alle`** oder **`Verwerfen`**')
    return '\n'.join(lines)


def _save_proposals(proposals: list[dict]) -> None:
    payload = {
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'status': 'pending',
        'proposals': proposals,
    }
    PROPOSALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROPOSALS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding='utf-8')


def main() -> int:
    print(f'[memory-proposal] Start {datetime.now().isoformat(timespec="seconds")}')
    context = _gather_today_context()
    if 'keine Aktivität' in context:
        print('[memory-proposal] Keine 24h-Aktivität — skip.')
        _save_proposals([])
        return 0

    prompt = _build_prompt(context)
    try:
        text, usage = call_llm(prompt, model_hint='sonnet', max_tokens=2000)
    except Exception as e:
        print(f'[memory-proposal] LLM-Fehler: {e}', file=sys.stderr)
        return 1

    proposals = _parse_response(text)
    print(f'[memory-proposal] {len(proposals)} Vorschläge generiert.')
    _save_proposals(proposals)

    # Discord-Post
    msg = _format_for_discord(proposals)
    try:
        from discord_sender import send
        send(msg, force=True)
        print('[memory-proposal] An Discord gesendet.')
    except Exception as e:
        print(f'[memory-proposal] Discord-Send-Fehler: {e}', file=sys.stderr)

    # Log auch ins Conversation-Log
    try:
        from conversation_log import append as conv_append
        conv_append(source='cli', role='system', speaker='memory_proposer',
                    content=f'{len(proposals)} Memory-Vorschläge generiert',
                    meta={'event': 'memory_proposal', 'count': len(proposals)})
    except Exception:
        pass

    return 0


if __name__ == '__main__':
    sys.exit(main())
