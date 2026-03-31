#!/usr/bin/env python3
"""
Autonomous Trading Loop — Der Orchestrator
Verbindet: News → Analyse → Strategie → Trade → Monitor → Exit

Kette:
1. global_radar.py → Signale aus globalen News
2. opportunity_scanner.py → technische Bewertung (Preis/52W)
3. Conviction Score → Entry-Entscheidung
4. Trade öffnen (paper_portfolio)
5. Entscheidung loggen (entscheidungs-log.md)
"""

import sqlite3, json, datetime, sys, os, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

DB = 'data/trading.db'
POSITION_SIZE = 2000        # € pro Position
ENTRY_THRESHOLD = 52        # Conviction Score für autonomen Trade
WATCHLIST_THRESHOLD = 35    # Score für Watchlist
MAX_POSITIONS = 15          # Maximale Paper-Positionen
MAX_PER_SECTOR = 3          # Max Positionen pro Sektor

# ─── Sektor-Rotation-Multiplier laden ─────────────────────────────────────────
def load_rotation_multiplier() -> dict:
    """
    Liest data/sector_rotation_state.json und gibt rotation_multiplier zurück.
    Falls Datei fehlt oder zu alt (>12h): leeres Dict → alle Sektoren 1.0x.
    """
    try:
        _ws = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _path = os.path.join(_ws, 'data', 'sector_rotation_state.json')
        if not os.path.exists(_path):
            return {}
        state = json.loads(open(_path).read())
        # Staleness-Check: älter als 12h → ignorieren
        ts = datetime.datetime.fromisoformat(state.get('timestamp', '2000-01-01'))
        if (datetime.datetime.now() - ts).total_seconds() > 43200:
            return {}
        return state.get('rotation_multiplier', {})
    except Exception:
        return {}

def get_price(ticker):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1wk&range=6mo'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=8).read())
        r = data['chart']['result'][0]
        closes = [c for c in r['indicators']['quote'][0]['close'] if c]
        m = r['meta']
        cur = m.get('regularMarketPrice')
        h52 = m.get('fiftyTwoWeekHigh')
        l52 = m.get('fiftyTwoWeekLow')
        # ATR annähern: durchschnittliche Wochenrange der letzten 8 Wochen
        highs = r['indicators']['quote'][0].get('high', [])
        lows = r['indicators']['quote'][0].get('low', [])
        ranges = [h-l for h, l in zip(highs[-8:], lows[-8:]) if h and l]
        atr_weekly = sum(ranges)/len(ranges) if ranges else cur*0.03 if cur else 0
        return cur, h52, l52, closes, atr_weekly
    except:
        return None, None, None, [], 0

def score_opportunity(ticker, cur, h52, l52, closes, direction, news_confidence, atr):
    """Kombinierter Score aus Technik + News-Signal"""
    score = 0
    reasons = []

    if not cur or not h52 or not l52:
        return 0, []

    # 1. Technisch: Abstand vom 52W-High
    fh = (cur/h52-1)*100
    if fh < -30:    score += 25; reasons.append(f"Tief {fh:.1f}% unter 52W-High")
    elif fh < -20:  score += 18; reasons.append(f"Abschlag {fh:.1f}% unter 52W-High")
    elif fh < -10:  score += 10; reasons.append(f"Moderat {fh:.1f}% unter 52W-High")

    # 2. Sicherheitsabstand vom Low
    fl = (cur/l52-1)*100
    if fl > 25:     score += 12; reasons.append("Sicherer Abstand vom 52W-Low")
    elif fl > 10:   score += 6

    # 3. Momentum Stabilisierung
    if len(closes) >= 6:
        if closes[-1] >= closes[-4]*0.98:
            score += 15; reasons.append("Momentum stabilisiert")
        elif closes[-1] < closes[-4]*0.94:
            score -= 8; reasons.append("Noch fallend")

    # 4. News-Signal
    if news_confidence == "hoch":
        if "BULLISCH" in direction:  score += 20; reasons.append("Starkes bullisches News-Signal")
        elif direction == "UP":      score += 12; reasons.append("Positives News-Signal")
    elif news_confidence == "mittel":
        score += 6

    # 5. CRV-Check: Stop = 1.5x ATR, Ziel = 3x ATR → mindestens 2:1
    if atr > 0:
        stop_dist = min(1.5 * atr, cur * 0.15)
        target_dist = max(3.0 * atr, cur * 0.20)
        crv = target_dist / stop_dist
        if crv >= 2.5:  score += 10; reasons.append(f"CRV {crv:.1f}:1 attraktiv")
        elif crv >= 2:  score += 5
        else:           score -= 5; reasons.append(f"CRV {crv:.1f}:1 schwach")

    return max(0, min(100, score)), reasons

def get_portfolio_state():
    """Aktuelle Portfoliostruktur aus DB"""
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT value FROM paper_fund WHERE key='current_cash'")
    row = c.fetchone()
    cash = float(row[0]) if row else 25000.0
    c.execute("SELECT ticker, sector FROM paper_portfolio WHERE status='OPEN'")
    positions = c.fetchall()
    c.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'")
    n_open = c.fetchone()[0]
    conn.close()
    sectors = {}
    for _, sec in positions:
        sectors[sec or 'Other'] = sectors.get(sec or 'Other', 0) + 1
    return cash, n_open, sectors, [t for t, _ in positions]

def sync_cash_if_needed(db):
    """Synct paper_fund.current_cash wenn Desync > 50€"""
    open_pos = db.execute("SELECT SUM(entry_price * shares) FROM paper_portfolio WHERE status='OPEN'").fetchone()[0] or 0
    pnl = db.execute("SELECT COALESCE(SUM(pnl_eur),0) FROM paper_portfolio WHERE status IN ('CLOSED','WIN','LOSS') AND pnl_eur IS NOT NULL").fetchone()[0] or 0
    correct = 25000.0 + pnl - open_pos
    current = float(db.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()[0] or 25000)
    if abs(correct - current) > 50:
        db.execute("UPDATE paper_fund SET value=? WHERE key='current_cash'", (correct,))
        db.commit()
        print(f"  🔧 Cash-Sync: {current:.0f}€ → {correct:.0f}€")

def already_in_portfolio(ticker):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM paper_portfolio WHERE ticker=? AND status='OPEN'", (ticker,))
    n = c.fetchone()[0]
    conn.close()
    return n > 0

def open_trade(ticker, strategy, sector, cur_price, atr, reasons, direction, headline):
    """Trade in paper_portfolio eröffnen"""
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    stop_dist = min(1.5 * atr, cur_price * 0.12)
    target_dist = max(3.0 * atr, cur_price * 0.22)
    stop = round(cur_price - stop_dist, 4)
    target = round(cur_price + target_dist, 4)
    shares = round(POSITION_SIZE / cur_price, 4)
    fees = 1.0

    c.execute("""
        INSERT INTO paper_portfolio
        (ticker, strategy, entry_price, entry_date, shares, stop_price, target_price,
         status, fees, notes, style, conviction, sector)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ticker, strategy, cur_price, datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        shares, stop, target, 'OPEN', fees,
        f"AUTO: {headline[:100]}",
        'swing', 65, sector
    ))

    # Cash aktualisieren
    c.execute("UPDATE paper_fund SET value = value - ? WHERE key='current_cash'",
              (POSITION_SIZE + fees,))
    conn.commit()
    conn.close()

    return stop, target, shares

def log_decision(ticker, decision, score, reasons, headline, trade_details=None):
    """Entscheidung in entscheidungs-log.md schreiben"""
    today = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    entry = f"""
## {today} — AUTO: {decision} {ticker}
**Entscheidung:** {decision} für {ticker} (Score: {score}/100)
**Auslöser:** {headline[:120]}
**Kern-Reasoning:** {' | '.join(reasons[:3])}
"""
    if trade_details:
        entry += f"**Trade:** Entry {trade_details['entry']:.2f}€ | Stop {trade_details['stop']:.2f}€ | Ziel {trade_details['target']:.2f}€ | {trade_details['shares']:.2f} Stück\n"

    log_path = 'memory/entscheidungs-log.md'
    with open(log_path, 'a') as f:
        f.write(entry)

def run_autonomous_loop(radar_signals=None):
    """Hauptschleife: Signale verarbeiten → Entscheidungen treffen"""
    print(f"\n{'='*65}")
    print(f"🤖 AUTONOMOUS LOOP — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*65}")

    # Cash-Sanity-Check
    _sync_conn = sqlite3.connect(DB)
    sync_cash_if_needed(_sync_conn)
    _sync_conn.close()

    cash, n_open, sectors, held_tickers = get_portfolio_state()
    slots_free = MAX_POSITIONS - n_open
    print(f"Portfolio: {n_open} Positionen | Cash: {cash:.0f}€ | Freie Slots: {slots_free}")

    if slots_free <= 0 or cash < POSITION_SIZE * 1.5:
        print("⛔ Kein Platz oder zu wenig Cash — kein neuer Trade")
        return []

    # Signale aus DB laden falls nicht übergeben
    if not radar_signals:
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        # Letzte 12h aus global_radar
        cutoff = (datetime.datetime.now() - datetime.timedelta(hours=12)).isoformat()
        c.execute("""
            SELECT headline, sector, tickers, direction, confidence
            FROM global_radar WHERE scanned_at > ? AND confidence='hoch'
            ORDER BY id DESC LIMIT 30
        """, (cutoff,))
        rows = c.fetchall()
        conn.close()
        radar_signals = [{'headline': r[0], 'sector': r[1],
                          'tickers': json.loads(r[2]), 'direction': r[3],
                          'confidence': r[4]} for r in rows]

    print(f"Verarbeite {len(radar_signals)} Signale...")
    trades_opened = []
    watchlist_added = []

    seen_tickers = set()
    for sig in radar_signals:
        for ticker in sig['tickers']:
            if ticker in seen_tickers or ticker == 'depends_on_sector':
                continue
            seen_tickers.add(ticker)

            if already_in_portfolio(ticker):
                continue

            # 24h-Cooldown: Ticker erst wieder handeln wenn letzte Schließung > 24h zurück
            _conn_cd = sqlite3.connect(DB)
            recent_close = _conn_cd.execute("""
                SELECT COUNT(*) FROM paper_portfolio 
                WHERE ticker=? AND status IN ('CLOSED','WIN','LOSS')
                AND close_date > datetime('now', '-24 hours')
            """, (ticker,)).fetchone()[0]
            _conn_cd.close()
            if recent_close > 0:
                print(f"  ⏳ {ticker}: Cooldown aktiv (in letzten 24h geschlossen)")
                continue

            # Sektor-Limit prüfen
            sector = sig['sector']
            if sectors.get(sector, 0) >= MAX_PER_SECTOR:
                continue

            cur, h52, l52, closes, atr = get_price(ticker)
            if not cur:
                continue

            score, reasons = score_opportunity(
                ticker, cur, h52, l52, closes,
                sig['direction'], sig['confidence'], atr
            )

            # ─── Sektor-Rotation-Multiplier anwenden ──────────────────
            # final_score = conviction * rotation_multiplier.get(sector, 1.0)
            # Sektoren mit 0.0x werden komplett blockiert (z.B. Halbleiter, Agrar)
            _rotation = load_rotation_multiplier()
            _sector_display = sector.capitalize() if sector else 'Other'
            _multiplier = _rotation.get(_sector_display, _rotation.get(sector, 1.0))
            final_score = round(score * _multiplier)
            if _multiplier != 1.0:
                reasons.append(f'Rotation×{_multiplier:.1f} ({_sector_display}): {score}→{final_score}')
            score = final_score
            # ─────────────────────────────────────────────────────────

            print(f"\n  {ticker:12s} | Score: {score:3d}/100 | {sig['direction']:12s} | {sig['headline'][:45]}")

            if score >= ENTRY_THRESHOLD and slots_free > 0 and "BULLISCH" in sig['direction']:
                strategy = f"AR-{sector[:4].upper()}"  # AR = Autonomous Radar

                # ─── ENTRY GATE CHECK ─────────────────────────────────
                try:
                    import sys as _sys, os as _os
                    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
                    from entry_gate import EntryGate
                    _gate = EntryGate(DB)
                    # Versuche regime aus DB zu laden
                    _regime = ''
                    try:
                        _conn_r = sqlite3.connect(DB)
                        _rrow = _conn_r.execute(
                            "SELECT regime FROM regime_history ORDER BY date DESC LIMIT 1"
                        ).fetchone()
                        _regime = _rrow[0] if _rrow else ''
                        _conn_r.close()
                    except Exception:
                        pass
                    _gate_result = _gate.check(
                        ticker, strategy,
                        news_headline=sig.get('headline', ''),
                        news_source=sig.get('source', ''),
                        regime=_regime,
                        vix=0
                    )
                    if not _gate_result['allowed']:
                        print(f"  🚫 [ENTRY GATE BLOCKED] {ticker}/{strategy}: {_gate_result['reason']}")
                        continue
                    if _gate_result.get('warnings'):
                        for _w in _gate_result['warnings']:
                            print(f"  ⚠️  [GATE WARNING] {_w}")
                except ImportError:
                    pass  # graceful fallback
                # ─── END ENTRY GATE ───────────────────────────────────

                # ─── CEO REVIEW — Gate 2 der Trade-Pipeline ──────────
                try:
                    from ceo_trade_review import ceo_review
                    _review = ceo_review({
                        'ticker': ticker,
                        'strategy_id': strategy,
                        'price': cur,
                        'conviction': max(1, score // 10),  # normalize 0-100 → 1-10
                        'signal': sig.get('direction', 'BULLISCH'),
                        'sector': sector.capitalize() if sector else 'UNKNOWN'
                    })
                    if _review['decision'] == 'REJECT':
                        print(f"  ❌ CEO REJECT: {ticker} — {_review['reason']}")
                        continue
                    elif _review['decision'] == 'WATCH':
                        print(f"  👁  CEO WATCH: {ticker} — {_review['reason']}")
                        log_decision(ticker, "CEO WATCH", score, reasons, sig['headline'])
                        watchlist_added.append(ticker)
                        continue
                    # APPROVE → proceed
                    _thesis_short = _review.get('thesis', '')[:60]
                    print(f"  🎩 CEO APPROVE: {ticker} | These: {_thesis_short}")
                except ImportError:
                    pass  # graceful fallback if script not available
                # ─── END CEO REVIEW ───────────────────────────────────

                stop, target, shares = open_trade(
                    ticker, strategy, sector, cur, atr, reasons,
                    sig['direction'], sig['headline']
                )
                log_decision(ticker, "TRADE ERÖFFNET", score, reasons, sig['headline'], {
                    'entry': cur, 'stop': stop, 'target': target, 'shares': shares
                })
                slots_free -= 1
                sectors[sector] = sectors.get(sector, 0) + 1
                trades_opened.append(ticker)
                print(f"  ✅ TRADE: {ticker} @ {cur:.2f}€ | Stop: {stop:.2f}€ | Ziel: {target:.2f}€")

            elif score >= WATCHLIST_THRESHOLD:
                log_decision(ticker, "WATCHLIST", score, reasons, sig['headline'])
                watchlist_added.append(ticker)
                print(f"  🟡 WATCHLIST: {ticker}")

    print(f"\n{'='*65}")
    print(f"ERGEBNIS: {len(trades_opened)} neue Trades | {len(watchlist_added)} auf Watchlist")
    if trades_opened:
        print(f"Trades: {', '.join(trades_opened)}")

    # ─── POST-TRADE ANALYZER ─────────────────────────────────────
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        from post_trade_analyzer import analyze_new_closed_trades
        analyze_new_closed_trades(DB)
    except Exception as _e:
        print(f"[POSTMORTEM] {_e}")
    # ─── END POST-TRADE ANALYZER ─────────────────────────────────

    return trades_opened

if __name__ == '__main__':
    run_autonomous_loop()


# ─────────────────────────────────────────────
# LEARNING LOOP — Jeder Trade bekommt ein Lernprotokoll
# ─────────────────────────────────────────────

def close_trade_with_lesson(trade_id, ticker, entry, close_price, reason_close, original_signal):
    """Schließt Trade + schreibt Lektion sofort"""
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    pnl = round((close_price - entry) * (2000 / entry), 2)
    pnl_pct = round((close_price / entry - 1) * 100, 2)
    outcome = "WIN" if pnl > 0 else "LOSS"

    c.execute("""UPDATE paper_portfolio
        SET status='CLOSED', close_price=?, close_date=?, pnl_eur=?, pnl_pct=?
        WHERE id=?
    """, (close_price, datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), pnl, pnl_pct, trade_id))

    # Cash zurückbuchen
    c.execute("UPDATE paper_fund SET value = value + ? WHERE key='current_cash'",
              (2000 + pnl,))
    conn.commit()
    conn.close()

    # Lektion ableiten
    if outcome == "WIN":
        lesson = f"Signal '{original_signal[:60]}' war korrekt. Thesis bestätigt."
    else:
        lesson = f"Signal '{original_signal[:60]}' war falsch oder zu früh. Warum: {reason_close}"

    # In albert-accuracy.md eintragen
    accuracy_path = 'memory/albert-accuracy.md'
    entry_text = f"\n| {datetime.date.today()} | AUTO | {ticker} | {pnl:+.2f}€ | {pnl_pct:+.1f}% | {outcome} | {reason_close} |"
    try:
        with open(accuracy_path, 'a') as f:
            f.write(entry_text)
    except: pass

    # Vollständige Lektion in entscheidungs-log
    log_path = 'memory/entscheidungs-log.md'
    log_entry = f"""
## {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} — ABSCHLUSS {outcome}: {ticker}
**Ergebnis:** {pnl:+.2f}€ ({pnl_pct:+.1f}%) | Exit-Grund: {reason_close}
**Original-Signal:** {original_signal[:120]}
**Lesson:** {lesson}
"""
    try:
        with open(log_path, 'a') as f:
            f.write(log_entry)
    except: pass

    print(f"  📚 Lektion gespeichert: {outcome} {ticker} {pnl:+.2f}€ — {lesson[:60]}")
    return pnl, lesson


def check_and_close_positions():
    """
    Prüft alle offenen Positionen gegen aktuelle Kurse.
    Stop hit → schließen + Lektion. Target hit → schließen + Lektion.
    """
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT id, ticker, strategy, entry_price, stop_price, target_price, notes
        FROM paper_portfolio WHERE status='OPEN'
    """)
    positions = c.fetchall()
    conn.close()

    closed = []
    for pos in positions:
        pid, ticker, strategy, entry, stop, target, notes = pos
        cur, _, _, _, _ = get_price(ticker)
        if not cur:
            continue

        reason = None
        close_price = cur

        if cur <= stop:
            reason = f"STOP HIT @ {cur:.2f}€ (Stop war {stop:.2f}€)"
        elif cur >= target:
            reason = f"TARGET HIT @ {cur:.2f}€ (Ziel war {target:.2f}€)"

        if reason:
            original_signal = notes or "Kein Signal-Text verfügbar"
            pnl, lesson = close_trade_with_lesson(pid, ticker, entry, close_price, reason, original_signal)
            closed.append((ticker, pnl, lesson))

    return closed


def run_full_cycle():
    """Kompletter autonomer Zyklus: Exit-Check → Radar → Entry"""
    print(f"\n{'='*65}")
    print(f"🔄 FULL CYCLE — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*65}")

    # 1. Erst Exit-Check (Stops + Targets)
    print("\n[1/3] Exit-Check...")
    closed = check_and_close_positions()
    if closed:
        print(f"  {len(closed)} Positionen geschlossen:")
        for t, pnl, lesson in closed:
            print(f"  {t}: {pnl:+.2f}€ | {lesson[:50]}")
    else:
        print("  Keine Exits fällig")

    # 2. Radar + Entry
    print("\n[2/3] Autonomous Entry-Loop...")
    new_trades = run_autonomous_loop()

    # 3. Portfolio-Summary
    cash, n_open, sectors, _ = get_portfolio_state()
    print(f"\n[3/3] Portfolio: {n_open} Positionen | Cash: {cash:.0f}€")

    return closed, new_trades
