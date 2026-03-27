#!/usr/bin/env python3
"""
generate_dashdata.py — Builds fresh api/dashdata.js from all data sources.
Run from workspace root: python3 scripts/generate_dashdata.py
"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime

WORKSPACE = Path(__file__).parent.parent
DB_PATH = WORKSPACE / 'data' / 'trading.db'
OUTPUT = WORKSPACE / 'api' / 'dashdata.js'


def safe_read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception as e:
        print(f"  WARN: {path} not found/invalid: {e}")
        return default if default is not None else {}


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_total_stats(conn):
    rows = conn.execute("SELECT status, pnl_eur FROM trades").fetchall()
    trades = len([r for r in rows if r['status'] in ('WIN', 'LOSS')])
    wins = len([r for r in rows if r['status'] == 'WIN'])
    losses = len([r for r in rows if r['status'] == 'LOSS'])
    open_count = len(conn.execute("SELECT 1 FROM trades WHERE status='OPEN'").fetchall())
    total_pnl = sum(r['pnl_eur'] or 0 for r in rows if r['status'] in ('WIN', 'LOSS'))
    win_rate = round(wins / trades * 100, 1) if trades > 0 else 0
    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_pnl": round(total_pnl, 2),
        "open_count": open_count
    }


def get_dt_stats(conn):
    rows = conn.execute("SELECT strategy, status, pnl_eur FROM trades").fetchall()
    stats = {}
    for r in rows:
        s = r['strategy'] or 'unknown'
        if s not in stats:
            stats[s] = {'trades': 0, 'wins': 0, 'losses': 0, 'open': 0, 'pnl': 0.0}
        if r['status'] in ('WIN', 'LOSS'):
            stats[s]['trades'] += 1
            if r['status'] == 'WIN':
                stats[s]['wins'] += 1
            else:
                stats[s]['losses'] += 1
            stats[s]['pnl'] += r['pnl_eur'] or 0
        elif r['status'] == 'OPEN':
            stats[s]['open'] += 1
    for s in stats:
        t = stats[s]['trades']
        stats[s]['pnl'] = round(stats[s]['pnl'], 2)
        stats[s]['wr'] = round(stats[s]['wins'] / t * 100, 1) if t > 0 else 0
    return stats


def get_recent_dt(conn, limit=30):
    try:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            # Convert any non-serializable to string
            for k, v in d.items():
                if v is not None and not isinstance(v, (int, float, str, bool, list, dict)):
                    d[k] = str(v)
            result.append(d)
        return result
    except Exception as e:
        print(f"  WARN: recent_dt error: {e}")
        return []


def get_paper_positions(conn):
    try:
        rows = conn.execute(
            "SELECT * FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"  WARN: paper_portfolio error: {e}")
        return []


def get_performance(conn):
    try:
        rows = conn.execute(
            "SELECT exit_date, pnl_eur FROM trades WHERE status IN ('WIN','LOSS') AND exit_date IS NOT NULL ORDER BY exit_date"
        ).fetchall()
        cumulative = 0
        equity_curve = []
        for r in rows:
            cumulative += r['pnl_eur'] or 0
            equity_curve.append({
                "date": str(r['exit_date'])[:10],
                "pnl": round(r['pnl_eur'] or 0, 2),
                "cumulative_pnl": round(cumulative, 2)
            })

        # Best and worst trades
        all_closed = conn.execute(
            "SELECT ticker, strategy, pnl_eur, pnl_pct, entry_date, exit_date FROM trades WHERE status IN ('WIN','LOSS') ORDER BY pnl_eur DESC"
        ).fetchall()
        best = [dict(r) for r in all_closed[:5]]
        worst = [dict(r) for r in all_closed[-5:]]

        # Monthly P&L
        monthly = {}
        for r in rows:
            if r['exit_date']:
                month = str(r['exit_date'])[:7]
                monthly[month] = round(monthly.get(month, 0) + (r['pnl_eur'] or 0), 2)
        monthly_pnl = [{"month": k, "pnl": v} for k, v in sorted(monthly.items())]

        # Strategy comparison
        strat_rows = conn.execute(
            "SELECT strategy, status, pnl_eur FROM trades WHERE status IN ('WIN','LOSS')"
        ).fetchall()
        strat_comp = {}
        for r in strat_rows:
            s = r['strategy'] or 'unknown'
            if s not in strat_comp:
                strat_comp[s] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
            strat_comp[s]['trades'] += 1
            if r['status'] == 'WIN':
                strat_comp[s]['wins'] += 1
            strat_comp[s]['pnl'] += r['pnl_eur'] or 0
        strategy_comparison = {
            s: {
                'trades': v['trades'],
                'wins': v['wins'],
                'pnl': round(v['pnl'], 2),
                'wr': round(v['wins'] / v['trades'] * 100, 1) if v['trades'] > 0 else 0
            }
            for s, v in strat_comp.items()
        }

        return {
            "equity_curve": equity_curve,
            "best_trades": best,
            "worst_trades": worst,
            "monthly_pnl": monthly_pnl,
            "strategy_comparison": strategy_comparison
        }
    except Exception as e:
        print(f"  WARN: performance error: {e}")
        return {"equity_curve": [], "best_trades": [], "worst_trades": [], "monthly_pnl": [], "strategy_comparison": {}}


def get_learning(conn):
    try:
        rows = conn.execute(
            "SELECT setup_type, geo_theme, status, pnl_eur, pnl_pct FROM trades WHERE status IN ('WIN','LOSS')"
        ).fetchall()

        # Setup performance
        setup_perf = {}
        for r in rows:
            st = r['setup_type'] or 'unknown'
            if st not in setup_perf:
                setup_perf[st] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
            setup_perf[st]['trades'] += 1
            if r['status'] == 'WIN':
                setup_perf[st]['wins'] += 1
            setup_perf[st]['pnl'] += r['pnl_eur'] or 0

        # Theme performance
        theme_perf = {}
        for r in rows:
            gt = r['geo_theme'] or 'unknown'
            if gt not in theme_perf:
                theme_perf[gt] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
            theme_perf[gt]['trades'] += 1
            if r['status'] == 'WIN':
                theme_perf[gt]['wins'] += 1
            theme_perf[gt]['pnl'] += r['pnl_eur'] or 0

        # VIX performance (try vix_zone column, fallback to vix_at_entry ranges)
        vix_perf = {}
        try:
            vix_rows = conn.execute(
                "SELECT vix_at_entry, status, pnl_eur FROM trades WHERE status IN ('WIN','LOSS')"
            ).fetchall()
            for r in vix_rows:
                vix = r['vix_at_entry']
                if vix is None:
                    zone = 'unknown'
                elif vix < 15:
                    zone = 'low (<15)'
                elif vix < 20:
                    zone = 'normal (15-20)'
                elif vix < 30:
                    zone = 'elevated (20-30)'
                else:
                    zone = 'high (>30)'
                if zone not in vix_perf:
                    vix_perf[zone] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
                vix_perf[zone]['trades'] += 1
                if r['status'] == 'WIN':
                    vix_perf[zone]['wins'] += 1
                vix_perf[zone]['pnl'] += r['pnl_eur'] or 0
        except Exception:
            pass

        # Normalize helpers
        def norm(d):
            return {
                k: {
                    'trades': v['trades'],
                    'wins': v['wins'],
                    'pnl': round(v['pnl'], 2),
                    'wr': round(v['wins'] / v['trades'] * 100, 1) if v['trades'] > 0 else 0
                }
                for k, v in d.items()
            }

        # Lessons from DB
        lesson_rows = conn.execute(
            "SELECT ticker, lessons, exit_date FROM trades WHERE lessons IS NOT NULL AND lessons != '' ORDER BY id DESC LIMIT 20"
        ).fetchall()
        lessons = [{"ticker": r['ticker'], "lesson": r['lessons'], "date": str(r['exit_date'])[:10] if r['exit_date'] else ""} for r in lesson_rows]

        return {
            "setup_performance": norm(setup_perf),
            "theme_performance": norm(theme_perf),
            "vix_performance": norm(vix_perf),
            "lessons": lessons
        }
    except Exception as e:
        print(f"  WARN: learning error: {e}")
        return {"setup_performance": {}, "theme_performance": {}, "vix_performance": {}, "lessons": []}


def main():
    print("=== generate_dashdata.py ===")

    # --- trading_config.json ---
    print("Loading trading_config.json...")
    cfg = safe_read_json(WORKSPACE / 'trading_config.json', {})

    # Open positions
    open_pos = []
    for ticker, pos in cfg.get('positions', {}).items():
        if pos.get('status') != 'CLOSED':
            p = dict(pos)
            p['ticker'] = ticker
            if 'entry_eur' in p: p['entry'] = p.pop('entry_eur')
            if 'stop_eur' in p: p['stop'] = p.pop('stop_eur')
            if 'targets_eur' in p: p['targets'] = p.pop('targets_eur')
            open_pos.append(p)

    # Closed positions
    closed_pos = []
    for ticker, pos in cfg.get('closed_positions', {}).items():
        p = dict(pos)
        p['ticker'] = ticker
        if 'entry_eur' in p: p['entry'] = p.pop('entry_eur')
        if 'exit_eur' in p: p['exit'] = p.pop('exit_eur')
        closed_pos.append(p)

    print(f"  Positions: {len(open_pos)} open, {len(closed_pos)} closed")

    # Strategies from trading_config.json (list format already)
    strats_cfg = cfg.get('strategies', [])
    if isinstance(strats_cfg, list):
        strategies_list = strats_cfg  # Already in correct format
    else:
        # Handle dict format (fallback)
        strategies_list = []
        for sid, s in strats_cfg.items():
            strategies_list.append({
                "id": sid,
                "name": s.get("name", sid),
                "status": s.get("status_emoji", s.get("status", "🟡")),
                "conviction": s.get("conviction", "Mittel"),
                "tickers": s.get("tickers", []),
                "desc": s.get("thesis", s.get("desc", "")),
                "color": s.get("color", "#06b6d4")
            })

    # strats_full from data/strategies.json (richer data)
    strats_full = {}
    strats_data = safe_read_json(WORKSPACE / 'data' / 'strategies.json', {})
    if isinstance(strats_data, dict):
        for sid, s in strats_data.items():
            strats_full[sid] = {
                "name": s.get("name", sid),
                "thesis": s.get("thesis", ""),
                "entry_trigger": s.get("entry_trigger", ""),
                "kill_trigger": s.get("kill_trigger", ""),
                "health": s.get("health", ""),
                "status": s.get("status", ""),
                "performance": s.get("performance", {})
            }

    print(f"  Strategies: {len(strategies_list)} list, {len(strats_full)} full")

    # --- data/current_regime.json ---
    print("Loading regime...")
    regime = safe_read_json(WORKSPACE / 'data' / 'current_regime.json', {})

    # --- data/dna.json ---
    print("Loading DNA...")
    dna = safe_read_json(WORKSPACE / 'data' / 'dna.json', {})

    # --- data/news_cache.json ---
    print("Loading news...")
    news_raw = safe_read_json(WORKSPACE / 'data' / 'news_cache.json', [])
    if isinstance(news_raw, list):
        news = news_raw[:50]  # limit
    elif isinstance(news_raw, dict):
        news = news_raw.get('articles', news_raw.get('news', []))[:50]
    else:
        news = []

    # --- data/backtest_results.json ---
    print("Loading backtest...")
    backtest = safe_read_json(WORKSPACE / 'data' / 'backtest_results.json', {})

    # --- data/risk.json ---
    print("Loading risk...")
    risk_data = safe_read_json(WORKSPACE / 'data' / 'risk.json', {})

    # --- data/signals.json ---
    print("Loading signals...")
    signals_data = safe_read_json(WORKSPACE / 'data' / 'signals.json', {})
    if isinstance(signals_data, list):
        sigs = signals_data[:20]
        signals = {
            "signals": sigs,
            "stats": {"total": len(sigs), "long": len([s for s in sigs if s.get('direction') == 'LONG']), "short": len([s for s in sigs if s.get('direction') == 'SHORT'])}
        }
    elif isinstance(signals_data, dict):
        sigs = signals_data.get('signals', [])[:20]
        signals = {
            "signals": sigs,
            "stats": signals_data.get('stats', {"total": len(sigs), "long": 0, "short": 0})
        }
    else:
        signals = {"signals": [], "stats": {"total": 0, "long": 0, "short": 0}}

    # --- data/sentiment.json ---
    print("Loading sentiment...")
    sentiment_data = safe_read_json(WORKSPACE / 'data' / 'sentiment.json', {})
    if isinstance(sentiment_data, dict):
        sentiment = {
            "portfolio_score": sentiment_data.get('portfolio_score', 0),
            "results": sentiment_data.get('results', sentiment_data)
        }
    else:
        sentiment = {"portfolio_score": 0, "results": {}}

    # --- SQLite DB ---
    print("Loading DB stats...")
    try:
        conn = get_conn()

        total_stats = get_total_stats(conn)
        print(f"  Total stats: {total_stats['trades']} trades, {total_stats['total_pnl']} EUR P&L")

        dt_stats = get_dt_stats(conn)
        print(f"  DT stats: {len(dt_stats)} strategies")

        recent_dt = get_recent_dt(conn)
        print(f"  Recent trades: {len(recent_dt)}")

        paper = get_paper_positions(conn)
        print(f"  Paper positions: {len(paper)}")

        performance = get_performance(conn)
        print(f"  Performance: {len(performance['equity_curve'])} equity points")

        learning = get_learning(conn)
        print(f"  Learning: {len(learning['lessons'])} lessons")

        conn.close()
    except Exception as e:
        print(f"  ERROR: DB failed: {e}")
        total_stats = {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0, "open_count": 0}
        dt_stats = {}
        recent_dt = []
        paper = []
        performance = {"equity_curve": [], "best_trades": [], "worst_trades": [], "monthly_pnl": [], "strategy_comparison": {}}
        learning = {"setup_performance": {}, "theme_performance": {}, "vix_performance": {}, "lessons": []}

    # --- Build risk block ---
    risk = {
        "circuit_breaker": risk_data.get('circuit_breaker', {}),
        "overall_score": risk_data.get('overall_score', 0),
        "sector_exposure": risk_data.get('sector_exposure', {}),
        "correlation_warnings": risk_data.get('correlation_warnings', []),
        "exposure": {
            "open_positions": len(open_pos),
            "total_invested": sum(p.get('size_eur', 0) or 0 for p in open_pos)
        },
        "stress_tests": risk_data.get('stress_tests', {}),
        "correlations": cfg.get('correlations', {})
    }

    # --- Assemble D object ---
    D = {
        "total_stats": total_stats,
        "positions": {"open": open_pos, "closed": closed_pos},
        "strategies": strategies_list,
        "strats_full": strats_full,
        "watchlist": cfg.get('watchlist', []),
        "earnings": cfg.get('earnings', []),
        "macro_events": cfg.get('macro_events', []),
        "sector_map": cfg.get('sector_map', {}),
        "correlations": cfg.get('correlations', {}),
        "regime": regime,
        "dna": dna,
        "dt_stats": dt_stats,
        "recent_dt": recent_dt,
        "paper": paper,
        "performance": performance,
        "learning": learning,
        "backtest": backtest,
        "news": news,
        "signals": signals,
        "sentiment": sentiment,
        "risk": risk,
        "_generated": datetime.now().isoformat()
    }

    # --- Serialize ---
    print("Serializing to JSON...")
    json_str = json.dumps(D, default=str, ensure_ascii=False)

    # --- Write dashdata.js ---
    out = f'const D = {json_str};\nmodule.exports = (req, res) => {{\n  res.setHeader("Content-Type", "application/json; charset=utf-8");\n  res.setHeader("Cache-Control", "no-store");\n  res.setHeader("Access-Control-Allow-Origin", "*");\n  return res.status(200).json(D);\n}};\n'

    OUTPUT.write_text(out, encoding='utf-8')

    # --- Summary ---
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"\n✅ Written to {OUTPUT} ({size_kb:.1f} KB)")
    print(f"   Keys: {sorted(D.keys())}")
    print(f"   Positions open: {len(open_pos)}, closed: {len(closed_pos)}")
    print(f"   Strategies: {len(strategies_list)}")
    print(f"   Recent trades: {len(recent_dt)}")
    print(f"   News items: {len(news)}")
    print(f"   Equity curve points: {len(performance['equity_curve'])}")

    # Quick JSON validation
    try:
        reparsed = json.loads(json_str)
        print(f"   JSON valid ✅ ({len(reparsed)} keys)")
    except Exception as e:
        print(f"   JSON INVALID ❌: {e}")


if __name__ == '__main__':
    main()
