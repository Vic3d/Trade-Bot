"""
trademind/cli.py — Einziger CLI-Einstiegspunkt

Usage:
    python3 -m trademind prices --mode daily     # Preise aktualisieren
    python3 -m trademind sa auto                  # Albert Strategy autonomous
    python3 -m trademind sa report                # Albert Strategy Bericht
    python3 -m trademind stats                    # Strategie-Statistiken
    python3 -m trademind vix                      # Aktueller VIX + Zone
    python3 -m trademind regime                   # Marktregime
"""
import sys, os
import argparse


def cmd_stats(args):
    """Strategie-Statistiken aus der DB."""
    from trademind.core.db import get_db

    db = get_db()

    print("=" * 60)
    print("🎩 TRADEMIND — STRATEGIE-STATISTIKEN")
    print("=" * 60)

    # ── Trades pro Strategie + Win Rate + P&L ────────────────────────────────
    rows = db.execute("""
        SELECT
            strategy,
            COUNT(*) AS total,
            SUM(CASE WHEN status='WIN' OR result='WIN' OR pnl_eur > 0 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN status='LOSS' OR result='LOSS' OR pnl_eur < 0 THEN 1 ELSE 0 END) AS losses,
            ROUND(SUM(COALESCE(pnl_eur, 0)), 2) AS total_pnl,
            ROUND(AVG(COALESCE(pnl_pct, 0)) * 100, 2) AS avg_pnl_pct
        FROM trades
        WHERE status IN ('CLOSED', 'WIN', 'LOSS')
        GROUP BY strategy
        ORDER BY total DESC
    """).fetchall()

    total_trades = 0
    total_pnl = 0.0
    total_wins = 0

    print(f"\n{'Strategie':<12} {'Trades':>6} {'Win%':>7} {'Total P&L':>12} {'Avg%':>7}")
    print("-" * 50)

    for r in rows:
        total = r["total"]
        wins  = r["wins"] or 0
        wr    = (wins / total * 100) if total > 0 else 0
        pnl   = r["total_pnl"] or 0.0
        avg   = r["avg_pnl_pct"] or 0.0

        total_trades += total
        total_pnl    += pnl
        total_wins   += wins

        pnl_str = f"+{pnl:.0f}€" if pnl >= 0 else f"{pnl:.0f}€"
        print(f"{r['strategy']:<12} {total:>6} {wr:>6.1f}% {pnl_str:>12} {avg:>+6.2f}%")

    print("-" * 50)
    overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
    pnl_str = f"+{total_pnl:.0f}€" if total_pnl >= 0 else f"{total_pnl:.0f}€"
    print(f"{'GESAMT':<12} {total_trades:>6} {overall_wr:>6.1f}% {pnl_str:>12}")

    # ── VIX-Coverage ─────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("📊 DATENQUALITÄT")
    print(f"{'─'*60}")

    total_closed = db.execute(
        "SELECT COUNT(*) FROM trades WHERE status IN ('CLOSED','WIN','LOSS')"
    ).fetchone()[0]

    vix_filled = db.execute(
        "SELECT COUNT(*) FROM trades WHERE status IN ('CLOSED','WIN','LOSS') AND vix_at_entry IS NOT NULL"
    ).fetchone()[0]

    crv_filled = db.execute(
        "SELECT COUNT(*) FROM trades WHERE status IN ('CLOSED','WIN','LOSS') AND crv IS NOT NULL"
    ).fetchone()[0]

    regime_filled = db.execute(
        "SELECT COUNT(*) FROM trades WHERE status IN ('CLOSED','WIN','LOSS') AND regime_at_entry IS NOT NULL"
    ).fetchone()[0]

    def pct(n, total):
        return f"{n}/{total} ({n/total*100:.0f}%)" if total > 0 else "0/0"

    print(f"  VIX-Coverage:     {pct(vix_filled, total_closed)}")
    print(f"  CRV-Coverage:     {pct(crv_filled, total_closed)}")
    print(f"  Regime-Coverage:  {pct(regime_filled, total_closed)}")

    # ── Offene Positionen ────────────────────────────────────────────────────
    open_pos = db.execute(
        "SELECT COUNT(*) FROM trades WHERE status='OPEN'"
    ).fetchone()[0]

    if open_pos > 0:
        print(f"\n  Offene Positionen: {open_pos}")
        open_rows = db.execute(
            "SELECT ticker, strategy, entry_price, entry_date FROM trades WHERE status='OPEN'"
        ).fetchall()
        for op in open_rows:
            print(f"    {op['ticker']:<10} {op['strategy']:<10} Entry: {op['entry_price']}€  ({op['entry_date']})")

    db.close()
    print()


def cmd_vix(args):
    """Aktuellen VIX + Zone anzeigen."""
    from trademind.core.vix import get_vix, get_vix_zone

    vix  = get_vix()
    zone = get_vix_zone(vix)
    print(f"VIX: {vix:.2f}  Zone: {zone.upper()}")


def cmd_regime(args):
    """Aktuelles Marktregime anzeigen."""
    from trademind.core.regime import get_regime

    r = get_regime()
    print(f"Regime: {r.get('regime', 'UNKNOWN')}")
    for k, v in r.items():
        if k != "regime":
            print(f"  {k}: {v}")


def cmd_prices(args):
    """Preise aktualisieren (delegiert an price_updater)."""
    import subprocess, sys
    mode = getattr(args, "mode", "daily")
    result = subprocess.run(
        [sys.executable, "trademind/data/price_updater.py", "--mode", mode],
        cwd="/data/.openclaw/workspace",
    )
    sys.exit(result.returncode)


def cmd_sa(args):
    """Albert Strategy — delegiert an albert_strategy.py."""
    import subprocess, sys
    subcmd = getattr(args, "subcmd", "report")
    result = subprocess.run(
        [sys.executable, "scripts/albert_strategy.py", subcmd],
        cwd="/data/.openclaw/workspace",
    )
    sys.exit(result.returncode)


# ══════════════════════════════════════════════════════════════════════════════
# RISK COMMANDS (Phase 3)
# ══════════════════════════════════════════════════════════════════════════════

def _get_open_positions(db=None) -> list[dict]:
    """Lädt alle offenen Positionen aus der DB."""
    _own = False
    if db is None:
        from trademind.core.db import get_db
        db = get_db()
        _own = True
    rows = db.execute(
        """SELECT ticker, strategy, entry_price, shares, stop, target,
                  position_size_eur, pnl_eur, geo_theme
           FROM trades WHERE status='OPEN'"""
    ).fetchall()
    positions = [dict(r) for r in rows]
    if _own:
        db.close()
    return positions


def cmd_risk(args):
    """Vollständiger Risk Report."""
    from trademind.core.db import get_db
    from trademind.risk.circuit_breaker import check_circuit_breakers, get_breaker_summary
    from trademind.risk.portfolio import get_portfolio_exposure
    from trademind.risk.stress_test import run_stress_tests, format_stress_results

    db = get_db()
    positions = _get_open_positions(db)

    print("=" * 65)
    print("🎩 TRADEMIND — PORTFOLIO RISK REPORT")
    from datetime import datetime
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)

    # ── 1. Circuit Breakers ──────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("🔌 CIRCUIT BREAKER STATUS")
    print(f"{'─'*65}")
    cb = check_circuit_breakers(db)
    status_icon = "✅ TRADING ERLAUBT" if cb["trading_allowed"] else "🚨 TRADING GESPERRT"
    print(f"  Status: {status_icon}")
    print(get_breaker_summary(cb))

    # ── 2. Portfolio Exposure ────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("📊 PORTFOLIO EXPOSURE")
    print(f"{'─'*65}")
    exp = get_portfolio_exposure(positions)

    print(f"  Gesamt investiert: {exp['total_exposure']:,.0f}€")

    if exp["by_sector"]:
        print(f"\n  SEKTOREN (Limit: 40%):")
        for sector, data in sorted(exp["by_sector"].items(), key=lambda x: -x[1]["pct"]):
            flag = " ⚠️" if data["pct"] > 40 else ""
            print(f"    {sector:<15} {data['count']}x  {data['pct']:>5.1f}%  {data['value']:>8,.0f}€{flag}")

    if exp["by_region"]:
        print(f"\n  REGIONEN (Limit: 60%):")
        for region, data in sorted(exp["by_region"].items(), key=lambda x: -x[1]["pct"]):
            flag = " ⚠️" if data["pct"] > 60 else ""
            print(f"    {region:<15} {data['count']}x  {data['pct']:>5.1f}%  {data['value']:>8,.0f}€{flag}")

    if exp["by_theme"]:
        print(f"\n  THEMEN:")
        for theme, data in sorted(exp["by_theme"].items(), key=lambda x: -x[1]["pct"]):
            print(f"    {theme:<20} {data['count']}x  {data['pct']:>5.1f}%  {data['value']:>8,.0f}€")

    if exp["violations"]:
        print(f"\n  🚨 VIOLATIONS ({len(exp['violations'])}):")
        for v in exp["violations"]:
            print(f"    ⚠️  {v}")
    else:
        print(f"\n  ✅ Keine Limit-Verletzungen")

    # ── 3. Stress Tests ──────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("💥 STRESS TESTS")
    print(f"{'─'*65}")
    stress = run_stress_tests(positions)
    if stress:
        print(format_stress_results(stress, show_positions=False))
    else:
        print("  Keine offenen Positionen")

    print(f"\n{'='*65}\n")
    db.close()


def cmd_risk_corr(args):
    """Korrelationscheck für einen Ticker gegen aktuelle Positionen."""
    from trademind.risk.correlation import check_correlation

    ticker = args.ticker.upper()
    positions = _get_open_positions()
    open_tickers = [p["ticker"] for p in positions if p["ticker"] != ticker]

    print(f"\n🔗 KORRELATIONSCHECK: {ticker}")
    print(f"   Offene Positionen: {', '.join(open_tickers) if open_tickers else 'keine'}")
    print(f"   Lookback: 60 Tage\n")

    if not open_tickers:
        print("  Keine offenen Positionen → kein Korrelationsrisiko")
        return

    print("  Berechne Korrelationen... (kann ~10s dauern)")
    result = check_correlation(ticker, open_tickers)

    print(f"\n  Suggested Action: {result['suggested_action'].upper()}")
    print(f"  Approved: {'✅ Ja' if result['approved'] else '❌ Nein'}")
    print(f"  Reason: {result['reason']}")

    if result["correlations"]:
        print(f"\n  Korrelationen ({len(result['correlations'])}):")
        for t, corr in result["correlations"]:
            bar = "█" * int(abs(corr) * 20)
            flag = " 🚨" if abs(corr) >= 0.85 else (" ⚠️" if abs(corr) >= 0.70 else "")
            print(f"    {t:<12} {corr:+.3f}  {bar}{flag}")
    print()


def cmd_risk_stress(args):
    """Stress Tests anzeigen — mit Positionen-Detail."""
    from trademind.risk.stress_test import run_stress_tests, format_stress_results

    positions = _get_open_positions()

    print("\n💥 STRESS TESTS — DETAILANSICHT\n")
    stress = run_stress_tests(positions)

    if not stress:
        print("  Keine offenen Positionen")
        return

    for r in stress:
        severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
        icon = severity_icon.get(r["severity"], "⚪")
        print(f"{icon} {r['name']} — {r['description']}")
        print(f"   Erwarteter Verlust: {r['total_loss']:+,.0f}€  [{r['severity'].upper()}]")
        print(f"   {'Ticker':<12} {'Sektor':<12} {'Wert':>8} {'Schock':>7} {'Verlust':>8}")
        print(f"   {'─'*55}")
        for pos in r["by_position"]:
            print(
                f"   {pos['ticker']:<12} {pos['sector']:<12} "
                f"{pos['value']:>8,.0f}€ {pos['shock_pct']:>+6.0f}%  {pos['loss']:>+7,.0f}€"
            )
        print()


def cmd_risk_breakers(args):
    """Circuit Breaker Status detailliert."""
    from trademind.risk.circuit_breaker import check_circuit_breakers, get_breaker_summary, CIRCUIT_BREAKERS

    print("\n🔌 CIRCUIT BREAKER — STATUS\n")
    print(f"  Konfigurierte Limits:")
    print(f"    Daily Loss:        {CIRCUIT_BREAKERS['daily_loss_limit']}€")
    print(f"    Weekly Loss:       {CIRCUIT_BREAKERS['weekly_loss_limit']}€")
    print(f"    Max Drawdown:      {CIRCUIT_BREAKERS['max_drawdown']}€")
    print(f"    Consecutive Loss:  {CIRCUIT_BREAKERS['consecutive_losses']}x")
    print(f"    VIX Panic:         >{CIRCUIT_BREAKERS['vix_panic']}")
    print()

    result = check_circuit_breakers()
    status_icon = "✅ TRADING ERLAUBT" if result["trading_allowed"] else "🚨 TRADING GESPERRT"
    print(f"  Status: {status_icon}")
    print(get_breaker_summary(result))
    print()


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS COMMANDS (Phase 4)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_health(args):
    """Strategy Health Report — Metriken + Signifikanz + Monte Carlo für alle Strategien."""
    from trademind.core.db import get_db
    from trademind.analytics.health import generate_health_report

    strategy = getattr(args, 'strategy', None)
    db = get_db()
    report = generate_health_report(db, strategy_filter=strategy)
    db.close()
    print(report)


# ══════════════════════════════════════════════════════════════════════════════
# EXECUTION COMMANDS (Phase 5)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_costs(args):
    """Zeige realistische Execution-Kosten für einen Trade."""
    from trademind.execution.simulator import simulate_fill, format_fill_line, get_liquidity_class

    ticker = args.ticker.upper()
    position_eur = float(args.position_eur)

    # VIX laden
    try:
        from trademind.core.vix import get_vix
        vix = get_vix()
    except Exception:
        vix = 20.0
        print("  ⚠️ VIX nicht abrufbar — nutze 20.0 als Default")

    cls_name, params = get_liquidity_class(ticker)

    # Preis schätzen: aus Yahoo oder als position_eur/100 (Placeholder)
    try:
        from trademind.core.market_data import get_price_yahoo
        price_raw, currency = get_price_yahoo(ticker)
        if not price_raw:
            raise ValueError("Kein Preis")
        # Kurs in EUR
        if currency != 'EUR':
            try:
                from trademind.core.market_data import to_eur
                price_eur = to_eur(price_raw, currency)
            except Exception:
                price_eur = price_raw
        else:
            price_eur = price_raw
        shares = position_eur / price_eur
    except Exception as e:
        print(f"  ⚠️ Preis nicht verfügbar ({e}) — berechne mit position/100")
        price_eur = position_eur / 100
        shares = 100.0
        currency = 'EUR'

    fill_buy  = simulate_fill(price_eur, 'BUY',  ticker, vix)
    fill_sell = simulate_fill(price_eur, 'SELL', ticker, vix)

    # Kosten pro Trade (entry + exit = Roundtrip)
    roundtrip_spread   = round((fill_buy['spread_cost']   + fill_sell['spread_cost'])   * shares, 2)
    roundtrip_slippage = round((fill_buy['slippage_cost'] + fill_sell['slippage_cost']) * shares, 2)
    roundtrip_commission = 2.0  # 2× Trade Republic
    roundtrip_total    = round(roundtrip_spread + roundtrip_slippage + roundtrip_commission, 2)
    roundtrip_pct      = round(roundtrip_total / position_eur * 100, 3)

    print(f"\n{'='*60}")
    print(f"💸 EXECUTION KOSTEN: {ticker}  (Position: {position_eur:,.0f}€)")
    print(f"{'='*60}")
    print(f"  Kurs:           {price_eur:.2f}€ ({currency})")
    print(f"  Shares:         {shares:.1f}")
    print(f"  Liquidität:     {cls_name.upper()}  "
          f"(Spread {params['spread_pct']}%  |  Slippage-Mult {params['slippage_mult']}%)")
    print(f"  VIX:            {vix:.1f}  (Mult {vix/20:.2f}x)")
    print()
    print(f"  ── ENTRY (BUY) ──────────────────────────────────")
    print(f"  {format_fill_line(fill_buy, shares)}")
    print(f"  ── EXIT (SELL) ──────────────────────────────────")
    print(f"  {format_fill_line(fill_sell, shares)}")
    print()
    print(f"  ── ROUNDTRIP ────────────────────────────────────")
    print(f"  Spread total:    {roundtrip_spread:.2f}€")
    print(f"  Slippage total:  {roundtrip_slippage:.2f}€")
    print(f"  Gebühren total:  {roundtrip_commission:.2f}€")
    print(f"  ─────────────────────────────────────────────────")
    print(f"  GESAMT:          {roundtrip_total:.2f}€  ({roundtrip_pct:.3f}% der Position)")
    print(f"{'='*60}\n")


def cmd_gap(args):
    """Overnight Gap Risk für einen Ticker."""
    from trademind.execution.gap_model import estimate_gap_risk, format_gap_report

    ticker = args.ticker.upper()
    position_eur = float(getattr(args, 'position_eur', 5000))

    print(f"\n  📡 Lade 1-Jahr-Daten für {ticker}...")
    gap = estimate_gap_risk(ticker, position_eur)
    print(format_gap_report(gap))
    print()


def cmd_cost_summary(args):
    """Berechne wie viel reale Kosten historische Trades gekostet hätten."""
    from trademind.core.db import get_db
    from trademind.execution.simulator import simulate_fill

    db = get_db()

    rows = db.execute("""
        SELECT ticker, entry_price, exit_price, shares, pnl_eur,
               vix_at_entry, status
        FROM trades
        WHERE status IN ('WIN', 'LOSS', 'CLOSED', 'STOPPED')
          AND entry_price IS NOT NULL
          AND exit_price IS NOT NULL
          AND shares IS NOT NULL
    """).fetchall()

    db.close()

    if not rows:
        print("\n❌ Keine geschlossenen Trades gefunden.\n")
        return

    total_spread   = 0.0
    total_slippage = 0.0
    total_comm     = 0.0
    n = 0

    for r in rows:
        ticker     = r['ticker']
        entry_p    = float(r['entry_price'])
        exit_p     = float(r['exit_price'])
        shares     = float(r['shares'])
        vix        = float(r['vix_at_entry'] or 20.0)

        try:
            fe = simulate_fill(entry_p, 'BUY',  ticker, vix)
            fx = simulate_fill(exit_p,  'SELL', ticker, vix)
        except Exception:
            continue

        total_spread   += (fe['spread_cost']   + fx['spread_cost'])   * shares
        total_slippage += (fe['slippage_cost'] + fx['slippage_cost']) * shares
        total_comm     += 2.0  # entry + exit commission
        n += 1

    total_costs = total_spread + total_slippage + total_comm

    print(f"\n{'='*65}")
    print(f"💸 HISTORISCHE EXECUTION-KOSTEN ({n} geschlossene Trades)")
    print(f"{'='*65}")
    print(f"  Spread-Kosten:     {total_spread:>10.2f}€")
    print(f"  Slippage-Kosten:   {total_slippage:>10.2f}€")
    print(f"  Kommissionen:      {total_comm:>10.2f}€  ({n*2} Trades à 1€)")
    print(f"  {'─'*42}")
    print(f"  GESAMT Realkosten: {total_costs:>10.2f}€")
    print()
    print(f"  ⚠️  Bei {n} historischen Trades mit realistischen Kosten")
    print(f"      wäre das P&L um {total_costs:.2f}€ schlechter gewesen.")
    print(f"{'='*65}\n")


def cmd_backtest(args):
    """Walk-Forward Backtesting."""
    from trademind.analytics.backtester import WalkForwardBacktester
    
    bt = WalkForwardBacktester()
    strategy_type = args.strategy_type
    tickers = [t.upper() for t in args.tickers]
    
    if strategy_type == 'compare':
        print("\n🔬 STRATEGIE-VERGLEICH: Momentum vs Mean-Reversion\n")
        for st in ['momentum', 'meanrev']:
            method = getattr(bt, f'backtest_{st}', None) or getattr(bt, f'backtest_mean_reversion', None)
            if st == 'momentum':
                result = bt.backtest_momentum(tickers)
            else:
                result = bt.backtest_mean_reversion(tickers)
            agg = result.get('aggregate', {})
            print(f"  {st.upper():12s}: {agg.get('total_trades', 0):3d} trades | "
                  f"WR {agg.get('win_rate', 0)*100:.0f}% | P&L {agg.get('total_pnl', 0):+,.0f}€ | "
                  f"Sharpe {agg.get('sharpe', 0):.2f} | OOS: {'✅' if result.get('out_of_sample_valid') else '❌'}")
        return
    
    print(f"\n🔬 WALK-FORWARD BACKTEST: {strategy_type.upper()}")
    print(f"   Ticker: {', '.join(tickers)}\n")
    
    if strategy_type == 'momentum':
        result = bt.backtest_momentum(tickers)
    else:
        result = bt.backtest_mean_reversion(tickers)
    
    # Show windows
    windows = result.get('windows', [])
    if windows:
        print(f"  {'Fenster':<25} {'Trades':>6} {'WR':>6} {'P&L':>10}")
        print(f"  {'─'*50}")
        for w in windows:
            print(f"  {w.get('test_start','?'):10s}–{w.get('test_end','?'):10s}  "
                  f"{w.get('trades', 0):>6}  {w.get('wr', 0)*100:>5.0f}%  {w.get('pnl', 0):>+9,.0f}€")
    
    # Aggregate
    agg = result.get('aggregate', {})
    print(f"\n  {'='*50}")
    print(f"  AGGREGIERT (Out-of-Sample):")
    print(f"  Trades:        {agg.get('total_trades', 0)}")
    print(f"  Win Rate:      {agg.get('win_rate', 0)*100:.1f}%")
    print(f"  Total P&L:     {agg.get('total_pnl', 0):+,.0f}€")
    print(f"  Sharpe Ratio:  {agg.get('sharpe', 0):.2f}")
    print(f"  Max Drawdown:  {agg.get('max_drawdown', 0):+,.0f}€")
    print(f"  Profit Factor: {agg.get('profit_factor', 0):.2f}")
    
    # Benchmark
    bm = result.get('benchmark', {})
    if bm:
        print(f"\n  BENCHMARK-VERGLEICH:")
        print(f"  SPY Buy&Hold:  {bm.get('spy_return', 0):+.1f}%")
        print(f"  DAX Buy&Hold:  {bm.get('dax_return', 0):+.1f}%")
    
    oos = result.get('out_of_sample_valid')
    print(f"\n  Out-of-Sample: {'✅ VALIDE (Sharpe > 0)' if oos else '❌ NICHT VALIDE'}")


def cmd_dashboard(args):
    """Dashboard-Daten generieren."""
    subcmd = getattr(args, 'subcmd', 'generate')
    
    if subcmd == 'generate':
        from trademind.dashboard.generate_data import generate_dashboard_data
        data = generate_dashboard_data()
        import json
        outpath = os.path.join(os.path.dirname(__file__), 'dashboard', 'data.json')
        with open(outpath, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"✅ Dashboard-Daten generiert: {outpath}")
        print(f"   Positionen: {len(data.get('positions', {}).get('open', []))}")
        print(f"   Geschlossene Trades: {len(data.get('performance', {}).get('equity_curve', []))}")
    elif subcmd == 'serve':
        import http.server, functools
        dash_dir = os.path.join(os.path.dirname(__file__), 'dashboard')
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=dash_dir)
        with http.server.HTTPServer(('0.0.0.0', 8888), handler) as httpd:
            print(f"🌐 Dashboard: http://localhost:8888")
            httpd.serve_forever()


def cmd_montecarlo(args):
    """Monte Carlo Simulation für eine Strategie."""
    from trademind.core.db import get_db
    from trademind.analytics.monte_carlo import monte_carlo_simulation, format_monte_carlo_report

    strategy = args.strategy.upper()
    db = get_db()

    rows = db.execute(
        "SELECT * FROM trades WHERE strategy=? AND status IN ('WIN','LOSS')",
        (strategy,)
    ).fetchall()
    db.close()

    trades = [dict(r) for r in rows]

    if not trades:
        print(f"\n❌ Keine geschlossenen Trades für Strategie '{strategy}' gefunden.\n")
        return

    print(f"\n  Running Monte Carlo für {strategy} ({len(trades)} Trades)...")
    mc = monte_carlo_simulation(trades, num_simulations=10000, future_trades=100)
    print(format_monte_carlo_report(strategy, mc))
    print()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="trademind",
        description="🎩 TradeMind Trading-Bot CLI",
    )
    sub = parser.add_subparsers(dest="command", help="Befehl")

    # stats
    p_stats = sub.add_parser("stats", help="Strategie-Statistiken")
    p_stats.set_defaults(func=cmd_stats)

    # vix
    p_vix = sub.add_parser("vix", help="Aktueller VIX")
    p_vix.set_defaults(func=cmd_vix)

    # regime
    p_regime = sub.add_parser("regime", help="Marktregime")
    p_regime.set_defaults(func=cmd_regime)

    # prices
    p_prices = sub.add_parser("prices", help="Preise aktualisieren")
    p_prices.add_argument("--mode", default="daily", choices=["daily", "backfill"])
    p_prices.set_defaults(func=cmd_prices)

    # sa (Albert Strategy)
    p_sa = sub.add_parser("sa", help="Albert Strategy")
    p_sa.add_argument("subcmd", nargs="?", default="report",
                      choices=["auto", "report", "scan", "monitor", "trade"])
    p_sa.set_defaults(func=cmd_sa)

    # risk (Phase 3 — Portfolio Risikomanagement)
    p_risk = sub.add_parser("risk", help="Portfolio Risk Report & Checks")
    risk_sub = p_risk.add_subparsers(dest="risk_cmd")

    # risk (ohne Subbefehl) → voller Report
    p_risk.set_defaults(func=cmd_risk)

    # risk corr TICKER
    p_risk_corr = risk_sub.add_parser("corr", help="Korrelationscheck für Ticker")
    p_risk_corr.add_argument("ticker", help="Ticker der neuen Position (z.B. OXY)")
    p_risk_corr.set_defaults(func=cmd_risk_corr)

    # risk stress
    p_risk_stress = risk_sub.add_parser("stress", help="Stress Tests")
    p_risk_stress.set_defaults(func=cmd_risk_stress)

    # risk breakers
    p_risk_breakers = risk_sub.add_parser("breakers", help="Circuit Breaker Status")
    p_risk_breakers.set_defaults(func=cmd_risk_breakers)

    # health [STRATEGIE]  — Strategy Health Report (Phase 4)
    p_health = sub.add_parser("health", help="Strategy Health Report (Metriken + Signifikanz + Monte Carlo)")
    p_health.add_argument("strategy", nargs="?", default=None,
                          help="Nur für diese Strategie (z.B. DT4). Ohne Argument: alle.")
    p_health.set_defaults(func=cmd_health)

    # montecarlo STRATEGIE  — Monte Carlo für eine Strategie
    p_mc = sub.add_parser("montecarlo", help="Monte Carlo Simulation für eine Strategie")
    p_mc.add_argument("strategy", help="Strategie (z.B. SA, DT4)")
    p_mc.set_defaults(func=cmd_montecarlo)

    # costs TICKER POSITION_EUR  — Execution-Kosten (Phase 5)
    p_costs = sub.add_parser("costs", help="Realistische Execution-Kosten für einen Trade")
    p_costs.add_argument("ticker", help="Ticker (z.B. OXY)")
    p_costs.add_argument("position_eur", type=float, help="Positionsgröße in EUR (z.B. 5000)")
    p_costs.set_defaults(func=cmd_costs)

    # gap TICKER [POSITION_EUR]  — Overnight Gap Risk (Phase 5)
    p_gap = sub.add_parser("gap", help="Overnight Gap Risk für einen Ticker")
    p_gap.add_argument("ticker", help="Ticker (z.B. OXY)")
    p_gap.add_argument("position_eur", type=float, nargs="?", default=5000,
                       help="Positionsgröße in EUR (default: 5000)")
    p_gap.set_defaults(func=cmd_gap)

    # costsummary  — Historische Kosten-Zusammenfassung (Phase 5)
    p_costsummary = sub.add_parser("costsummary", help="Historische Execution-Kosten Summary")
    p_costsummary.set_defaults(func=cmd_cost_summary)

    # backtest  — Walk-Forward Backtester (Phase 6)
    p_bt = sub.add_parser("backtest", help="Walk-Forward Backtesting")
    p_bt.add_argument("strategy_type", choices=["momentum", "meanrev", "compare"],
                      help="Strategie-Typ: momentum, meanrev, oder compare")
    p_bt.add_argument("tickers", nargs="*", default=["OXY", "FRO", "AG"],
                      help="Ticker für Backtest")
    p_bt.set_defaults(func=cmd_backtest)

    # dashboard  — Dashboard Data Generator (Phase 7)
    p_dash = sub.add_parser("dashboard", help="Dashboard-Daten generieren")
    p_dash.add_argument("subcmd", nargs="?", default="generate",
                        choices=["generate", "serve"])
    p_dash.set_defaults(func=cmd_dashboard)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Risk-Subcommand-Routing: wenn risk_cmd gesetzt ist, nutze dessen func
    if args.command == "risk" and hasattr(args, "risk_cmd") and args.risk_cmd is not None:
        args.func(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
