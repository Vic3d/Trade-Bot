#!/usr/bin/env python3.14
"""
Strategy Discovery — Autonome Strategie-Entwicklung
====================================================
Sucht selbstständig neue Thesen, verbessert bestehende Strategien,
und identifiziert Sektor-Rotation ohne Victor-Input.

Baumplan:
  1. NewsThemeScanner   — neue Themen in News ohne Strategie
  2. PatternMiner       — Gewinner-Muster aus eigenen Trades
  3. SectorRotationTracker — welche Sektoren laufen gerade?
  4. StrategyReporter   — Discord-Report + Datei

Läuft wöchentlich (Sa 14:00) via scheduler_daemon.py
"""

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS    = Path('/data/.openclaw/workspace')
DB    = WS / 'data' / 'trading.db'
DATA  = WS / 'data'
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))


# ── Bekannte Themen → aktive Strategien (um Duplikate zu vermeiden) ────────────

KNOWN_THEMES = {
    'iran', 'hormuz', 'houthi', 'opec', 'crude', 'brent', 'wti',      # PS1
    'tanker', 'vlcc', 'shipping lane', 'suez',                          # PS2
    'nato', 'defense spending', 'rheinmetall', 'ukraine', 'bundes',     # PS3/PS11
    'silver', 'silber', 'precious metal',                               # PS4/S4
    'fertilizer', 'dünger', 'potash', 'mosaic',                        # PS5
    'container', 'freight rate', 'zim',                                 # PS14
    'glp-1', 'novo nordisk', 'ozempic', 'wegovy',                      # PS_NVO
    'siemens', 'bmw', 'domestic',                                       # PS17/PS18
}

# Sektor → Bekannte Strategien
SECTOR_STRATEGY_MAP = {
    'energy':       'PS1',
    'defense':      'PS11',
    'materials':    'PS4',
    'shipping':     'PS14',
    'pharma':       'PS_NVO',
    'tech':         'S3',
    'agriculture':  'PS5',
    'industrials':  'PS17',
}

# Kandidaten-Ticker je Thema (für neue Thesen)
THEME_TICKER_MAP = {
    'nuclear':   [('CCJ', 'Cameco — Uran Produzent'),
                  ('NXE', 'NexGen Energy'),
                  ('UEC', 'Uranium Energy'),
                  ('UUUU', 'Energy Fuels')],
    'copper':    [('FCX', 'Freeport-McMoRan'),
                  ('SCCO', 'Southern Copper'),
                  ('TECK', 'Teck Resources')],
    'ai_infra':  [('DELL', 'Dell — AI Infrastructure'),
                  ('VRT', 'Vertiv — Cooling/Power'),
                  ('VST', 'Vistra — AI Power')],
    'rare_earth':[('MP', 'MP Materials'),
                  ('NOVN', 'Novonix'),
                  ('LYNAS.AX', 'Lynas Rare Earths')],
    'water':     [('AWK', 'American Water Works'),
                  ('XYL', 'Xylem'),
                  ('WTRG', 'Essential Utilities')],
    'cyber':     [('CRWD', 'CrowdStrike'),
                  ('PANW', 'Palo Alto'),
                  ('ZS',   'Zscaler')],
    'biotech':   [('MRNA', 'Moderna'),
                  ('BIIB', 'Biogen'),
                  ('REGN', 'Regeneron')],
    'india':     [('INDA', 'iShares India ETF'),
                  ('PIN',  'Invesco India ETF')],
    'battery':   [('LTHM', 'Livent — Lithium'),
                  ('ALB',  'Albemarle — Lithium'),
                  ('QS',   'QuantumScape — Solid State')],
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. NEWS THEME SCANNER
# ─────────────────────────────────────────────────────────────────────────────

def scan_news_themes(days: int = 14) -> list[dict]:
    """
    Clustert News-Headlines der letzten N Tage.
    Findet Themen die NICHT in KNOWN_THEMES sind.
    Schlägt neue Strategie-Kandidaten vor.
    """
    conn = sqlite3.connect(str(DB))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')

    rows = conn.execute("""
        SELECT headline, tickers FROM news_events
        WHERE created_at > ? AND headline IS NOT NULL
        ORDER BY id DESC
    """, (cutoff,)).fetchall()
    conn.close()

    if not rows:
        return []

    # Wort-Frequenz zählen (ohne Stopwords)
    STOPWORDS = {
        'the','a','an','in','on','at','to','of','for','is','are','was',
        'will','with','from','that','this','by','as','or','and','not',
        'has','have','its','be','it','he','she','they','we','you','but',
        'after','before','when','new','says','amid','over','up','down',
        'stock','shares','company','market','percent','million','billion',
        # Zu generisch für Thesen-Erkennung
        'trump','biden','president','says','report','week','year','quarter',
        'prices','returns','growth','outlook','results','earnings','sales',
        'investors','analysts','data','rate','rates','high','higher','lower',
        'reuters','bloomberg','news','media','times','street','wall','today',
        'global','world','index','fund','etf','corp','inc','llc','group',
        # Bereits bekannte Themen/Ticker
        'palantir','nvidia','microsoft','apple','tesla','amazon','google',
        'pltr','nvda','msft','aapl','tsla','amzn','goog',
        'israel','israeli','hamas','gaza','west','bank',  # schon in PS1-Kontext
        'energy','crude','petroleum',  # schon PS1
    }

    word_counter = Counter()
    bigram_counter = Counter()

    for headline, _ in rows:
        words = re.findall(r'\b[a-z]{4,}\b', headline.lower())
        filtered = [w for w in words if w not in STOPWORDS]
        word_counter.update(filtered)
        # Bigramme für Themen-Erkennung
        bigrams = [f"{filtered[i]} {filtered[i+1]}" for i in range(len(filtered)-1)]
        bigram_counter.update(bigrams)

    # Neue Themen finden (nicht in KNOWN_THEMES)
    new_themes = []
    all_phrases = {**{k: v for k, v in word_counter.most_common(50)},
                   **{k: v for k, v in bigram_counter.most_common(30)}}

    for phrase, count in sorted(all_phrases.items(), key=lambda x: -x[1]):
        if count < 5:
            continue
        if any(known in phrase for known in KNOWN_THEMES):
            continue
        # Kandidaten-Ticker dazu?
        matched_theme = None
        for theme_key in THEME_TICKER_MAP:
            if theme_key.replace('_', ' ') in phrase or phrase in theme_key:
                matched_theme = theme_key
                break

        # Auch ohne bekannte Ticker vorschlagen wenn frequent genug
        new_themes.append({
            'phrase': phrase,
            'count': count,
            'theme_key': matched_theme,
            'tickers': THEME_TICKER_MAP.get(matched_theme, []) if matched_theme else [],
        })

        if len(new_themes) >= 8:
            break

    return new_themes


# ─────────────────────────────────────────────────────────────────────────────
# 2. PATTERN MINER
# ─────────────────────────────────────────────────────────────────────────────

def mine_winner_patterns() -> dict:
    """
    Analysiert closed trades: Was haben Gewinner gemeinsam?
    Extrahiert Einstiegsregeln aus echten Trade-Daten.
    """
    conn = sqlite3.connect(str(DB))

    rows = conn.execute("""
        SELECT strategy, rsi_at_entry, vix_at_entry, hmm_regime,
               day_of_week, hour_of_entry, pnl_pct, pnl_eur,
               ma50_distance, atr_pct_at_entry
        FROM paper_portfolio
        WHERE status NOT IN ('OPEN')
    """).fetchall()

    conn.close()

    if len(rows) < 10:
        return {'error': 'Zu wenig Trades mit Features', 'count': len(rows)}

    winners = [r for r in rows if r[6] and r[6] > 0]
    losers  = [r for r in rows if r[6] and r[6] <= 0]

    def avg(lst, idx):
        vals = [r[idx] for r in lst if r[idx] is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    def regime_dist(lst):
        regimes = [r[3] for r in lst if r[3]]
        return dict(Counter(regimes).most_common(3))

    def strategy_wr(rows_list):
        strat_wins = defaultdict(lambda: [0, 0])
        for r in rows_list:
            strat_wins[r[0]][1] += 1
            if r[6] and r[6] > 0:
                strat_wins[r[0]][0] += 1
        return {s: round(w/t*100) for s, (w, t) in strat_wins.items() if t >= 3}

    rules = []

    # RSI-Regel
    w_rsi = avg(winners, 1)
    l_rsi = avg(losers, 1)
    if w_rsi and l_rsi:
        if w_rsi < l_rsi - 5:
            rules.append({
                'rule': f'RSI bei Winners: {w_rsi} vs. Losers: {l_rsi} → Entry unter RSI {round(w_rsi+3)} bevorzugen',
                'confidence': 'HIGH' if abs(w_rsi - l_rsi) > 10 else 'MEDIUM',
            })

    # Regime-Regel
    w_regimes = regime_dist(winners)
    rules.append({
        'rule': f'Regime-Verteilung Winners: {w_regimes}',
        'confidence': 'MEDIUM',
    })

    # Bester Entry-Wochentag
    day_wr = defaultdict(lambda: [0, 0])
    for r in rows:
        if r[4] is not None and r[6] is not None:
            day_wr[r[4]][1] += 1
            if r[6] > 0:
                day_wr[r[4]][0] += 1
    day_names = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    best_days = sorted(
        [(day_names[d], round(w/t*100) if t >= 3 else 0, t)
         for d, (w, t) in day_wr.items() if t >= 3],
        key=lambda x: -x[1]
    )
    if best_days:
        rules.append({
            'rule': f'Beste Entry-Tage: {best_days[:3]}',
            'confidence': 'LOW' if len(rows) < 50 else 'MEDIUM',
        })

    # Strategie Win-Rates
    strat_wr = strategy_wr(rows)
    top_strats = sorted(strat_wr.items(), key=lambda x: -x[1])[:5]
    rules.append({
        'rule': f'Beste Strategien: {top_strats}',
        'confidence': 'HIGH',
    })

    return {
        'total_trades': len(rows),
        'winners': len(winners),
        'losers': len(losers),
        'win_rate': round(len(winners) / len(rows) * 100),
        'avg_rsi_winners': w_rsi,
        'avg_rsi_losers': l_rsi,
        'rules': rules,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. SECTOR ROTATION TRACKER
# ─────────────────────────────────────────────────────────────────────────────

def track_sector_rotation() -> dict:
    """
    Analysiert Sektor-Performance der letzten 10 und 20 Tage.
    Identifiziert Outperformer → erhöht Conviction-Gewichte.
    """
    conn = sqlite3.connect(str(DB))

    try:
        rows = conn.execute("""
            SELECT sector, avg_return_10d, avg_return_20d, updated_at
            FROM sector_momentum
            ORDER BY avg_return_10d DESC
        """).fetchall()
    except Exception:
        rows = []

    conn.close()

    if not rows:
        # Fallback: aus paper_portfolio-Daten ableiten
        conn = sqlite3.connect(str(DB))
        rows2 = conn.execute("""
            SELECT sector, AVG(pnl_pct) avg_pnl, COUNT(*) cnt
            FROM paper_portfolio
            WHERE sector IS NOT NULL AND status != 'OPEN'
            GROUP BY sector ORDER BY avg_pnl DESC
        """).fetchall()
        conn.close()

        if not rows2:
            return {'outperformer': [], 'underperformer': [], 'source': 'none'}

        outperformer = [(r[0], round(r[1], 1), r[2]) for r in rows2 if r[1] and r[1] > 2 and r[2] >= 3]
        underperformer = [(r[0], round(r[1], 1), r[2]) for r in rows2 if r[1] and r[1] < -2 and r[2] >= 3]

        return {
            'outperformer': outperformer[:3],
            'underperformer': underperformer[:3],
            'recommendations': [
                f"Conviction +10 für {s} ({SECTOR_STRATEGY_MAP.get(s, '?')})"
                for s, _, _ in outperformer[:2]
            ],
            'source': 'paper_portfolio',
        }

    outperformer = [(r[0], round(r[1], 2)) for r in rows if r[1] and r[1] > 1]
    underperformer = [(r[0], round(r[1], 2)) for r in rows if r[1] and r[1] < -1]

    return {
        'outperformer': outperformer[:3],
        'underperformer': underperformer[:3],
        'recommendations': [
            f"Conviction +10 für {s} ({SECTOR_STRATEGY_MAP.get(s, '?')})"
            for s, _ in outperformer[:2]
        ],
        'source': 'sector_momentum',
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. STRATEGY REPORTER
# ─────────────────────────────────────────────────────────────────────────────

def build_report(themes, patterns, sectors) -> str:
    lines = []
    lines.append("🔍 **TradeMind — Strategy Discovery Report**")
    lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')} MEZ\n")

    # Neue Themen
    lines.append("**📰 Neue Themen in den News (letzte 14 Tage):**")
    actionable = [t for t in themes if t['tickers']]
    if actionable:
        for t in actionable[:4]:
            tickers_str = ', '.join(x[0] for x in t['tickers'][:3])
            lines.append(f"  → **{t['phrase']}** ({t['count']}x) — Kandidaten: {tickers_str}")
    else:
        lines.append("  Keine neuen Themen mit Ticker-Kandidaten gefunden.")

    if themes and not actionable:
        top = themes[:3]
        lines.append("  Häufige Begriffe ohne Ticker: " + ', '.join(f"{t['phrase']} ({t['count']}x)" for t in top))

    lines.append("")

    # Pattern-Miner Ergebnisse
    lines.append("**📊 Gewinner-Muster aus eigenen Trades:**")
    if 'error' in patterns:
        lines.append(f"  ⚠️ {patterns['error']} ({patterns['count']} Trades)")
    else:
        lines.append(f"  Basis: {patterns['total_trades']} Trades | {patterns['win_rate']}% Win-Rate")
        for rule in patterns.get('rules', []):
            conf = rule['confidence']
            icon = '🟢' if conf == 'HIGH' else ('🟡' if conf == 'MEDIUM' else '⬜')
            lines.append(f"  {icon} {rule['rule']}")

    lines.append("")

    # Sektor-Rotation
    lines.append("**🔄 Sektor-Rotation:**")
    if sectors['outperformer']:
        out_str = ', '.join(f"{s[0]} (+{s[1]}%)" if len(s) > 1 else s[0] for s in sectors['outperformer'])
        lines.append(f"  🟢 Outperformer: {out_str}")
    if sectors['underperformer']:
        under_str = ', '.join(f"{s[0]} ({s[1]}%)" if len(s) > 1 else s[0] for s in sectors['underperformer'])
        lines.append(f"  🔴 Underperformer: {under_str}")
    for rec in sectors.get('recommendations', []):
        lines.append(f"  💡 {rec}")

    lines.append("")
    lines.append("**📋 Empfehlung:**")

    recs = []
    if actionable:
        top_theme = actionable[0]
        recs.append(f"Neues Theme '{top_theme['phrase']}' prüfen — {', '.join(x[0] for x in top_theme['tickers'][:2])} als Paper-Trade-Kandidaten")
    if patterns.get('avg_rsi_winners') and patterns.get('avg_rsi_losers'):
        recs.append(f"Entry-RSI auf {round(patterns['avg_rsi_winners']+3)} begrenzen für höhere Win-Rate")
    if sectors['outperformer']:
        recs.append(f"Sektor {sectors['outperformer'][0][0]} weiter gewichten")

    for r in recs[:3]:
        lines.append(f"  → {r}")

    if not recs:
        lines.append("  Keine konkreten Handlungsempfehlungen diese Woche.")

    return '\n'.join(lines)


def save_to_file(themes, patterns, sectors, report_text: str):
    """Speichert Ergebnisse in Dateien."""
    # JSON-Outputs
    (DATA / 'theme_candidates.json').write_text(json.dumps(themes, indent=2, ensure_ascii=False))
    (DATA / 'pattern_rules.json').write_text(json.dumps(patterns, indent=2, ensure_ascii=False))
    (DATA / 'sector_weights.json').write_text(json.dumps(sectors, indent=2, ensure_ascii=False))

    # Markdown-Log
    log_path = WS / 'memory' / 'strategy-discovery.md'
    entry = f"\n\n---\n## {datetime.now().strftime('%Y-%m-%d')}\n\n{report_text}\n"

    if log_path.exists():
        existing = log_path.read_text()
        log_path.write_text(existing + entry)
    else:
        log_path.write_text(f"# Strategy Discovery Log\n{entry}")


def run():
    """Hauptloop — alle 3 Module + Report."""
    print("[strategy_discovery] Start...")

    print("  → NewsThemeScanner...")
    themes = scan_news_themes(days=14)
    print(f"     {len(themes)} neue Themen gefunden")

    print("  → PatternMiner...")
    patterns = mine_winner_patterns()
    print(f"     {patterns.get('total_trades', 0)} Trades analysiert")

    print("  → SectorRotationTracker...")
    sectors = track_sector_rotation()
    print(f"     Outperformer: {sectors['outperformer']}")

    report = build_report(themes, patterns, sectors)
    save_to_file(themes, patterns, sectors, report)

    # Discord-Nachricht
    try:
        from discord_sender import send
        send(report[:1900])
        print("  → Discord-Report gesendet")
    except Exception as e:
        print(f"  → Discord-Fehler: {e}")
        print(report)

    print("[strategy_discovery] Fertig.")
    return {'themes': len(themes), 'patterns': patterns, 'sectors': sectors}


if __name__ == '__main__':
    run()
