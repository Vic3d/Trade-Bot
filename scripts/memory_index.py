#!/usr/bin/env python3
"""
P2.13 — Memory Index Builder
=============================
Erzeugt memory/INDEX.json mit {file, date, tickers[], strategies[], tags[], headline}
für jede Datei in memory/. Erlaubt schnelle Lookups: "Was wussten wir am 2026-03-15
über NVDA?" ohne 200 MD-Files zu lesen.

Lauf: täglich nach state-snapshot regeneration (z.B. um 23:30).
"""
import json, re
from pathlib import Path
from datetime import datetime, timezone

WS = Path(__file__).resolve().parent.parent
MEM = WS / 'memory'
INDEX = MEM / 'INDEX.json'

DATE_RE = re.compile(r'(\d{4}-\d{2}-\d{2})')
TICKER_RE = re.compile(r'\b([A-Z]{2,5}(?:\.[A-Z]{1,3})?)\b')
STRATEGY_RE = re.compile(r'\b(PS\d+|PT\d*|PM\d*|S\d+|DT\d+|AR-[A-Z]+)\b')

# Häufige englische Wörter / Phrasen die wie Ticker aussehen — Filter
TICKER_BLACKLIST = {
    'AND','THE','FOR','BUT','NOT','YOU','ARE','WAS','HAS','ITS','HIS','ALL',
    'CET','EUR','USD','GBP','CHF','VIX','DXY','GDP','CPI','API','LLM','URL',
    'PDF','CEO','CFO','MD','OK','YES','NO','TODO','FIXME','NEW','OLD','TOP',
    'SQL','JSON','HTML','CSS','HTTP','HTTPS','SSH','VPS','EU','US','UK','DE',
    'AI','ML','RL','HMM','EMA','RSI','MACD','ATR','SMA','PNL','WR','CRV',
    'DB','PR','OP','RE','MO','DI','MI','DO','FR','SA','SO','UTC','GMT',
    'IRA','MFN','BEAR','BULL','RISK','OFF','ON','TBD','NA','NS','HQ',
    'PS','PT','PM','DT','AR','OK','OPEN','CLOSE','HIGH','LOW','WIN','LOSS',
}


def parse_file(p: Path) -> dict:
    try:
        text = p.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return {}
    head = text[:300].splitlines()[0] if text else ''
    # Datum aus Filename oder erstem Vorkommen
    m = DATE_RE.search(p.name) or DATE_RE.search(text[:500])
    date = m.group(1) if m else ''
    # Ticker (gefiltert)
    raw_tickers = set(TICKER_RE.findall(text[:8000]))
    tickers = sorted(t for t in raw_tickers if t not in TICKER_BLACKLIST and len(t) >= 2)[:25]
    # Strategien
    strategies = sorted(set(STRATEGY_RE.findall(text)))[:15]
    # Tags aus Filename (nach Datum)
    tag_part = p.stem.replace(date, '').strip('-_ ')
    tags = [t for t in re.split(r'[-_]+', tag_part) if t and len(t) > 2][:8]
    return {
        'file': p.relative_to(WS).as_posix(),
        'date': date,
        'headline': head[:120],
        'tickers': tickers,
        'strategies': strategies,
        'tags': tags,
        'size': p.stat().st_size,
    }


def build_index() -> dict:
    files = sorted(MEM.glob('*.md'))
    entries = []
    for f in files:
        e = parse_file(f)
        if e:
            entries.append(e)
    # Sub-Verzeichnisse (z.B. deep_dives/)
    for f in MEM.rglob('*.md'):
        if f.parent == MEM:
            continue
        e = parse_file(f)
        if e:
            entries.append(e)
    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'count': len(entries),
        'entries': entries,
    }
    INDEX.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    return out


def query(ticker: str = '', strategy: str = '', date_from: str = '', date_to: str = '') -> list[dict]:
    """Einfache Query-API: filter by ticker/strategy/date-range."""
    if not INDEX.exists():
        build_index()
    data = json.loads(INDEX.read_text(encoding='utf-8'))
    res = []
    for e in data.get('entries', []):
        if ticker and ticker.upper() not in e.get('tickers', []):
            continue
        if strategy and strategy.upper() not in [s.upper() for s in e.get('strategies', [])]:
            continue
        d = e.get('date', '')
        if date_from and d and d < date_from:
            continue
        if date_to and d and d > date_to:
            continue
        res.append(e)
    return res


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--query':
        # CLI: python memory_index.py --query NVDA
        ticker = sys.argv[2] if len(sys.argv) > 2 else ''
        hits = query(ticker=ticker)
        print(f'{len(hits)} hits for ticker={ticker!r}')
        for h in hits[:50]:
            print(f"  {h['date']} | {h['file']} | {h['headline']}")
    else:
        out = build_index()
        try:
            print(f"[memory_index] indexed {out['count']} files -> {INDEX.relative_to(WS)}")
        except UnicodeEncodeError:
            print(f"[memory_index] indexed {out['count']} files")
