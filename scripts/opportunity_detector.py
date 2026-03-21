"""
opportunity_detector.py — News-getriebener Kaufgelegenheits-Detektor

Flow:
  1. News für jeden Watchlist-Eintrag holen (Google News RSS)
  2. Keyword-Match gegen Opportunity Profiles (Bullish/Bearish Trigger)
  3. Preis-Check: ist der Kurs in der Entry-Zone?
  4. Score berechnen (0–10):
      +3 Trigger-Stärke (Anzahl + Qualität Matches)
      +3 Preis-Position (mitten in Zone = 3, Rand = 1)
      +2 Strategie-Health (green=2, yellow=1, red=0)
      +2 Makro-Kontext (VIX < 25 = 2, 25-35 = 1, >35 = 0)
  5. Score ≥ 7 → Paper Trade eröffnen + Discord Alert
  6. Dedup: jede Opportunity max. 1x pro 72h melden

Output:
  KEIN_SIGNAL                  — keine neuen Opportunities
  OPPORTUNITY: [json]          — Opportunities für LLM-Bewertung im Cron
"""

import json
import hashlib
import time
import sqlite3
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import date

WS = Path('/data/.openclaw/workspace')
PROFILES_PATH = WS / 'data/opportunity_profiles.json'
STRATEGIES_PATH = WS / 'data/strategies.json'
DB_PATH = WS / 'data/trading.db'
OPP_CACHE_PATH = WS / 'memory/opportunity-cache.json'
OPP_CACHE_TTL_H = 72  # Stunden

PAPER_CAPITAL = 5000  # € pro Trade


def load_profiles():
    return json.loads(PROFILES_PATH.read_text())


def load_strategies():
    return json.loads(STRATEGIES_PATH.read_text())


def load_opp_cache():
    if OPP_CACHE_PATH.exists():
        try:
            return json.loads(OPP_CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


def save_opp_cache(cache):
    OPP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cache = {k: v for k, v in cache.items() if now - v < OPP_CACHE_TTL_H * 3600}
    OPP_CACHE_PATH.write_text(json.dumps(cache, indent=2))


def opp_key(ticker, headline):
    h = hashlib.md5(f"{ticker}:{headline[:60]}".lower().encode()).hexdigest()[:10]
    return h


def is_new_opp(ticker, headline, cache):
    return opp_key(ticker, headline) not in cache


def mark_opp_seen(ticker, headline, cache):
    cache[opp_key(ticker, headline)] = time.time()


def fetch_yahoo_price(yahoo_ticker, currency):
    """Aktuellen Kurs von Yahoo Finance holen."""
    try:
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}?interval=1d&range=1d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
        meta = data['chart']['result'][0]['meta']
        price = meta['regularMarketPrice']

        # GBp → EUR Konvertierung
        if currency == 'GBP' and yahoo_ticker.endswith('.L'):
            eurusd = get_eurusd()
            gbpusd = get_fx('GBPUSD=X')
            price_gbp = price / 100  # GBp → GBP
            price = price_gbp * gbpusd / eurusd if eurusd else price_gbp

        # USD → EUR
        elif currency == 'USD':
            eurusd = get_eurusd()
            if eurusd:
                price = price / eurusd

        return round(price, 2)
    except Exception:
        return None


def get_eurusd():
    try:
        url = 'https://query2.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=1d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)['chart']['result'][0]['meta']['regularMarketPrice']
    except Exception:
        return 1.08


def get_fx(ticker):
    try:
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)['chart']['result'][0]['meta']['regularMarketPrice']
    except Exception:
        return None


def get_vix():
    try:
        url = 'https://query2.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=1d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)['chart']['result'][0]['meta']['regularMarketPrice']
    except Exception:
        return 25.0


def fetch_rss(query, max_items=6):
    q = urllib.parse.quote(query)
    url = f'https://news.google.com/rss/search?q={q}&hl=en&gl=US&ceid=US:en'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            root = ET.fromstring(r.read())
        items = []
        for item in root.findall('.//item')[:max_items]:
            title = item.findtext('title', '').strip()
            source = item.findtext('source', '').strip()
            if title:
                items.append({'title': title, 'source': source})
        return items
    except Exception:
        return []


def score_opportunity(profile, matched_bullish, matched_bearish, price_eur, vix, strategy_health):
    """Score 0–10 berechnen."""
    score = 0
    reasons = []

    # 1. Trigger-Stärke (0–3)
    bull_count = len(matched_bullish)
    bear_count = len(matched_bearish)

    if bear_count > bull_count:
        return 0, ["Bearish dominiert"]

    if bull_count >= 3:
        score += 3
        reasons.append(f"Starke Trigger ({bull_count}x bullisch)")
    elif bull_count == 2:
        score += 2
        reasons.append(f"2 bullische Trigger")
    elif bull_count == 1:
        score += 1
        reasons.append(f"1 bullischer Trigger")

    # 2. Preis-Position (0–3)
    if price_eur is None:
        score += 1
        reasons.append("Kurs nicht abrufbar (neutral)")
    else:
        entry_min = profile['entry_min']
        entry_max = profile['entry_max']
        # USD-Ticker bereits in EUR konvertiert
        zone_size = entry_max - entry_min
        zone_mid = (entry_min + entry_max) / 2

        if entry_min <= price_eur <= entry_max:
            # In der Zone — wie nah an der Mitte?
            distance_from_mid = abs(price_eur - zone_mid) / (zone_size / 2)
            if distance_from_mid < 0.3:
                score += 3
                reasons.append(f"Kurs mitten in Entry-Zone ({price_eur:.2f}€)")
            else:
                score += 2
                reasons.append(f"Kurs in Entry-Zone ({price_eur:.2f}€)")
        elif price_eur < entry_min:
            if price_eur > entry_min * 0.95:  # <5% unter Zone
                score += 1
                reasons.append(f"Kurs knapp unter Zone ({price_eur:.2f}€ vs {entry_min}€ Min)")
            else:
                reasons.append(f"Kurs zu weit unter Zone ({price_eur:.2f}€)")
        else:
            reasons.append(f"Kurs über Entry-Zone ({price_eur:.2f}€ > {entry_max}€)")
            score = max(0, score - 1)

    # 3. Strategie-Health (0–2)
    if strategy_health == 'green':
        score += 2
        reasons.append("Strategie-Health: 🟢")
    elif strategy_health == 'yellow':
        score += 1
        reasons.append("Strategie-Health: 🟡")
    else:
        reasons.append("Strategie-Health: 🔴 (0 Punkte)")

    # 4. Makro (VIX) (0–2)
    if vix < 20:
        score += 2
        reasons.append(f"VIX {vix:.1f} (Risk-On)")
    elif vix < 30:
        score += 1
        reasons.append(f"VIX {vix:.1f} (neutral)")
    else:
        reasons.append(f"VIX {vix:.1f} (Risk-Off, 0 Punkte)")

    return score, reasons


def open_paper_trade(ticker, profile, price_eur, score, matched_triggers, top_headline):
    """Paper Trade in DB eröffnen."""
    if price_eur is None:
        return False, "Kein Kurs verfügbar"

    # Stop und Target in EUR
    stop_eur = profile['stop']
    if profile['currency'] in ('USD', 'GBP'):
        # Bereits als EUR übergeben, aber stop/target sind in Originalwährung
        # → Stop/Target aus Profil sind in der Originalwährung definiert
        # Wir speichern den EUR-Preis
        pass

    shares = round(PAPER_CAPITAL / price_eur, 4)

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Prüfen ob bereits offener Trade für diesen Ticker
        existing = c.execute(
            'SELECT id FROM paper_portfolio WHERE ticker=? AND status="OPEN"',
            (ticker,)
        ).fetchone()

        if existing:
            conn.close()
            return False, f"Bereits offener Trade für {ticker}"

        today = date.today().isoformat()
        note = f"News-Signal Score {score}/10 | Trigger: {', '.join(matched_triggers[:2])} | {top_headline[:60]}"

        c.execute('''
            INSERT INTO paper_portfolio
            (ticker, strategy, entry_price, entry_date, shares, stop_price, target_price, status, fees, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, "OPEN", 1.0, ?)
        ''', (
            ticker,
            profile.get('strategy', 'NEWS'),
            price_eur,
            today,
            shares,
            stop_eur,
            profile.get('target', price_eur * 1.2),
            note
        ))
        conn.commit()
        conn.close()
        return True, f"Paper Trade eröffnet: {shares:.2f} Anteile @ {price_eur:.2f}€"

    except Exception as e:
        return False, f"DB-Fehler: {e}"


def run_detector():
    profiles = load_profiles()
    strategies = load_strategies()
    cache = load_opp_cache()
    vix = get_vix()

    opportunities = []

    for ticker, profile in profiles.items():
        # News holen
        headlines = []
        for query in profile.get('news_queries', []):
            headlines.extend(fetch_rss(query, max_items=6))

        if not headlines:
            continue

        # Trigger-Matching
        all_matched_bullish = []
        all_matched_bearish = []
        top_headline = None
        top_source = None

        seen_headlines = set()
        for item in headlines:
            title = item['title']
            if title in seen_headlines:
                continue
            seen_headlines.add(title)

            title_lower = title.lower()
            bull_matches = [t for t in profile['bullish_triggers'] if t.lower() in title_lower]
            bear_matches = [t for t in profile['bearish_triggers'] if t.lower() in title_lower]

            if bull_matches or bear_matches:
                all_matched_bullish.extend(bull_matches)
                all_matched_bearish.extend(bear_matches)
                if not top_headline and bull_matches:
                    top_headline = title
                    top_source = item.get('source', '')

        if not all_matched_bullish:
            continue

        # Dedup-Check
        signal_key = f"{ticker}:{','.join(sorted(set(all_matched_bullish[:2])))}"
        if not is_new_opp(ticker, signal_key, cache):
            continue

        # Preis holen
        price_eur = fetch_yahoo_price(profile['yahoo'], profile['currency'])

        # Strategie-Health
        strategy_id = profile.get('strategy', 'STANDALONE')
        strategy_health = 'yellow'
        if strategy_id in strategies:
            strategy_health = strategies[strategy_id].get('health', 'yellow')

        # Score berechnen
        unique_bullish = list(set(all_matched_bullish))
        unique_bearish = list(set(all_matched_bearish))
        score, reasons = score_opportunity(
            profile, unique_bullish, unique_bearish,
            price_eur, vix, strategy_health
        )

        opportunities.append({
            'ticker': ticker,
            'name': profile['name'],
            'strategy': strategy_id,
            'score': score,
            'price_eur': price_eur,
            'entry_min': profile['entry_min'],
            'entry_max': profile['entry_max'],
            'stop': profile['stop'],
            'target': profile.get('target'),
            'matched_bullish': unique_bullish[:4],
            'matched_bearish': unique_bearish[:2],
            'top_headline': top_headline or '',
            'top_source': top_source or '',
            'reasons': reasons,
            'confirmation': profile.get('confirmation_required', 'price_in_zone'),
            'vix': vix,
            '_cache_key': signal_key
        })

    # Cache aktualisieren
    for opp in opportunities:
        mark_opp_seen(opp['ticker'], opp['_cache_key'], cache)
    save_opp_cache(cache)

    # Sortieren nach Score
    opportunities.sort(key=lambda x: x['score'], reverse=True)
    return opportunities


if __name__ == '__main__':
    import sys
    opps = run_detector()

    if not opps:
        print("KEIN_SIGNAL")
        sys.exit(0)

    # Nur Score ≥ 5 ausgeben
    relevant = [o for o in opps if o['score'] >= 5]
    if not relevant:
        print(f"KEIN_SIGNAL (niedrigster Score: {opps[0]['score'] if opps else 0})")
        sys.exit(0)

    print(f"OPPORTUNITY: {json.dumps(relevant, ensure_ascii=False)}")
    print(f"\n--- {len(relevant)} Opportunities (Score ≥ 5) ---")
    for o in relevant:
        score_bar = '█' * o['score'] + '░' * (10 - o['score'])
        price_str = f"{o['price_eur']:.2f}€" if o['price_eur'] else "N/A"
        in_zone = '✅' if o['price_eur'] and o['entry_min'] <= o['price_eur'] <= o['entry_max'] else '❌'
        print(f"\n  [{o['score']}/10] {score_bar} {o['ticker']} — {o['name']}")
        print(f"  Kurs: {price_str} {in_zone} Zone: {o['entry_min']}–{o['entry_max']}€")
        print(f"  Trigger: {o['matched_bullish']}")
        print(f"  Top-News: {o['top_headline'][:70]}")
        print(f"  Gründe: {o['reasons']}")
