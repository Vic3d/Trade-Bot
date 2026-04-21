#!/usr/bin/env python3
"""
Phase 22 Digest Block — 5-Block Morgen-Briefing-Addon
=======================================================
Liefert zusammenhaengenden Text-Block, der oben ins Morgen-Briefing
gehaengt wird. Fuenf Abschnitte:

  1. Gestern erledigt   (Trades opened/closed, Exits, Kill-Trigger)
  2. Heute anstehend    (Catalyst-Dates heute, Earnings, Events)
  3. Watchlist-Updates  (TRIGGER_HIT, status changes)
  4. Neue Kandidaten    (Thesen die < 24h neu im Draft)
  5. System-Status      (Cash, Positions, TQS-Verteilung, Flags)

Standalone testbar:
  python3 scripts/phase22_digest_block.py
"""
from __future__ import annotations
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
STRATS = WS / 'data' / 'strategies.json'
WATCHLIST = WS / 'data' / 'watchlist.json'


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}


# ── Block 1: Gestern erledigt ────────────────────────────────────────────
def block_yesterday() -> list[str]:
    if not DB.exists():
        return ['  (keine DB)']
    y = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    lines = []
    try:
        c = sqlite3.connect(str(DB))
        # Entries gestern
        rows = c.execute(
            "SELECT ticker, strategy, entry_price, shares FROM paper_portfolio "
            "WHERE date(entry_date) = ? ORDER BY id DESC LIMIT 10",
            (y,)
        ).fetchall()
        for t, s, px, sh in rows:
            lines.append(f'  📈 ENTRY {t} ({s}) {sh}x @ {px:.2f}')
        # Exits gestern
        rows = c.execute(
            "SELECT ticker, strategy, close_price, pnl_eur, exit_type FROM paper_portfolio "
            "WHERE date(close_date) = ? ORDER BY id DESC LIMIT 10",
            (y,)
        ).fetchall()
        for t, s, px, pnl, ext in rows:
            sign = '🟢' if (pnl or 0) > 0 else '🔴'
            lines.append(f'  {sign} EXIT {t} ({s}) @ {px:.2f} — {pnl:+.0f}€ [{ext or "?"}]')
        c.close()
    except Exception as e:
        lines.append(f'  (Fehler: {e})')

    # Kill-Trigger aus data/watchlist.log
    log = WS / 'data' / 'watchlist.log'
    if log.exists():
        try:
            txt = log.read_text(encoding='utf-8', errors='ignore')
            for line in txt.splitlines()[-100:]:
                if y in line and ('TRIGGER_HIT' in line or 'ARCHIVED' in line):
                    lines.append(f'  ⚙️  {line.split("] ", 1)[-1][:120]}')
        except Exception:
            pass

    return lines or ['  Gestern keine Aktivitaet.']


# ── Block 2: Heute anstehend ─────────────────────────────────────────────
def block_today() -> list[str]:
    strats = _load_json(STRATS)
    today = date.today()
    lines = []
    for sid, cfg in strats.items():
        if not isinstance(cfg, dict) or sid.startswith('_'):
            continue
        cat = cfg.get('catalyst') or {}
        cd = cat.get('date')
        if not cd:
            continue
        try:
            cdate = date.fromisoformat(cd[:10])
        except Exception:
            continue
        days = (cdate - today).days
        if -1 <= days <= 2:
            tkr = (cfg.get('tickers') or [cfg.get('ticker')] or ['?'])[0] or '?'
            ev = (cat.get('event') or '')[:60]
            when = 'heute' if days == 0 else ('morgen' if days == 1 else f'{days:+d}T')
            lines.append(f'  📅 {sid:12} [{tkr:<8}] {when:6} {ev}')

    # sekundaere Katalysatoren (Earnings in <7d)
    for sid, cfg in strats.items():
        if not isinstance(cfg, dict) or sid.startswith('_'):
            continue
        sec = (cfg.get('catalyst') or {}).get('secondary') or {}
        ed = sec.get('earnings_date')
        if not ed:
            continue
        try:
            edate = date.fromisoformat(ed[:10])
        except Exception:
            continue
        d = (edate - today).days
        if 0 <= d <= 7:
            tkr = (cfg.get('tickers') or [cfg.get('ticker')] or ['?'])[0] or '?'
            lines.append(f'  📊 {sid:12} [{tkr:<8}] Earnings in {d}T ({edate.isoformat()})')

    return lines[:10] or ['  Keine Katalysatoren in den naechsten 2 Tagen.']


# ── Block 3: Watchlist-Updates ───────────────────────────────────────────
def block_watchlist() -> list[str]:
    wl = _load_json(WATCHLIST)
    theses = wl.get('theses', {})
    if not theses:
        return ['  (Watchlist leer)']
    # Was hat sich seit gestern geaendert?
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat(timespec='seconds')
    recent_changes = []
    trigger_hit = []
    new_traded = []
    for sid, e in theses.items():
        if e.get('status') == 'TRIGGER_HIT':
            trigger_hit.append(sid)
        if e.get('status') == 'TRADED' and (e.get('traded_at') or '') > cutoff:
            new_traded.append(sid)
        if (e.get('trigger_hit_at') or '') > cutoff:
            recent_changes.append(f'  🎯 {sid} TRIGGER_HIT — {e.get("trigger_reason","?")[:80]}')

    lines = []
    if recent_changes:
        lines.extend(recent_changes[:5])
    if trigger_hit and not recent_changes:
        lines.append(f'  ⚡ Offen auf TRIGGER_HIT: {", ".join(trigger_hit[:5])}')
    # Summary
    by_status: dict = {}
    for e in theses.values():
        by_status[e.get('status', '?')] = by_status.get(e.get('status', '?'), 0) + 1
    summary = ' | '.join(f'{k}:{v}' for k, v in sorted(by_status.items()))
    lines.append(f'  📋 {summary}')
    return lines


# ── Block 4: Neue Kandidaten ─────────────────────────────────────────────
def block_new_candidates() -> list[str]:
    wl = _load_json(WATCHLIST)
    theses = wl.get('theses', {})
    cutoff = (datetime.now() - timedelta(hours=48)).isoformat(timespec='seconds')
    drafts = [
        (sid, e) for sid, e in theses.items()
        if e.get('status') == 'DRAFT' and (e.get('first_added') or '') > cutoff
    ]
    if not drafts:
        return ['  Keine neuen Kandidaten in den letzten 48h.']
    drafts.sort(key=lambda kv: -(kv[1].get('tqs') or 0))
    lines = []
    for sid, e in drafts[:5]:
        missing = ','.join((e.get('missing_fields') or [])[:3])
        lines.append(f'  📝 {sid} TQS={e.get("tqs",0):>3} — missing: {missing}')
    return lines


# ── Block 5: System-Status ───────────────────────────────────────────────
def block_status() -> list[str]:
    lines = []
    # Portfolio
    if DB.exists():
        try:
            c = sqlite3.connect(str(DB))
            row = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(entry_price*shares),0) "
                "FROM paper_portfolio WHERE status='OPEN'"
            ).fetchone()
            n, exposure = row or (0, 0)
            lines.append(f'  💼 Open: {n} Positionen, ~{exposure:,.0f}€ Exposure')
            c.close()
        except Exception:
            pass
    # Watchlist TQS-Verteilung
    wl = _load_json(WATCHLIST)
    theses = wl.get('theses', {})
    modes = {'FULL_AUTO': 0, 'SEMI_AUTO': 0, 'DRAFT': 0}
    for e in theses.values():
        if e.get('status') in ('ACTIVE_WATCH', 'TRIGGER_HIT'):
            modes[e.get('mode', 'DRAFT')] = modes.get(e.get('mode', 'DRAFT'), 0) + 1
    lines.append(
        f'  🎚 Watchlist aktiv: FULL_AUTO {modes["FULL_AUTO"]} | '
        f'SEMI_AUTO {modes["SEMI_AUTO"]} | DRAFT {modes["DRAFT"]}'
    )
    # Politische Risiko-Flags
    strats = _load_json(STRATS)
    flagged = [
        sid for sid, c in strats.items()
        if isinstance(c, dict) and c.get('political_risk_flag')
    ]
    if flagged:
        lines.append(f'  ⚠️  Political-Risk-Flag: {", ".join(flagged[:5])}')
    return lines


# ── Main ────────────────────────────────────────────────────────────────
def generate_phase22_block() -> str:
    parts = [
        '━━ 📋 GESTERN ERLEDIGT ━━',
        *block_yesterday(),
        '',
        '━━ 📅 HEUTE ANSTEHEND ━━',
        *block_today(),
        '',
        '━━ 👁️  WATCHLIST-UPDATES ━━',
        *block_watchlist(),
        '',
        '━━ 📝 NEUE KANDIDATEN ━━',
        *block_new_candidates(),
        '',
        '━━ 🎚  SYSTEM-STATUS ━━',
        *block_status(),
    ]
    return '\n'.join(parts)


if __name__ == '__main__':
    print(generate_phase22_block())
