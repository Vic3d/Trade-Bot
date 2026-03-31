#!/usr/bin/env python3
"""
sentiment_scorer.py — News-Sentiment-Scorer via Google News RSS
Holt Headlines und scored sie mit Keyword-Matching.
"""

import sys
import json
import re
import argparse
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.parse import quote
from xml.etree import ElementTree
import time

# Keyword scoring
POSITIVE = {
    'beats': 3, 'exceeds': 3, 'record': 2, 'upgrade': 3, 'buy': 2,
    'strong': 2, 'growth': 2, 'profit': 2, 'dividend': 2, 'contract': 3,
    'surge': 2, 'rally': 1, 'bullish': 2, 'outperform': 3, 'raises guidance': 4,
    'acquisition': 2, 'partnership': 1, 'expansion': 2, 'breakthrough': 3,
    'soars': 2, 'jumps': 1, 'gains': 1, 'rises': 1, 'higher': 1,
    'wins': 2, 'awarded': 2, 'boost': 2, 'revenue': 1, 'earnings': 1,
}

NEGATIVE = {
    'misses': -3, 'warns': -2, 'downgrade': -3, 'sell': -2, 'weak': -2,
    'loss': -2, 'debt': -1, 'lawsuit': -2, 'investigation': -2, 'recall': -2,
    'crash': -3, 'bearish': -2, 'underperform': -3, 'cuts guidance': -4,
    'layoffs': -2, 'bankruptcy': -4, 'default': -3, 'sanctions': -1,
    'falls': -1, 'drops': -1, 'declines': -1, 'lower': -1, 'plunges': -2,
    'slumps': -2, 'tumbles': -2, 'cuts': -1, 'warning': -2, 'risk': -1,
    'fears': -1, 'concern': -1, 'pressure': -1,
}

# Ticker → company name for better search
TICKER_NAMES = {
    'OXY': 'Occidental Petroleum',
    'TTE.PA': 'TotalEnergies',
    'FRO': 'Frontline',
    'DHT': 'DHT Holdings',
    'KTOS': 'Kratos Defense',
    'HII': 'Huntington Ingalls',
    'HAG.DE': 'Hensoldt',
    'BA.L': 'BAE Systems',
    'HL': 'Hecla Mining',
    'PAAS': 'Pan American Silver',
    'GOLD': 'Barrick Gold',
    'WPM': 'Wheaton Precious Metals',
    'MOS': 'Mosaic Company',
    'CF': 'CF Industries',
    'RHM.DE': 'Rheinmetall',
}


def fetch_google_news(ticker, max_articles=10):
    """Fetch headlines from Google News RSS."""
    # Use company name if available for better results
    search_term = TICKER_NAMES.get(ticker, ticker)
    query = quote(f"{search_term} stock")
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    
    try:
        req = Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })
        with urlopen(req, timeout=10) as response:
            xml_data = response.read()
        
        root = ElementTree.fromstring(xml_data)
        articles = []
        
        for item in root.findall('.//item')[:max_articles]:
            title = item.find('title')
            pub_date = item.find('pubDate')
            link = item.find('link')
            
            if title is not None and title.text:
                articles.append({
                    'title': title.text.strip(),
                    'date': pub_date.text.strip() if pub_date is not None and pub_date.text else '',
                    'url': link.text.strip() if link is not None and link.text else '',
                })
        
        return articles
    except Exception as e:
        return []


def score_headline(headline):
    """Score a single headline."""
    text = headline.lower()
    score = 0
    matched_keywords = []
    
    # Check multi-word phrases first
    for phrase, value in sorted(POSITIVE.items(), key=lambda x: -len(x[0])):
        if phrase in text:
            score += value
            matched_keywords.append(f"+{phrase}")
    
    for phrase, value in sorted(NEGATIVE.items(), key=lambda x: -len(x[0])):
        if phrase in text:
            score += value  # value is already negative
            matched_keywords.append(f"{phrase}")
    
    return score, matched_keywords


def score_headlines(ticker, max_articles=10):
    """Score all headlines for a ticker."""
    articles = fetch_google_news(ticker, max_articles)
    
    if not articles:
        return {
            'ticker': ticker,
            'score': 0,
            'articles': 0,
            'positive': 0,
            'negative': 0,
            'neutral': 0,
            'top_headline': 'Keine Artikel gefunden',
            'details': [],
        }
    
    total_score = 0
    positive_count = 0
    negative_count = 0
    neutral_count = 0
    details = []
    top_score = -999
    top_headline = articles[0]['title'] if articles else ''
    
    for article in articles:
        headline_score, keywords = score_headline(article['title'])
        total_score += headline_score
        
        if headline_score > 0:
            positive_count += 1
        elif headline_score < 0:
            negative_count += 1
        else:
            neutral_count += 1
        
        if headline_score > top_score:
            top_score = headline_score
            top_headline = article['title']
        
        details.append({
            'headline': article['title'],
            'score': headline_score,
            'keywords': keywords,
            'date': article.get('date', ''),
        })
    
    return {
        'ticker': ticker,
        'score': total_score,
        'articles': len(articles),
        'positive': positive_count,
        'negative': negative_count,
        'neutral': neutral_count,
        'top_headline': top_headline,
        'details': details,
    }


def score_portfolio(tickers, max_articles=10):
    """Score all tickers in the portfolio."""
    results = []
    for ticker in tickers:
        result = score_headlines(ticker, max_articles)
        results.append(result)
        time.sleep(0.5)  # Rate limiting
    return results


def get_sector_sentiment(sector_keywords):
    """Get sentiment for a sector using keywords."""
    query = quote(' '.join(sector_keywords))
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    
    try:
        req = Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })
        with urlopen(req, timeout=10) as response:
            xml_data = response.read()
        
        root = ElementTree.fromstring(xml_data)
        total_score = 0
        count = 0
        
        for item in root.findall('.//item')[:10]:
            title = item.find('title')
            if title is not None and title.text:
                s, _ = score_headline(title.text)
                total_score += s
                count += 1
        
        return {'keywords': sector_keywords, 'score': total_score, 'articles': count}
    except Exception:
        return {'keywords': sector_keywords, 'score': 0, 'articles': 0}


def print_report(tickers, max_articles=10):
    """Print sentiment report."""
    today = datetime.now().strftime('%d.%m.%Y')
    
    print(f"\n{'='*80}")
    print(f"=== SENTIMENT-SCORE ({today}) ===")
    print(f"{'='*80}")
    
    results = score_portfolio(tickers, max_articles)
    
    # Header
    print(f"\n{'Ticker':<10} {'Score':>6} {'Pos':>5} {'Neg':>5} {'Neutral':>8} Top-Headline")
    print('-' * 80)
    
    total_sentiment = 0
    strongest = None
    weakest = None
    
    for r in results:
        score_str = f"{r['score']:+d}"
        headline_short = r['top_headline'][:45] + '...' if len(r['top_headline']) > 45 else r['top_headline']
        print(f"{r['ticker']:<10} {score_str:>6} {r['positive']:>5} {r['negative']:>5} {r['neutral']:>8} \"{headline_short}\"")
        
        total_sentiment += r['score']
        if strongest is None or r['score'] > strongest['score']:
            strongest = r
        if weakest is None or r['score'] < weakest['score']:
            weakest = r
    
    # Summary
    sentiment_label = 'BULLISH' if total_sentiment > 5 else ('BEARISH' if total_sentiment < -5 else 'NEUTRAL')
    sentiment_emoji = '🟢' if sentiment_label == 'BULLISH' else ('🔴' if sentiment_label == 'BEARISH' else '🟡')
    
    print(f"\n{sentiment_emoji} Portfolio Sentiment: {total_sentiment:+d} ({sentiment_label})")
    if strongest:
        print(f"   Stärkster: {strongest['ticker']} ({strongest['score']:+d})")
    if weakest:
        print(f"   Schwächster: {weakest['ticker']} ({weakest['score']:+d})")
    
    return results


def save_sentiment(results):
    """Save sentiment data to JSON."""
    output = {
        'timestamp': datetime.now().isoformat(),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'results': [
            {k: v for k, v in r.items() if k != 'details'}
            for r in results
        ],
        'detailed_results': results,
        'portfolio_score': sum(r['score'] for r in results),
        'portfolio_label': 'BULLISH' if sum(r['score'] for r in results) > 5 else (
            'BEARISH' if sum(r['score'] for r in results) < -5 else 'NEUTRAL'
        ),
    }
    
    json_path = Path("/data/.openclaw/workspace/data/sentiment.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Sentiment gespeichert in: {json_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='News Sentiment Scorer')
    parser.add_argument('tickers', nargs='*', default=TICKER_NAMES.keys(),
                       help='Ticker-Liste (z.B. OXY KTOS HL)')
    parser.add_argument('--articles', type=int, default=10, help='Max Artikel pro Ticker')
    args = parser.parse_args()
    
    tickers = list(args.tickers)
    results = print_report(tickers, args.articles)
    save_sentiment(results)
