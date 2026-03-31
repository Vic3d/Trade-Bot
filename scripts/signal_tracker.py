#!/usr/bin/env python3
"""
Signal Tracker v2 — Lead-Lag Feedback Loop (SQLite-basiert)
============================================================
1. Liest Lead-Lag-Paare aus data/lag_knowledge.json
2. Erkennt Signale (Yahoo Finance Kursbewegungen, Spreads)
3. Loggt Signal + Prognose in trading.db → signals Tabelle
4. Prüft nach lag_hours ob Prognose stimmte → Outcome WIN/LOSS
5. Aktualisiert Accuracy in lag_knowledge.json
6. CEO liest signals-Tabelle für Lead-Lag-Intelligence

Läuft alle 30 Min via OpenClaw Cron.
Keine externen Dependencies — nur stdlib + sqlite3.
"""

import json
import sqlite3
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

WORKSPACE = Path('/data/.openclaw/workspace')
LAG_DB = WORKSPACE / 'data/lag_knowledge.json'
STATE = WORKSPACE / 'memory/signal-tracker-state.json'
DB_PATH = WORKSPACE / 'data/trading.db'

# Cooldown: gleiches Paar nicht öfter als alle 6h
SIGNAL_COOLDOWN_HOURS = 6
# Minimum Kursänderung für Outcome-Bewertung
OUTCOME_THRESHOLD_PCT = 0.5


# ─── DB ───────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Ensure table has all needed columns
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_id TEXT NOT NULL,
            lead_ticker TEXT,
            lag_ticker TEXT,
            signal_value TEXT,
            lead_price REAL,
            lag_price_at_signal REAL,
            lag_price_at_check REAL,
            change_pct REAL,
            outcome TEXT DEFAULT 'PENDING',
            regime_at_signal TEXT,
            vix_at_signal REAL,
            accuracy_at_time REAL,
            check_after_ts REAL,
            direction TEXT,
            lag_hours REAL,
            lead_name TEXT,
            lag_name TEXT,
            created_at TEXT,
            checked_at TEXT
        )
    """)
    # Add columns if missing (backward compat)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(signals)").fetchall()}
    new_cols = {
        'check_after_ts': 'REAL',
        'direction': 'TEXT',
        'lag_hours': 'REAL',
        'lead_name': 'TEXT',
        'lag_name': 'TEXT',
    }
    for col, ctype in new_cols.items():
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {col} {ctype}")
            except Exception:
                pass
    conn.commit()
    return conn


# ─── Yahoo Finance ────────────────────────────────────────────────────

def yahoo_price(ticker):
    """Holt aktuellen Kurs + Vortagesschluss von Yahoo Finance."""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
        meta = d['chart']['result'][0]['meta']
        return meta['regularMarketPrice'], meta.get('chartPreviousClose', meta['regularMarketPrice'])
    except Exception as e:
        return None, None


def brent_wti_spread():
    """Berechnet Brent-WTI Spread."""
    brent, _ = yahoo_price("BZ=F")
    wti, _ = yahoo_price("CL=F")
    if brent and wti:
        return round(brent - wti, 2)
    return None


def get_vix():
    """Holt aktuellen VIX."""
    price, _ = yahoo_price("^VIX")
    return price


def get_regime(vix):
    """Einfache Regime-Klassifikation."""
    if not vix:
        return 'UNKNOWN'
    if vix < 18:
        return 'BULL'
    elif vix < 25:
        return 'NEUTRAL'
    elif vix < 32:
        return 'RISK_OFF'
    return 'CRASH'


# ─── Signal Detection ────────────────────────────────────────────────

def detect_signals(lag_db, state, conn):
    """Prüft alle Lead-Indikatoren auf aktive Signale."""
    signals = []
    now = time.time()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # Cooldown: Signale der letzten N Stunden aus DB laden
    cooldown_cutoff = (datetime.now(timezone.utc) - timedelta(hours=SIGNAL_COOLDOWN_HOURS)).isoformat()
    recent_pairs = {r['pair_id'] for r in conn.execute(
        "SELECT DISTINCT pair_id FROM signals WHERE created_at > ?", (cooldown_cutoff,)
    ).fetchall()}

    for pair_id, pair in lag_db.get('pairs', {}).items():
        if pair_id in recent_pairs:
            continue  # Cooldown aktiv

        lead = pair['lead_ticker']
        direction = pair['direction']
        threshold = pair.get('threshold_pct')
        lag_h = pair.get('lag_hours', 6)

        # Sonderfall: Computed Brent-WTI Spread
        if lead == 'COMPUTED_BRENT_WTI_SPREAD':
            spread = brent_wti_spread()
            if spread is not None and threshold and spread > threshold:
                lag_price, _ = yahoo_price(pair['lag_ticker'])
                signals.append({
                    'pair_id': pair_id,
                    'pair': pair,
                    'signal_value': f"Spread: ${spread:.2f}",
                    'signal_pct': None,
                    'lead_price': spread,
                    'lag_price_now': lag_price,
                })
            continue

        # Sonderfall: liveuamap-basierte Signale → skip (handled by geo scanner)
        if lead == 'LIVEUAMAP_IRAN':
            continue

        # Yahoo-basierte Lead-Signale
        if not threshold:
            continue

        price_now, price_prev = yahoo_price(lead)
        if not price_now or not price_prev or price_prev == 0:
            continue

        chg_pct = (price_now - price_prev) / price_prev * 100

        triggered = False
        if direction == 'inverse' and abs(chg_pct) >= threshold:
            triggered = True
        elif direction in ('same', 'bullish') and abs(chg_pct) >= threshold:
            triggered = True
        elif direction == 'bullish_when_spread_high':
            # Special case for spread-based
            continue

        if triggered:
            lag_price, _ = yahoo_price(pair['lag_ticker'])
            signals.append({
                'pair_id': pair_id,
                'pair': pair,
                'signal_value': f"{chg_pct:+.1f}%",
                'signal_pct': chg_pct,
                'lead_price': price_now,
                'lag_price_now': lag_price,
            })

    return signals


# ─── Signal loggen ────────────────────────────────────────────────────

def log_signal(conn, signal, vix, regime):
    """Schreibt ein neues Signal in die DB."""
    pair = signal['pair']
    now_utc = datetime.now(timezone.utc)
    lag_h = pair.get('lag_hours', 6)
    check_after = time.time() + lag_h * 3600
    accuracy = pair.get('accuracy_pct')

    conn.execute("""
        INSERT INTO signals (
            pair_id, lead_ticker, lag_ticker, signal_value,
            lead_price, lag_price_at_signal, outcome,
            regime_at_signal, vix_at_signal, accuracy_at_time,
            check_after_ts, direction, lag_hours,
            lead_name, lag_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        signal['pair_id'],
        pair['lead_ticker'],
        pair['lag_ticker'],
        signal['signal_value'],
        signal.get('lead_price'),
        signal.get('lag_price_now'),
        regime,
        vix,
        accuracy,
        check_after,
        pair['direction'],
        lag_h,
        pair.get('lead_name', pair['lead_ticker']),
        pair.get('lag_name', pair['lag_ticker']),
        now_utc.isoformat(),
    ))
    conn.commit()

    sig_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    print(f"  📡 Signal #{sig_id}: {pair.get('lead_name', pair['lead_ticker'])} → {pair.get('lag_name', pair['lag_ticker'])} ({signal['signal_value']})")
    print(f"     Prüfung in {lag_h}h | Regime: {regime} | VIX: {vix:.1f}")
    return sig_id


# ─── Outcome Check ───────────────────────────────────────────────────

def check_pending_outcomes(conn, lag_db):
    """Prüft alle PENDING Signale deren lag_hours abgelaufen sind."""
    now = time.time()
    pending = conn.execute(
        "SELECT * FROM signals WHERE outcome = 'PENDING' AND check_after_ts IS NOT NULL AND check_after_ts <= ?",
        (now,)
    ).fetchall()

    checked = 0
    wins = 0
    losses = 0

    for sig in pending:
        pair_id = sig['pair_id']
        lag_ticker = sig['lag_ticker']
        entry_price = sig['lag_price_at_signal']
        direction = sig['direction'] or 'same'
        signal_pct = None

        if not entry_price or entry_price == 0:
            # Kein Entry-Preis → kann nicht bewerten, als SKIP markieren
            conn.execute(
                "UPDATE signals SET outcome = 'SKIP', checked_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), sig['id'])
            )
            conn.commit()
            continue

        # Aktuellen Preis holen
        if lag_ticker == 'COMPUTED_BRENT_WTI_SPREAD':
            current = brent_wti_spread()
        else:
            current, _ = yahoo_price(lag_ticker)

        if current is None:
            continue  # Retry nächstes Mal

        actual_chg = (current - entry_price) / entry_price * 100

        # Bewertung
        try:
            sv = sig['signal_value'] or ''
            if '%' in sv:
                signal_pct = float(sv.replace('%', '').replace('+', ''))
        except (ValueError, TypeError):
            signal_pct = None

        if direction == 'inverse':
            # Lead steigt → Lag sollte fallen (oder umgekehrt)
            if signal_pct and signal_pct > 0:
                correct = actual_chg < -OUTCOME_THRESHOLD_PCT
            else:
                correct = actual_chg > OUTCOME_THRESHOLD_PCT
        elif direction in ('same', 'bullish'):
            if signal_pct and signal_pct < 0:
                correct = actual_chg < -OUTCOME_THRESHOLD_PCT
            else:
                correct = actual_chg > OUTCOME_THRESHOLD_PCT
        else:
            correct = abs(actual_chg) > OUTCOME_THRESHOLD_PCT

        outcome = 'WIN' if correct else 'LOSS'
        emoji = '✅' if correct else '❌'

        conn.execute("""
            UPDATE signals SET
                outcome = ?,
                lag_price_at_check = ?,
                change_pct = ?,
                checked_at = ?
            WHERE id = ?
        """, (
            outcome,
            current,
            round(actual_chg, 2),
            datetime.now(timezone.utc).isoformat(),
            sig['id'],
        ))
        conn.commit()
        checked += 1
        if correct:
            wins += 1
        else:
            losses += 1

        print(f"  {emoji} Signal #{sig['id']} ({pair_id}): {entry_price:.2f} → {current:.2f} ({actual_chg:+.1f}%) = {outcome}")

        # Accuracy in lag_knowledge.json updaten
        pair = lag_db.get('pairs', {}).get(pair_id)
        if pair:
            pair['sample_count'] = pair.get('sample_count', 0) + 1
            pair['wins'] = pair.get('wins', 0) + (1 if correct else 0)
            pair['losses'] = pair.get('losses', 0) + (0 if correct else 1)
            pair['accuracy_pct'] = round(pair['wins'] / pair['sample_count'] * 100, 1)

    if checked:
        print(f"  📊 Outcomes geprüft: {checked} | ✅ {wins} | ❌ {losses}")
    return lag_db


# ─── Stats ────────────────────────────────────────────────────────────

def print_stats(conn):
    """Zeigt aktuelle Signal-Statistiken."""
    total = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM signals WHERE outcome = 'PENDING'").fetchone()[0]
    wins = conn.execute("SELECT COUNT(*) FROM signals WHERE outcome = 'WIN'").fetchone()[0]
    losses = conn.execute("SELECT COUNT(*) FROM signals WHERE outcome = 'LOSS'").fetchone()[0]
    skips = conn.execute("SELECT COUNT(*) FROM signals WHERE outcome = 'SKIP'").fetchone()[0]

    resolved = wins + losses
    accuracy = (wins / resolved * 100) if resolved > 0 else 0

    print(f"  📈 Gesamt: {total} | ⏳ {pending} pending | ✅ {wins} wins | ❌ {losses} losses | ⏭️ {skips} skips")
    if resolved > 0:
        print(f"  🎯 Accuracy: {accuracy:.1f}% ({resolved} resolved)")

    # Per-pair stats
    pairs = conn.execute("""
        SELECT pair_id, lead_name, lag_name,
               COUNT(*) as total,
               SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) as losses
        FROM signals
        WHERE outcome IN ('WIN', 'LOSS')
        GROUP BY pair_id
        ORDER BY total DESC
    """).fetchall()
    if pairs:
        print(f"  --- Per-Pair Accuracy ---")
        for p in pairs:
            acc = p['wins'] / (p['wins'] + p['losses']) * 100 if (p['wins'] + p['losses']) > 0 else 0
            print(f"    {p['pair_id']}: {acc:.0f}% ({p['wins']}W/{p['losses']}L) — {p['lead_name']} → {p['lag_name']}")


# ─── Main ────────────────────────────────────────────────────────────

def main():
    if not LAG_DB.exists():
        print("KEIN_SIGNAL — lag_knowledge.json nicht gefunden")
        return

    lag_db = json.loads(LAG_DB.read_text())
    conn = get_db()
    now_utc = datetime.now(timezone.utc)

    print(f"[{now_utc.strftime('%H:%M UTC')}] Signal Tracker v2 läuft...")
    print(f"  {len(lag_db.get('pairs', {}))} Lead-Lag Paare geladen")

    # 1. VIX + Regime holen
    vix = get_vix() or 25.0
    regime = get_regime(vix)
    print(f"  VIX: {vix:.1f} | Regime: {regime}")

    # 2. Pending Outcomes prüfen (ZUERST — damit Accuracy aktuell ist)
    lag_db = check_pending_outcomes(conn, lag_db)

    # 3. Neue Signale detektieren
    signals = detect_signals(lag_db, {}, conn)
    print(f"  Neue Signale: {len(signals)}")

    for sig in signals:
        log_signal(conn, sig, vix, regime)

    # 4. Lag-DB mit neuen Accuracy-Werten speichern
    LAG_DB.write_text(json.dumps(lag_db, indent=2, ensure_ascii=False))

    # 5. Stats
    print_stats(conn)

    if not signals:
        pending = conn.execute("SELECT COUNT(*) FROM signals WHERE outcome = 'PENDING'").fetchone()[0]
        if pending:
            print(f"  KEIN_SIGNAL — {pending} Signale warten auf Outcome-Check")
        else:
            print("  KEIN_SIGNAL")

    conn.close()


if __name__ == '__main__':
    main()
