#!/usr/bin/env python3
"""
Trade Journal — Automatisches Logging für den Trading Monitor
=============================================================
Wird von trading_monitor.py aufgerufen wenn ein Alert ausgelöst wird.
Schreibt in:
  - memory/trade-decisions.md  (Alert-Log, append)
  - memory/albert-accuracy.md  (Prognose-Tracking, update)

Autor: Albert 🎩 | v1.0 | 15.03.2026
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path('/data/.openclaw/workspace')
DECISIONS_PATH = WORKSPACE / 'memory' / 'trade-decisions.md'
ACCURACY_PATH = WORKSPACE / 'memory' / 'albert-accuracy.md'
STRATEGIES_PATH = WORKSPACE / 'memory' / 'strategien.md'


# ─── Hilfsfunktionen ─────────────────────────────────────────────────

def _load_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''


def _write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def _now_berlin() -> str:
    """Gibt aktuelle Zeit als YYYY-MM-DD HH:MM zurück (UTC+1 approximiert)."""
    from datetime import timedelta
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    return now.strftime('%Y-%m-%d %H:%M')


# ─── Trade Decisions Log ─────────────────────────────────────────────

def log_alert(alert_data: dict):
    """
    Schreibt einen Alert-Eintrag in memory/trade-decisions.md.

    alert_data keys:
      ticker      str   "MSFT"
      name        str   "Microsoft"
      alert_type  str   "Stop-Warnung" | "Stop-Breach" | "Trailing-Signal" |
                         "Watchlist-Entry" | "Target-Reached"
      price_eur   float Aktueller Kurs in EUR
      entry_eur   float Entry-Kurs in EUR (0 wenn unbekannt)
      pnl_pct     float P&L in % (0.0 wenn N/A)
      stop_eur    float|None Stop-Kurs
      vix         float|None VIX-Wert
      wti         float|None WTI-Preis in USD
      conviction  dict|None  Ergebnis von conviction_score() (optional)
      strategy    str   "S1" / "S2" / ... / "S7" (optional, wird auto-erkannt wenn fehlt)
    """
    ts = _now_berlin()
    ticker = alert_data.get('ticker', '?')
    name = alert_data.get('name', ticker)
    alert_type = alert_data.get('alert_type', 'Alert')
    price_eur = alert_data.get('price_eur', 0.0)
    entry_eur = alert_data.get('entry_eur', 0.0)
    pnl_pct = alert_data.get('pnl_pct', 0.0)
    stop_eur = alert_data.get('stop_eur')
    vix = alert_data.get('vix')
    wti = alert_data.get('wti')
    conviction = alert_data.get('conviction')

    # Strategie auto-erkennen wenn nicht mitgegeben
    strategy = alert_data.get('strategy') or _detect_strategy(ticker)

    # Kontext-Zeile
    kontext_parts = []
    if vix is not None:
        kontext_parts.append(f"VIX: {vix:.1f}")
    if wti is not None:
        kontext_parts.append(f"WTI: ${wti:.2f}")
    if conviction:
        score = conviction.get('score', '?')
        rec = conviction.get('recommendation', '')
        kontext_parts.append(f"Conviction: {score}/100 [{rec}]")
    kontext_str = ' | '.join(kontext_parts) if kontext_parts else 'Keine Macro-Daten'

    # P&L-String
    pnl_sign = '+' if pnl_pct >= 0 else ''
    pnl_str = f"{pnl_sign}{pnl_pct:.1f}%"

    # Preis-Strings
    price_str = f"{price_eur:.2f}€".replace('.', ',')
    entry_str = f"{entry_eur:.2f}€".replace('.', ',') if entry_eur else "—"
    stop_str = f"{stop_eur:.2f}€".replace('.', ',') if stop_eur else "—"

    entry_text = f"""
### {ts} — {name} ({ticker}) — {alert_type}
**Kurs:** {price_str} | **Entry:** {entry_str} | **P&L:** {pnl_str}
**Alert:** {alert_type} | **Stop:** {stop_str}
**Strategie:** {strategy}
**Kontext:** {kontext_str}

"""

    # Append an trade-decisions.md
    existing = _load_text(DECISIONS_PATH)
    if not existing:
        existing = "# Trade Decisions — Alert-Log\n\n"

    # Vor dem letzten "*Dieses Log...*"-Footer einfügen wenn vorhanden
    footer_marker = '*Dieses Log wird bei jeder'
    if footer_marker in existing:
        insert_pos = existing.rfind('\n---\n')
        if insert_pos == -1:
            insert_pos = existing.rfind(footer_marker)
        new_content = existing[:insert_pos] + entry_text + existing[insert_pos:]
    else:
        new_content = existing.rstrip() + '\n' + entry_text

    _write_text(DECISIONS_PATH, new_content)

    # Accuracy updaten wenn Exit-Signal
    if alert_type in ('Stop-Breach', 'Target-Reached'):
        _close_accuracy_entry(ticker, name, price_eur, pnl_pct, alert_type, ts[:10])


def _detect_strategy(ticker: str) -> str:
    """Versucht die Strategie anhand des Tickers zu erraten."""
    mapping = {
        'EQNR': 'S1', 'DR0.DE': 'S1', 'ISPA.DE': 'S1', 'AG': 'S1',
        'A2QQ9R': 'S1/S6', 'A3D42Y': 'S1',
        'RHM.DE': 'S2',
        'NVDA': 'S3', 'MSFT': 'S3', 'PLTR': 'S3',
        'ISPA': 'S4', 'GLD': 'S4',
        'RIO.L': 'S5', 'BHP.L': 'S5',
        'A14WU5': 'S3', 'A2DWAW': 'S7',
        'BAYN.DE': 'S2',
    }
    return mapping.get(ticker, 'S?')


# ─── Accuracy Tracking ───────────────────────────────────────────────

def _parse_accuracy(text: str) -> dict:
    """Parst die Accuracy-Datei in ein strukturiertes Dict."""
    result = {
        'header': '',
        'open_rows': [],      # list of dicts
        'closed_rows': [],    # list of dicts
        'raw': text,
    }
    if not text or text.strip() == '':
        return result

    # Header (alles vor der Offene-Prognosen-Tabelle)
    open_section = re.search(r'## Offene Prognosen', text)
    if open_section:
        result['header'] = text[:open_section.start()]

    # Offene Prognosen Zeilen parsen
    open_match = re.search(
        r'## Offene Prognosen.*?\|.*?\|.*?\n((?:\|.*\n)*)',
        text, re.DOTALL
    )
    if open_match:
        for row in open_match.group(1).split('\n'):
            row = row.strip()
            if row.startswith('|') and '---' not in row and row != '|':
                cols = [c.strip() for c in row.split('|') if c.strip()]
                if len(cols) >= 7:
                    result['open_rows'].append({
                        'datum': cols[0],
                        'aktie': cols[1],
                        'richtung': cols[2],
                        'entry': cols[3],
                        'ziel': cols[4],
                        'stop': cols[5],
                        'status': cols[6],
                        'ticker': _extract_ticker(cols[1]),
                    })

    # Abgeschlossene Prognosen
    closed_match = re.search(
        r'## Abgeschlossene Prognosen.*?\|.*?\|.*?\n((?:\|.*\n)*)',
        text, re.DOTALL
    )
    if closed_match:
        for row in closed_match.group(1).split('\n'):
            row = row.strip()
            if row.startswith('|') and '---' not in row and row != '|':
                cols = [c.strip() for c in row.split('|') if c.strip()]
                if len(cols) >= 7:
                    result['closed_rows'].append({
                        'datum': cols[0],
                        'aktie': cols[1],
                        'richtung': cols[2],
                        'entry': cols[3],
                        'exit': cols[4],
                        'pnl': cols[5],
                        'result': cols[6],
                    })

    return result


def _extract_ticker(aktie_str: str) -> str:
    """Extrahiert Ticker aus 'Nvidia (NVDA)' → 'NVDA'."""
    match = re.search(r'\(([^)]+)\)', aktie_str)
    return match.group(1) if match else aktie_str


def _build_accuracy_file(open_rows: list, closed_rows: list) -> str:
    """Baut die komplette accuracy.md neu auf."""
    # Statistik berechnen
    total = len(closed_rows)
    wins = sum(1 for r in closed_rows if '✅' in r.get('result', ''))
    losses = sum(1 for r in closed_rows if '❌' in r.get('result', ''))
    win_pct = (wins / total * 100) if total > 0 else 0

    # Avg Win/Loss berechnen
    win_pnls = []
    loss_pnls = []
    for r in closed_rows:
        pnl_str = r.get('pnl', '0%').replace('%', '').replace('+', '').replace(',', '.')
        try:
            val = float(pnl_str)
            if val >= 0:
                win_pnls.append(val)
            else:
                loss_pnls.append(abs(val))
        except ValueError:
            pass

    avg_win = f"+{sum(win_pnls)/len(win_pnls):.1f}%" if win_pnls else "—"
    avg_loss = f"-{sum(loss_pnls)/len(loss_pnls):.1f}%" if loss_pnls else "—"
    ratio = f"{sum(win_pnls)/len(win_pnls) / (sum(loss_pnls)/len(loss_pnls)):.1f}:1" if win_pnls and loss_pnls else "—"

    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    # Offene Prognosen-Tabelle
    open_table = "| Datum | Aktie | Richtung | Entry | Ziel | Stop | Status |\n"
    open_table += "|---|---|---|---|---|---|---|\n"
    for r in open_rows:
        open_table += f"| {r['datum']} | {r['aktie']} | {r['richtung']} | {r['entry']} | {r['ziel']} | {r['stop']} | {r['status']} |\n"

    # Abgeschlossene Prognosen-Tabelle
    closed_table = "| Datum | Aktie | Richtung | Entry | Exit | P&L | ✅/❌ |\n"
    closed_table += "|---|---|---|---|---|---|---|\n"
    for r in closed_rows:
        closed_table += f"| {r['datum']} | {r['aktie']} | {r['richtung']} | {r['entry']} | {r['exit']} | {r['pnl']} | {r['result']} |\n"

    content = f"""# Albert Accuracy Report
*Letzte Aktualisierung: {now}*

Tracking aller Empfehlungen und Trade-Entscheidungen. Wird automatisch von trading_monitor.py aktualisiert.

---

## Offene Prognosen

{open_table}
## Abgeschlossene Prognosen

{closed_table}
## Statistik

- **Gesamt:** {total} Trades | ✅ {wins} ({win_pct:.0f}%) | ❌ {losses} ({100-win_pct:.0f}%)
- **Avg Win:** {avg_win} | **Avg Loss:** {avg_loss} | **Win/Loss Ratio:** {ratio}
- **Offene Positionen:** {len(open_rows)}
"""
    return content


def add_open_position(ticker: str, name: str, date: str, direction: str,
                      entry_eur: float, target_eur: float | None,
                      stop_eur: float | None):
    """
    Fügt eine neue offene Position zur Accuracy-Tabelle hinzu.
    Wird aufgerufen wenn Victor eine neue Position eröffnet.
    """
    text = _load_text(ACCURACY_PATH)
    parsed = _parse_accuracy(text)

    # Prüfen ob bereits vorhanden
    for row in parsed['open_rows']:
        if row.get('ticker') == ticker:
            return  # Bereits eingetragen

    entry_str = f"{entry_eur:.2f}€".replace('.', ',')
    target_str = f"{target_eur:.0f}€" if target_eur else "—"
    stop_str = f"{stop_eur:.2f}€".replace('.', ',') if stop_eur else "—"

    new_row = {
        'datum': date,
        'aktie': f"{name} ({ticker})",
        'richtung': 'LONG',
        'entry': entry_str,
        'ziel': target_str,
        'stop': stop_str,
        'status': '⏳ Offen',
        'ticker': ticker,
    }
    parsed['open_rows'].append(new_row)
    _write_text(ACCURACY_PATH, _build_accuracy_file(parsed['open_rows'], parsed['closed_rows']))


def _close_accuracy_entry(ticker: str, name: str, exit_price_eur: float,
                           pnl_pct: float, reason: str, date: str):
    """
    Schließt eine offene Position und verschiebt sie in Abgeschlossene Prognosen.
    """
    text = _load_text(ACCURACY_PATH)
    if not text:
        return

    parsed = _parse_accuracy(text)

    # Offene Position finden
    found = None
    remaining_open = []
    for row in parsed['open_rows']:
        if row.get('ticker') == ticker or ticker in row.get('aktie', ''):
            found = row
        else:
            remaining_open.append(row)

    if not found:
        return

    pnl_sign = '+' if pnl_pct >= 0 else ''
    result_icon = '✅' if pnl_pct >= 0 else '❌'
    exit_str = f"{exit_price_eur:.2f}€".replace('.', ',')

    closed_row = {
        'datum': f"{found['datum']}–{date[5:]}",  # "04.03–15.03"
        'aktie': found['aktie'],
        'richtung': found['richtung'],
        'entry': found['entry'],
        'exit': exit_str,
        'pnl': f"{pnl_sign}{pnl_pct:.1f}%",
        'result': result_icon,
    }
    parsed['closed_rows'].append(closed_row)
    parsed['open_rows'] = remaining_open

    _write_text(ACCURACY_PATH, _build_accuracy_file(parsed['open_rows'], parsed['closed_rows']))


# ─── Bulk-Import der Bestands-Trades ────────────────────────────────

def import_historical_trades():
    """
    Trägt alle bisherigen Trades rückwirkend in albert-accuracy.md ein.
    Einmalig ausführen — idempotent (prüft ob bereits vorhanden).
    """
    text = _load_text(ACCURACY_PATH)
    parsed = _parse_accuracy(text)

    existing_tickers = {r.get('ticker', '') for r in parsed['open_rows']}
    existing_closed = {r.get('aktie', '') for r in parsed['closed_rows']}

    # ─── Offene Positionen ───────────────────────────────────────────
    open_positions = [
        # (ticker, name, datum, entry_eur, target_eur, stop_eur)
        ('NVDA',    'Nvidia',                       '25.02.', 167.88, None,    None),
        ('MSFT',    'Microsoft',                    '04.03.', 351.85, 387.00,  338.00),
        ('PLTR',    'Palantir',                     '04.03.', 132.11, 159.00,  127.00),
        ('EQNR',    'Equinor ASA',                  '04.03.', 27.04,  31.00,   25.00),
        ('BAYN.DE', 'Bayer AG',                     '10.03.', 39.95,  44.00,   38.00),
        ('RIO.L',   'Rio Tinto',                    '09.03.', 76.92,  85.00,   73.00),
        ('RHM.DE',  'Rheinmetall AG (2)',            '12.03.', 1570.00, 1750.00, 1520.00),
        ('A2QQ9R',  'Invesco Solar Energy ETF',     '13.03.', 22.40,  28.00,   None),
        ('A3D42Y',  'VanEck Oil Services ETF',      '13.03.', 27.90,  None,    24.00),
        ('A14WU5',  'L&G Cyber Security ETF',       '13.03.', 28.80,  None,    25.95),
        ('A2DWAW',  'iShares Biotech ETF',          '13.03.', 7.00,   None,    6.30),
    ]

    added_open = 0
    for ticker, name, datum, entry, target, stop in open_positions:
        if ticker not in existing_tickers:
            entry_str = f"{entry:.2f}€".replace('.', ',')
            target_str = f"{target:.0f}€" if target else "—"
            stop_str = f"{stop:.2f}€".replace('.', ',') if stop else "—"
            parsed['open_rows'].append({
                'datum': datum,
                'aktie': f"{name} ({ticker})",
                'richtung': 'LONG',
                'entry': entry_str,
                'ziel': target_str,
                'stop': stop_str,
                'status': '⏳ Offen',
                'ticker': ticker,
            })
            added_open += 1

    # ─── Abgeschlossene Trades ───────────────────────────────────────
    closed_trades = [
        # (datum, aktie_str, richtung, entry_str, exit_str, pnl_str, result)
        ('09.03–11.03', 'Rheinmetall AG (RHM.DE)',      'LONG', '1.635€',  '~1.563€',  '-4,4%', '❌'),
        ('04.03–10.03', 'Deutsche Rohstoff AG (DR0.DE)','LONG', '76,35€',  '~77,00€',  '+0,85%','✅'),
        ('10.03–10.03', 'Deutsche Rohstoff AG (DR0.DE)','LONG', '82,15€',  '~79,00€',  '-3,8%', '❌'),
    ]

    added_closed = 0
    for datum, aktie, richtung, entry, exit_p, pnl, result in closed_trades:
        key = f"{datum}_{aktie}"
        if key not in existing_closed and not any(
            r.get('datum') == datum and aktie in r.get('aktie', '')
            for r in parsed['closed_rows']
        ):
            parsed['closed_rows'].append({
                'datum': datum,
                'aktie': aktie,
                'richtung': richtung,
                'entry': entry,
                'exit': exit_p,
                'pnl': pnl,
                'result': result,
            })
            added_closed += 1

    _write_text(ACCURACY_PATH, _build_accuracy_file(parsed['open_rows'], parsed['closed_rows']))
    print(f"[trade_journal] Import: {added_open} offene + {added_closed} abgeschlossene Trades eingetragen.")
    return added_open + added_closed


# ─── Test / Demo ─────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=== Trade Journal — Selbsttest ===\n")

    # 1. Historische Trades importieren
    print("1. Importiere historische Trades...")
    n = import_historical_trades()
    print(f"   → {n} Einträge importiert\n")

    # 2. Dummy-Alert loggen
    print("2. Teste log_alert() mit Dummy-Alert...")
    dummy_alert = {
        'ticker': 'MSFT',
        'name': 'Microsoft',
        'alert_type': 'Stop-Warnung',
        'price_eur': 340.50,
        'entry_eur': 351.85,
        'pnl_pct': -3.22,
        'stop_eur': 338.00,
        'vix': 26.4,
        'wti': 91.20,
        'conviction': {
            'score': 45,
            'recommendation': 'Schwaches Signal — Vorsicht',
            'factors': {'vix': -10, 'stop_abstand': -20, 'strategie': 0, 'trend': 0, 'volume': 0}
        },
        'strategy': 'S3',
    }
    log_alert(dummy_alert)
    print("   → Alert geloggt in memory/trade-decisions.md\n")

    # 3. Accuracy-Datei anzeigen
    print("3. Aktuelle albert-accuracy.md:")
    print("-" * 60)
    content = ACCURACY_PATH.read_text(encoding='utf-8') if ACCURACY_PATH.exists() else "(leer)"
    print(content[:1500])
    print("=" * 60)
    print("Selbsttest abgeschlossen. ✅")
