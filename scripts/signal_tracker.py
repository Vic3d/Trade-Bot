#!/usr/bin/env python3
"""
Signal Tracker — Paperclip-basierter Feedback Loop
====================================================
1. Überwacht Lead-Indikatoren (lag_knowledge.json)
2. Wenn Signal → Paperclip Issue erstellen (TRA-X)
3. Validator-Agent wird nach lag_hours getriggert → prüft Outcome
4. Accuracy-Datenbank wächst automatisch

Läuft alle 30 Min via OpenClaw Cron.
"""

import json, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path('/data/.openclaw/workspace')
LAG_DB    = WORKSPACE / 'data/lag_knowledge.json'
STATE     = WORKSPACE / 'memory/signal-tracker-state.json'
SIGNALS_JSON = WORKSPACE / 'data/signals.json'

PAPERCLIP_URL = "http://127.0.0.1:53476/api"
COMPANY_ID    = "9147c9ab-f487-40ed-a67b-c41f0a8d4fba"
PROJECT_ID    = "a23e17b9-3463-4bf5-adfd-47e5bcad5399"
VALIDATOR_ID  = "b3c2ccf0-0475-43fd-a330-d403aaa16972"
GOAL_ID       = "b7b57e54-4289-4e3f-912f-d7b304fb6658"


# ─── Paperclip API ────────────────────────────────────────────────────

def pc_post(path, data):
    url = f"{PAPERCLIP_URL}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read())

def pc_patch(path, data):
    url = f"{PAPERCLIP_URL}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="PATCH")
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read())

def pc_get(path):
    req = urllib.request.Request(f"{PAPERCLIP_URL}{path}")
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read())


# ─── Yahoo Finance ────────────────────────────────────────────────────

def yahoo_price(ticker):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        meta = d['chart']['result'][0]['meta']
        return meta['regularMarketPrice'], meta.get('chartPreviousClose', meta['regularMarketPrice'])
    except Exception as e:
        print(f"Yahoo-Fehler {ticker}: {e}")
        return None, None


# ─── Brent-WTI Spread ────────────────────────────────────────────────

def brent_wti_spread():
    brent, _ = yahoo_price("BZ=F")
    wti, _   = yahoo_price("CL=F")
    if brent and wti:
        return round(brent - wti, 2)
    return None


# ─── Signal Detection ────────────────────────────────────────────────

def detect_signals(lag_db, state):
    """Prüft alle Lead-Indikatoren auf aktive Signale."""
    signals = []
    fired_today = state.get('fired_today', {})
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    for pair_id, pair in lag_db.get('pairs', {}).items():
        if pair_id in fired_today.get(today, []):
            continue  # Heute bereits gesendet

        lead = pair['lead_ticker']
        direction = pair['direction']
        threshold = pair.get('threshold_pct')

        # Sonderfall: Computed signals
        if lead == 'COMPUTED_BRENT_WTI_SPREAD':
            spread = brent_wti_spread()
            if spread and spread > pair.get('threshold_pct', 10):
                signals.append({
                    'pair_id': pair_id,
                    'pair': pair,
                    'signal_value': f"Spread: ${spread:.2f}",
                    'signal_pct': None,
                    'lead_price': spread,
                    'lag_price_now': None
                })
            continue

        if lead == 'LIVEUAMAP_IRAN':
            # Wird separat durch newswire_analyst behandelt
            continue

        # Yahoo-basierte Leads
        if not threshold:
            continue

        price_now, price_prev = yahoo_price(lead)
        if not price_now or not price_prev:
            continue

        chg_pct = (price_now - price_prev) / price_prev * 100

        triggered = False
        if direction in ('same', 'bullish') and chg_pct <= -threshold:
            triggered = True  # Lead fällt stark → Lag folgt
        elif direction == 'inverse' and chg_pct >= threshold:
            triggered = True  # VIX steigt stark → Tech fällt
        elif direction == 'same' and chg_pct >= threshold:
            triggered = True  # Lead steigt stark → Lag folgt

        if triggered:
            lag_price, _ = yahoo_price(pair['lag_ticker'])
            signals.append({
                'pair_id': pair_id,
                'pair': pair,
                'signal_value': f"{chg_pct:+.1f}%",
                'signal_pct': chg_pct,
                'lead_price': price_now,
                'lag_price_now': lag_price
            })

    return signals


# ─── Paperclip Issue erstellen ────────────────────────────────────────

def create_signal_issue(signal, lag_db):
    pair = signal['pair']
    pair_id = signal['pair_id']
    accuracy = pair.get('accuracy_pct')
    samples  = pair.get('sample_count', 0)
    min_samples = lag_db.get('min_samples_to_trust', 20)
    min_acc     = lag_db.get('min_accuracy_to_trade', 60.0)

    now_utc = datetime.now(timezone.utc)
    lag_h   = pair.get('lag_hours', 6)
    check_at = now_utc.strftime(f'in {lag_h}h (~%H:%M UTC + {lag_h}h)')

    # Confidence-Level bestimmen
    if samples < min_samples:
        confidence = f"🔬 AUFBAU ({samples}/{min_samples} Samples — noch nicht handelbar)"
        priority = "low"
    elif accuracy and accuracy >= min_acc:
        confidence = f"✅ VERTRAUENSWÜRDIG ({accuracy:.0f}% / {samples} Samples)"
        priority = "high"
    else:
        confidence = f"⚠️ SCHWACH ({accuracy:.0f}% / {samples} Samples — unter {min_acc}% Minimum)"
        priority = "medium"

    title = f"Signal: {pair['lead_name']} → {pair['lag_name']} ({signal['signal_value']})"

    description = f"""## Lead-Lag Signal detektiert

**Lead:** {pair['lead_name']} (`{pair['lead_ticker']}`) — {signal['signal_value']}
**Lag:** {pair['lag_name']} (`{pair['lag_ticker']}`) — aktuell: {signal['lag_price_now'] or 'n/a'}
**Erwartete Lag-Zeit:** {lag_h}h
**Richtung:** {pair['direction']}
**Confidence:** {confidence}

**Theorie:** {pair['description']}

---

### Prognose
In ~{lag_h}h sollte `{pair['lag_ticker']}` sich in Richtung **{pair['direction']}** bewegen.
Validator prüft das Outcome automatisch um {check_at}.

### Was tun?
{"🚫 Noch nicht handelbar — Daten sammeln." if samples < min_samples else
 f"{'🟢 Setup prüfen — Confidence hoch genug.' if (accuracy or 0) >= min_acc else '🔴 Nicht handeln — Accuracy zu niedrig.'}"}

---
*Pair ID: {pair_id} | Erstellt: {now_utc.strftime('%Y-%m-%d %H:%M UTC')}*
*Validator prüft in {lag_h}h automatisch.*"""

    issue = pc_post(f"/companies/{COMPANY_ID}/issues", {
        "title": title,
        "description": description,
        "projectId": PROJECT_ID,
        "goalId": GOAL_ID,
        "priority": priority,
        "status": "todo"
    })

    print(f"  📋 Issue erstellt: {issue['identifier']} — {title}")
    return issue


# ─── Outcome-Check (Validator-Rolle) ─────────────────────────────────

def check_pending_outcomes(state, lag_db):
    """Prüft Issues deren lag_hours abgelaufen sind."""
    pending = state.get('pending_outcomes', [])
    now = datetime.now(timezone.utc).timestamp()
    still_pending = []

    for entry in pending:
        if now < entry['check_at_ts']:
            still_pending.append(entry)
            continue

        # Zeit abgelaufen → Outcome prüfen
        pair_id   = entry['pair_id']
        issue_id  = entry['issue_id']
        pair      = lag_db['pairs'].get(pair_id)
        if not pair:
            continue

        lag_ticker = pair['lag_ticker']
        if lag_ticker == 'COMPUTED_BRENT_WTI_SPREAD':
            current, _ = brent_wti_spread(), None
        else:
            current, _ = yahoo_price(lag_ticker)

        if not current:
            still_pending.append(entry)  # Retry
            continue

        entry_price = entry.get('lag_price_at_signal')
        if not entry_price:
            still_pending.append(entry)
            continue

        actual_chg  = (current - entry_price) / entry_price * 100
        direction   = pair['direction']
        lag_h       = pair.get('lag_hours', 6)

        # Bewertung
        if direction == 'inverse':
            correct = actual_chg < -1.0
        elif direction in ('same', 'bullish'):
            correct = actual_chg < -1.0 if entry.get('signal_pct', 0) < 0 else actual_chg > 1.0
        else:
            correct = abs(actual_chg) > 1.0

        result_emoji = "✅" if correct else "❌"
        outcome_text = f"""## Outcome nach {lag_h}h

**{result_emoji} {'KORREKT' if correct else 'FALSCH'}**

| | Bei Signal | Jetzt ({lag_h}h später) | Veränderung |
|---|---|---|---|
| {pair['lag_name']} | {entry_price:.2f} | {current:.2f} | {actual_chg:+.1f}% |

**Prognose war:** {direction} Bewegung in {lag_h}h
**Tatsächlich:** {actual_chg:+.1f}%
**Urteil:** {'Prognose bestätigt ✅' if correct else 'Prognose nicht bestätigt ❌'}

---
*Accuracy-Datenbank wird automatisch aktualisiert.*"""

        # Kommentar auf Issue posten
        try:
            pc_post(f"/issues/{issue_id}/comments", {"body": outcome_text})
            # Issue schließen
            pc_patch(f"/issues/{issue_id}", {"status": "done" if correct else "cancelled"})
            print(f"  {result_emoji} Outcome für {issue_id[:8]}: {pair_id} → {actual_chg:+.1f}%")
        except Exception as e:
            print(f"  Paperclip-Fehler beim Outcome: {e}")
            # Trotzdem signals.json updaten
        
        # → signals.json updaten
        update_signal_outcome(issue_id, 'WIN' if correct else 'LOSS', round(actual_chg, 2), current)

        # Accuracy updaten
        pair['sample_count'] = pair.get('sample_count', 0) + 1
        pair['wins']   = pair.get('wins', 0) + (1 if correct else 0)
        pair['losses'] = pair.get('losses', 0) + (0 if correct else 1)
        pair['accuracy_pct'] = round(pair['wins'] / pair['sample_count'] * 100, 1)

    state['pending_outcomes'] = still_pending
    return state, lag_db


# ─── Signals JSON (Dashboard-Feed) ───────────────────────────────────

def load_signals_json():
    if SIGNALS_JSON.exists():
        return json.loads(SIGNALS_JSON.read_text())
    return {"signals": [], "stats": {"total": 0, "wins": 0, "losses": 0, "pending": 0}, "updated": None}

def save_signals_json(data):
    data['updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    # Stats berechnen
    sigs = data['signals']
    data['stats'] = {
        "total": len(sigs),
        "wins": sum(1 for s in sigs if s.get('outcome') == 'WIN'),
        "losses": sum(1 for s in sigs if s.get('outcome') == 'LOSS'),
        "pending": sum(1 for s in sigs if s.get('outcome') == 'PENDING'),
        "accuracy_pct": round(
            sum(1 for s in sigs if s.get('outcome') == 'WIN') / max(1, sum(1 for s in sigs if s.get('outcome') in ('WIN','LOSS'))) * 100, 1
        ) if any(s.get('outcome') in ('WIN','LOSS') for s in sigs) else None
    }
    SIGNALS_JSON.write_text(json.dumps(data, indent=2))

def append_signal(signal_entry):
    data = load_signals_json()
    data['signals'].insert(0, signal_entry)  # Neueste zuerst
    # Max 100 Signale behalten
    data['signals'] = data['signals'][:100]
    save_signals_json(data)

def update_signal_outcome(issue_id, outcome, actual_chg, lag_price_now):
    data = load_signals_json()
    for s in data['signals']:
        if s.get('issue_id') == issue_id:
            s['outcome'] = outcome
            s['actual_change_pct'] = actual_chg
            s['lag_price_after'] = lag_price_now
            s['resolved_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            break
    save_signals_json(data)

def push_signals_to_git():
    """Auto-commit + push signals.json damit Vercel es sieht."""
    import subprocess
    try:
        subprocess.run(['git', 'add', str(SIGNALS_JSON)], cwd=str(WORKSPACE), capture_output=True, timeout=10)
        result = subprocess.run(
            ['git', 'commit', '-m', f'📡 Signal update {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} [skip ci]'],
            cwd=str(WORKSPACE), capture_output=True, timeout=10
        )
        if result.returncode == 0:
            subprocess.run(['git', 'push'], cwd=str(WORKSPACE), capture_output=True, timeout=30)
            print("  📤 signals.json gepusht → Vercel")
    except Exception as e:
        print(f"  Git push fehlgeschlagen: {e}")


# ─── Main ────────────────────────────────────────────────────────────

def main():
    lag_db = json.loads(LAG_DB.read_text())
    state  = json.loads(STATE.read_text()) if STATE.exists() else {}
    today  = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    print(f"[{datetime.now(timezone.utc).strftime('%H:%M UTC')}] Signal Tracker läuft...")

    # 1. Pending Outcomes prüfen
    state, lag_db = check_pending_outcomes(state, lag_db)

    # 2. Neue Signale detektieren
    signals = detect_signals(lag_db, state)
    print(f"  Signale detektiert: {len(signals)}")

    for sig in signals:
        pair_id = sig['pair_id']
        pair = sig['pair']
        issue = create_signal_issue(sig, lag_db)

        # In pending_outcomes eintragen
        import time
        lag_h = pair['lag_hours']
        if 'pending_outcomes' not in state:
            state['pending_outcomes'] = []
        state['pending_outcomes'].append({
            'pair_id':              pair_id,
            'issue_id':             issue['id'],
            'lag_price_at_signal':  sig.get('lag_price_now'),
            'signal_pct':           sig.get('signal_pct'),
            'check_at_ts':          time.time() + lag_h * 3600
        })

        # fired_today tracken
        if 'fired_today' not in state:
            state['fired_today'] = {}
        state['fired_today'].setdefault(today, []).append(pair_id)

        # → signals.json für Dashboard
        append_signal({
            'pair_id': pair_id,
            'lead_ticker': pair['lead_ticker'],
            'lead_name': pair['lead_name'],
            'lag_ticker': pair['lag_ticker'],
            'lag_name': pair['lag_name'],
            'signal_value': sig['signal_value'],
            'signal_pct': sig.get('signal_pct'),
            'lead_price': sig.get('lead_price'),
            'lag_price_at_signal': sig.get('lag_price_now'),
            'lag_hours': lag_h,
            'direction': pair['direction'],
            'outcome': 'PENDING',
            'issue_id': issue['id'],
            'issue_key': issue.get('identifier', '?'),
            'confidence': f"{pair.get('sample_count',0)}/{lag_db.get('min_samples_to_trust',20)} samples",
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        })

    # 3. State + Lag-DB speichern
    STATE.write_text(json.dumps(state, indent=2))
    LAG_DB.write_text(json.dumps(lag_db, indent=2))

    if not signals:
        print("  KEIN_SIGNAL")
    else:
        print(f"  {len(signals)} Issue(s) in Paperclip erstellt.")
        push_signals_to_git()


if __name__ == '__main__':
    main()
