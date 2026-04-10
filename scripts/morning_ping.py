#!/usr/bin/env python3.13
"""
morning_ping.py — 07:00 Uhr Morgen-Briefing für Victor
Aktuelle Nachrichten + Portfolio-Stand + Backtest-Status
Albert | TradeMind v2
"""
import urllib.request
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

WS = Path('/data/.openclaw/workspace')


def send_discord(msg: str):
    cfg = Path('/data/.openclaw/openclaw.json')
    token = json.loads(cfg.read_text())['channels']['discord']['token']
    channel = '1492225799062032484'
    chunks = [msg[i:i+1900] for i in range(0, len(msg), 1900)]
    for chunk in chunks:
        data = json.dumps({'content': chunk}).encode()
        req = urllib.request.Request(
            f'https://discord.com/api/v10/channels/{channel}/messages',
            data=data,
            headers={
                'Authorization': f'Bot {token}',
                'Content-Type': 'application/json',
                'User-Agent': 'TradeMind/2.0',
            }
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f'Discord error: {e}')


def fetch_rss(url: str, max_items: int = 6) -> list:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml = resp.read()
        root = ElementTree.fromstring(xml)
        items = []
        for item in root.findall('.//item')[:max_items]:
            title = item.findtext('title', '').strip()
            if title and len(title) > 10:
                items.append(title)
        if not items:
            ns = {'a': 'http://www.w3.org/2005/Atom'}
            for entry in root.findall('a:entry', ns)[:max_items]:
                title = entry.findtext('a:title', '', ns).strip()
                if title and len(title) > 10:
                    items.append(title)
        return items
    except Exception:
        return []


def get_news_section() -> tuple:
    feeds = [
        ('Reuters Business',  'https://feeds.reuters.com/reuters/businessNews'),
        ('Reuters Finance',   'https://feeds.reuters.com/reuters/financialsNews'),
        ('Yahoo Finance',     'https://finance.yahoo.com/news/rssindex'),
        ('WSJ Markets',       'https://feeds.a.dj.com/rss/RSSMarketsMain.xml'),
    ]

    all_headlines = []
    for name, url in feeds:
        items = fetch_rss(url, max_items=5)
        all_headlines.extend(items[:4])

    # Deduplizieren
    seen = set()
    unique = []
    for h in all_headlines:
        key = h[:55].lower()
        if key not in seen:
            seen.add(key)
            unique.append(h)

    lines = ['**AKTUELLE NACHRICHTENLAGE**']
    if unique:
        for h in unique[:10]:
            lines.append(f'  • {h[:120]}')
    else:
        lines.append('  • Keine RSS-Feeds erreichbar')

    return '\n'.join(lines), unique


def get_thesis_hits(headlines: list) -> str:
    thesis_keywords = {
        'S2/PS17 EU Defense':   ['defense', 'nato', 'military', 'ruestung', 'rheinmetall', 'airbus', 'saab', 'bundeswehr'],
        'PS18 Trade War':       ['tariff', 'trade war', 'zoll', 'trump', 'china trade', 'import duty'],
        'PS19 Dollar-Schwaeche':['dollar', 'dxy', 'fed pivot', 'emerging market', 'usd falls', 'weak dollar'],
        'PS20 US Rezession':    ['recession', 'gdp', 'unemployment', 'layoffs', 'ism manufacturing', 'jobless'],
        'PS4 Healthcare':       ['healthcare', 'pharma', 'fda', 'biotech', 'drug approval'],
        'PS16 AI Infra':        ['nvidia', 'ai infrastructure', 'semiconductor', 'data center', 'chip'],
    }
    combined = ' '.join(headlines).lower()
    hits = []
    for thesis, kws in thesis_keywords.items():
        matched = [k for k in kws if k in combined]
        if matched:
            hits.append(f'  🎯 **{thesis}** — {", ".join(matched[:3])}')
    if not hits:
        return ''
    return '**THESEN IN DEN NEWS:**\n' + '\n'.join(hits)


def get_portfolio_section() -> str:
    conn = sqlite3.connect(str(WS / 'data' / 'trading.db'))
    try:
        open_count = conn.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'"
        ).fetchone()[0]
        fund = dict(conn.execute('SELECT key, value FROM paper_fund').fetchall())
        cash  = float(fund.get('current_cash', 0))
        start = float(fund.get('starting_capital', 25000))
        pnl   = float(fund.get('total_realized_pnl', 0))
        new_t = conn.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE entry_date >= date('now','-1 day')"
        ).fetchone()[0]
        lab_t = conn.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE entry_date >= date('now','-1 day') AND notes LIKE '%LAB_MODE%'"
        ).fetchone()[0]
    finally:
        conn.close()
    perf = (cash - start) / start * 100
    return (
        f'**PORTFOLIO**\n'
        f'  Cash: {cash:.0f}€  |  Realisiert: {pnl:+.0f}€  |  Performance: {perf:+.1f}%\n'
        f'  Offene Positionen: {open_count}  |  Neue Trades (24h): {new_t} (davon Lab: {lab_t})'
    )


def get_backtest_section() -> str:
    bt_file = WS / 'data' / 'backtest_v2_results.json'
    bt_log  = WS / 'data' / 'backtest_v2.log'

    result = subprocess.run(
        ['pgrep', '-f', 'backtest_engine_v2'],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        last = ''
        if bt_log.exists():
            lines = bt_log.read_text().strip().split('\n')
            last = lines[-1][:80] if lines else ''
        return f'⏳ **Backtest läuft noch...**\n  Zuletzt: {last}'

    if bt_file.exists():
        try:
            data = json.loads(bt_file.read_text())
            total = data.get('total_trades', '?')
            wr    = data.get('win_rate_pct', 0)
            pf    = data.get('profit_factor', 0)
            best  = data.get('best_strategy', '?')
            worst = data.get('worst_strategy', '?')
            return (
                f'✅ **BACKTEST FERTIG**\n'
                f'  {total} simulierte Trades  |  Win-Rate: {wr:.0f}%  |  Profit Factor: {pf:.2f}\n'
                f'  Beste Strategie: {best}  |  Schwächste: {worst}'
            )
        except Exception:
            pass

    if bt_log.exists():
        last = bt_log.read_text().strip().split('\n')[-1][:100]
        return f'📊 Backtest-Log: {last}'

    return '📊 Backtest: noch keine Daten'


def main():
    now = datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')
    sep = '━' * 34

    news_text, raw_headlines = get_news_section()
    thesis_text  = get_thesis_hits(raw_headlines)
    portfolio    = get_portfolio_section()
    backtest     = get_backtest_section()

    parts = [
        f'☀️ **GUTEN MORGEN, VICTOR!** — {now} UTC',
        sep,
        f'📰 {news_text}',
    ]

    if thesis_text:
        parts += ['', f'🧠 {thesis_text}']

    parts += [
        sep,
        f'💼 {portfolio}',
        sep,
        f'🔬 {backtest}',
        sep,
        '💬 Bereit für den Tag — was steht an?',
        '— Albert (TradeMind)',
    ]

    full_msg = '\n'.join(parts)
    print(full_msg)
    send_discord(full_msg)


if __name__ == '__main__':
    main()
