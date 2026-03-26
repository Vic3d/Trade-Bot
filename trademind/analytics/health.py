"""
trademind/analytics/health.py — Strategy Health Report

Für alle Strategien mit >= 5 geschlossenen Trades:
- Metriken berechnen (Sharpe, Sortino, Max DD, ...)
- Signifikanz testen (Binomial, t-Test, Bootstrap)
- Monte Carlo laufen lassen
- Empfehlung: KEEP / REVIEW / KILL / INSUFFICIENT

Empfehlungslogik:
    KILL:        p-value > 0.20 UND negative P&L UND > 20 Trades
    REVIEW:      p-value 0.05-0.20 ODER Sharpe < 0.5
    KEEP:        p-value < 0.05 UND Sharpe > 0.5 UND positive P&L
    INSUFFICIENT: < 10 Trades (zu wenig für Signifikanz)
"""
from .metrics import calculate_strategy_metrics
from .significance import test_strategy_significance
from .monte_carlo import monte_carlo_simulation


MIN_TRADES_FOR_METRICS  = 5
MIN_TRADES_FOR_VERDICT  = 10


def _get_recommendation(metrics: dict, sig: dict) -> tuple[str, str]:
    """
    Empfehlung: KEEP / REVIEW / KILL / INSUFFICIENT
    Returns: (label, reason)
    """
    n = metrics['total_trades']
    pnl = metrics['total_pnl']
    sharpe = metrics['sharpe_ratio']
    wr = metrics['win_rate']
    pf = metrics['profit_factor']
    binom_p = sig['binom_p']
    t_p = sig['t_test_p']
    # Kombinierter p-value: nehme den höheren (konservativer)
    p_max = max(binom_p, t_p)

    # ── Obvious KILL — auch ohne 10+ Trades wenn Evidenz überwältigend ───────
    # WR < 20% UND PF < 0.35 UND negatives P&L UND min 5 Trades
    # Das ist mathematisch klar: keine Chance auf Profitabilität
    if n >= MIN_TRADES_FOR_METRICS and pnl < 0 and wr < 0.25 and pf < 0.35:
        wins_count = round(wr * n)
        return 'KILL', (
            f"Überwältigende Negativ-Evidenz: WR={wr*100:.0f}% ({wins_count}/{n} Wins), "
            f"PF={pf:.2f}, P&L={pnl:+.0f}€ — kein realistischer Edge"
        )

    if n < MIN_TRADES_FOR_VERDICT:
        return 'INSUFFICIENT', f"Nur {n} Trades — zu wenig für statistisches Urteil (min. {MIN_TRADES_FOR_VERDICT})"

    # KILL: p > 0.20 UND negatives P&L UND > 20 Trades (genug Daten, kein Edge)
    if p_max > 0.20 and pnl < 0 and n > 20:
        return 'KILL', f"p={p_max:.2f} (kein Edge), P&L={pnl:+.0f}€ (negativ), {n} Trades (genug Daten)"

    # KEEP: p < 0.05 UND Sharpe > 0.5 UND positives P&L
    if p_max < 0.05 and sharpe > 0.5 and pnl > 0:
        return 'KEEP', f"p={p_max:.3f} (signifikant), Sharpe={sharpe:.2f}, P&L={pnl:+.0f}€"

    # REVIEW: zwischen KILL und KEEP
    reasons = []
    if 0.05 <= p_max <= 0.20:
        reasons.append(f"p={p_max:.3f} (unklar ob Edge)")
    if p_max > 0.20:
        reasons.append(f"p={p_max:.3f} (kein Edge)")
    if sharpe < 0.5:
        reasons.append(f"Sharpe={sharpe:.2f} (zu niedrig)")
    if pnl < 0:
        reasons.append(f"P&L={pnl:+.0f}€ (negativ)")

    reason = "; ".join(reasons) if reasons else "Grenzfall"
    return 'REVIEW', reason


def _load_trades_for_strategy(db, strategy: str) -> list[dict]:
    """Lädt alle geschlossenen Trades für eine Strategie."""
    rows = db.execute(
        "SELECT * FROM trades WHERE strategy=? AND status IN ('WIN','LOSS')",
        (strategy,)
    ).fetchall()
    return [dict(r) for r in rows]


def generate_health_report(db, strategy_filter: str = None) -> str:
    """
    Vollständiger Strategy Health Report.
    
    Für alle Strategien mit >= 5 geschlossenen Trades:
    - Metriken, Signifikanz, Monte Carlo, Empfehlung
    
    Args:
        db: Datenbankverbindung (aus get_db())
        strategy_filter: Optional — nur diese Strategie anzeigen (z.B. 'DT4')
    
    Returns: Formatierter Report als String
    """
    from datetime import datetime

    # ── Alle Strategien mit >= 5 Trades laden ────────────────────────────────
    query = """
        SELECT strategy, COUNT(*) as cnt
        FROM trades
        WHERE status IN ('WIN', 'LOSS')
        GROUP BY strategy
        HAVING cnt >= ?
        ORDER BY cnt DESC
    """
    rows = db.execute(query, (MIN_TRADES_FOR_METRICS,)).fetchall()

    if strategy_filter:
        rows = [r for r in rows if r['strategy'] == strategy_filter]

    if not rows:
        if strategy_filter:
            return f"\n❌ Strategie '{strategy_filter}' hat keine ausreichenden Daten (min. {MIN_TRADES_FOR_METRICS} geschlossene Trades)\n"
        return f"\n❌ Keine Strategie mit >= {MIN_TRADES_FOR_METRICS} geschlossenen Trades gefunden.\n"

    lines = []
    lines.append("=" * 70)
    lines.append("🎩 TRADEMIND — STRATEGY HEALTH REPORT")
    lines.append(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"   Strategien analysiert: {len(rows)}")
    lines.append("=" * 70)

    summary_rows = []

    for row in rows:
        strategy = row['strategy']
        trades = _load_trades_for_strategy(db, strategy)

        if not trades:
            continue

        # ── Metriken ──────────────────────────────────────────────────────────
        metrics = calculate_strategy_metrics(trades)

        # ── Signifikanz ───────────────────────────────────────────────────────
        sig = test_strategy_significance(trades)

        # ── Monte Carlo (nur bei >= 5 Trades sinnvoll) ───────────────────────
        mc = monte_carlo_simulation(trades, num_simulations=10000, future_trades=100)

        # ── Empfehlung ────────────────────────────────────────────────────────
        rec, rec_reason = _get_recommendation(metrics, sig)

        # ── Icons ─────────────────────────────────────────────────────────────
        rec_icon = {
            'KEEP':         '✅',
            'REVIEW':       '🟡',
            'KILL':         '💀',
            'INSUFFICIENT': '⚪',
        }.get(rec, '❓')

        pnl_sign = '+' if metrics['total_pnl'] >= 0 else ''

        lines.append(f"\n{'─'*70}")
        lines.append(f"{rec_icon} {strategy}  [{rec}]  —  {rec_reason}")
        lines.append(f"{'─'*70}")

        # Basis-Metriken
        lines.append(f"  Trades:      {metrics['total_trades']}  |  Win Rate: {metrics['win_rate']*100:.1f}%  |  Total P&L: {pnl_sign}{metrics['total_pnl']:,.0f}€")
        lines.append(f"  Avg Halte:   {metrics['avg_hold_days']:.1f} Tage  |  Best: {metrics['best_trade']:+.0f}€  |  Worst: {metrics['worst_trade']:+.0f}€")
        lines.append("")

        # Risiko-Metriken
        lines.append(f"  {'METRIKEN':<20}")
        lines.append(f"  {'Sharpe Ratio:':<22} {metrics['sharpe_ratio']:>8.3f}  {'✅' if metrics['sharpe_ratio'] > 1.0 else ('🟡' if metrics['sharpe_ratio'] > 0.5 else '🔴')}")
        lines.append(f"  {'Sortino Ratio:':<22} {metrics['sortino_ratio']:>8.3f}")
        lines.append(f"  {'Calmar Ratio:':<22} {metrics['calmar_ratio']:>8.3f}")
        lines.append(f"  {'Profit Factor:':<22} {metrics['profit_factor']:>8.3f}  {'✅' if metrics['profit_factor'] > 1.5 else ('🟡' if metrics['profit_factor'] > 1.0 else '🔴')}")
        lines.append(f"  {'Expected Value:':<22} {metrics['expected_value']:>+8.2f}€")
        lines.append(f"  {'Win/Loss Ratio:':<22} {metrics['win_loss_ratio']:>8.3f}")
        lines.append(f"  {'Max Drawdown:':<22} {metrics['max_drawdown_eur']:>+8.0f}€  ({metrics['max_drawdown_pct']:.1f}%,  {metrics['max_dd_duration_days']} Tage)")
        lines.append("")

        # Signifikanz
        lines.append(f"  {'SIGNIFIKANZ':<20}")
        if sig['verdict'] == 'ZU WENIG DATEN':
            lines.append(f"  ⚪ Zu wenig Daten ({sig['n_trades']} Trades, min. {MIN_TRADES_FOR_VERDICT} benötigt)")
        else:
            binom_flag = '✅' if sig['binom_p'] < 0.05 else ('🟡' if sig['binom_p'] < 0.20 else '🔴')
            t_flag     = '✅' if sig['t_test_p'] < 0.05 else ('🟡' if sig['t_test_p'] < 0.20 else '🔴')
            lines.append(f"  Binomial p-value:      {sig['binom_p']:.4f}  {binom_flag}")
            lines.append(f"  t-Test p-value:        {sig['t_test_p']:.4f}  {t_flag}")
            lines.append(f"  Bootstrap CI 95%:      [{sig['ci_95_lower']:+.2f}%,  {sig['ci_95_upper']:+.2f}%]")
            lines.append(f"  Verdict: {sig['verdict']}")
        lines.append("")

        # Monte Carlo
        if mc['n_source_trades'] >= 2:
            lines.append(f"  {'MONTE CARLO':<20}  ({mc['num_simulations']:,} Szenarien, {mc['future_trades']} Trades)")
            lines.append(f"  Median:            {mc['median_pnl']:>+9,.0f}€")
            lines.append(f"  Worst  5%:         {mc['worst_5pct']:>+9,.0f}€")
            lines.append(f"  Best   5%:         {mc['best_5pct']:>+9,.0f}€")
            lines.append(f"  Prob. profitabel:  {mc['prob_profitable']*100:>8.1f}%")
            lines.append(f"  Median Max DD:     {mc['median_max_dd']:>+9,.0f}€")
            lines.append(f"  Worst  5% DD:      {mc['worst_max_dd']:>+9,.0f}€")

        summary_rows.append((rec_icon, rec, strategy, metrics['total_trades'],
                              metrics['win_rate'], metrics['total_pnl'],
                              metrics['sharpe_ratio'], sig['binom_p'],
                              mc.get('prob_profitable', 0)))

    # ── Zusammenfassung ───────────────────────────────────────────────────────
    lines.append(f"\n{'='*70}")
    lines.append("📋 ZUSAMMENFASSUNG")
    lines.append(f"{'='*70}")
    lines.append(f"  {'':3} {'Strategie':<12} {'N':>5} {'WR%':>6} {'P&L':>10} {'Sharpe':>8} {'p-val':>7}  Verdict")
    lines.append(f"  {'─'*65}")

    for (icon, rec, strat, n, wr, pnl, sharpe, p_val, prob_p) in summary_rows:
        rec_short = {'KEEP': 'KEEP', 'REVIEW': 'REVIEW', 'KILL': '💀KILL', 'INSUFFICIENT': 'INSUFF'}.get(rec, rec)
        pnl_str = f"{pnl:+,.0f}€"
        lines.append(f"  {icon}  {strat:<12} {n:>5} {wr*100:>5.1f}% {pnl_str:>10} {sharpe:>8.2f} {p_val:>7.4f}  {rec_short}")

    # Kill-Liste
    kills = [s for (icon, rec, s, *_) in summary_rows if rec == 'KILL']
    reviews = [s for (icon, rec, s, *_) in summary_rows if rec == 'REVIEW']
    keeps = [s for (icon, rec, s, *_) in summary_rows if rec == 'KEEP']

    lines.append(f"\n  ✅ KEEP:    {', '.join(keeps) if keeps else 'keine'}")
    lines.append(f"  🟡 REVIEW:  {', '.join(reviews) if reviews else 'keine'}")
    lines.append(f"  💀 KILL:    {', '.join(kills) if kills else 'keine'}")
    lines.append(f"\n{'='*70}\n")

    return "\n".join(lines)
