#!/usr/bin/env python3
"""
Trading Monitor v2.1 — Pure Python, Zero AI Tokens
===================================================
Konsolidierter Price-/Alert-Monitor für alle Positionen + Watchlist.
Ersetzt 11 separate AI-Cron-Jobs (~500 Runs/Tag → 1 Script).

Läuft alle 15 Min via OpenClaw Cron (minimaler Haiku-Prompt, ~500 Tokens/Run).
Alerts werden direkt via `openclaw message send` an Discord geschickt.

Autor: Albert 🎩 | v2.1 | 19.03.2026

Änderungen v2.1:
  - Sommerzeit-Fix: zoneinfo.ZoneInfo("Europe/Berlin") statt timedelta(hours=1)
  - Onvista-Cache: alle URLs einmalig in main() vorgeladen — kein Doppel-Crawl mehr
  - get_price_eur(): zentraler Helper — keine Code-Duplikation zwischen Position/Watchlist/Export
  - sent_today: set statt list → O(1) Lookup + .add()/.discard() statt .append()/.remove()
  - EMA10 + EMA200 in get_ema_data() + SMA-Initialisierung (korrektere Berechnung)
  - Conviction: Volume-Faktor entfernt (war immer 0), kein Stop gesetzt = -20 (statt 0)
  - yahoo_price(): 2 Retries mit exponentiellem Backoff bei Netzwerkfehler
  - check_macro(): Nikkei 225 (^N225) als Pflicht-Makroindikator hinzugefügt
  - Stop-Margin: (price - stop) / price statt / stop (konventionelle Berechnung)
  - Overnight-Context: kein hard-coded veralteter Kommentar
  - FX-Alert: Discord-Alert wenn EUR/USD nicht verfügbar
  - detect_candlestick(): Shooting Star (Bearish) hinzugefügt
  - Log-Rotation: nur alle 50 Log-Calls prüfen statt bei jedem
  - check_macro(): redundanten Date-Check entfernt (wird in main() erledigt)
"""

import json
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Sommerzeit-Fix: zoneinfo (Python 3.9+)
try:
    from zoneinfo import ZoneInfo
    _BERLIN_TZ = ZoneInfo("Europe/Berlin")
except ImportError:
    _BERLIN_TZ = None  # Fallback weiter unten


def berlin_now() -> datetime:
    """Aktuelles Datum/Uhrzeit in Europe/Berlin — Sommer- und Winterzeit korrekt."""
    if _BERLIN_TZ:
        return datetime.now(_BERLIN_TZ)
    # Fallback für Python < 3.9: DST-aware Schätzung
    import time as _time
    is_dst = _time.daylight and _time.localtime().tm_isdst > 0
    return datetime.now(timezone.utc) + timedelta(hours=2 if is_dst else 1)


# ─── Pfade ───────────────────────────────────────────────────────────
WORKSPACE = Path('/data/.openclaw/workspace')
CONFIG_PATH = WORKSPACE / 'trading_config.json'
STATE_PATH = WORKSPACE / 'memory' / 'trading-monitor-state.json'
LOG_PATH = WORKSPACE / 'memory' / 'trading-monitor.log'
PRICES_PATH = WORKSPACE / 'memory' / 'latest-prices.json'
SNAPSHOT_PATH = WORKSPACE / 'memory' / 'state-snapshot.md'
OVERNIGHT_PATH = WORKSPACE / 'memory' / 'overnight-context.md'
EMA_CACHE_PATH = WORKSPACE / 'memory' / 'ema-cache.json'
STRATEGIEN_PATH = WORKSPACE / 'memory' / 'strategien.md'

# trade_journal Modul einbinden
sys.path.insert(0, str(WORKSPACE / 'scripts'))
sys.path.insert(0, str(WORKSPACE / 'scripts' / 'intelligence'))
sys.path.insert(0, str(WORKSPACE / 'scripts' / 'core'))
sys.path.insert(0, str(WORKSPACE / 'scripts' / 'execution'))
try:
    from trade_journal import log_alert as _journal_log_alert
    JOURNAL_AVAILABLE = True
except ImportError:
    JOURNAL_AVAILABLE = False
    def _journal_log_alert(data): pass

# TradeMind v2 Module (Sprint 1-4)
try:
    from regime_detector import detect_current_regime as _detect_regime
    from conviction_scorer import calculate_conviction as _calc_conviction_v2
    from signal_engine import calculate_confluence as _calc_confluence
    from risk_manager import full_risk_report as _risk_report
    TRADEMIND_V2 = True
except ImportError:
    TRADEMIND_V2 = False

# ─── Log (mit effizienter Rotation) ──────────────────────────────────
_log_counter = 0

def log(msg: str):
    """Append to log + print. Rotation nur alle 50 Calls prüfen."""
    global _log_counter
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, 'a') as f:
            f.write(line + '\n')
        _log_counter += 1
        if _log_counter % 50 == 0:
            lines = LOG_PATH.read_text().splitlines()
            if len(lines) > 500:
                LOG_PATH.write_text('\n'.join(lines[-300:]) + '\n')
    except Exception:
        pass


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default if default is not None else {}


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def send_alert(msg: str, target: str = None, alert_type: str = 'GENERAL', ticker: str = None, value: str = None):
    """Schreibt Alert in Queue-Datei. Der Cron-Agent liest + sendet via message-Tool."""
    queue_path = WORKSPACE / 'memory' / 'alert-queue.json'
    queue = load_json(queue_path, [])
    queue.append({
        'message': msg,
        'target': target or '452053147620343808',
        'ts': datetime.now(timezone.utc).isoformat(),
    })
    save_json(queue_path, queue)
    log(f"ALERT QUEUED: {msg[:80]}...")
    
    # TRA-137: Auch in data/alerts.json schreiben für Dashboard Alert-Timeline
    alerts_path = WORKSPACE / 'data' / 'alerts.json'
    alerts = load_json(alerts_path, [])
    alerts.append({
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'type': alert_type,
        'ticker': ticker or '',
        'message': msg[:200],
        'value': value or '',
    })
    # Max 200 Alerts behalten
    if len(alerts) > 200:
        alerts = alerts[-200:]
    save_json(alerts_path, alerts)


# ─── Yahoo Finance (mit Retry) ───────────────────────────────────────

def yahoo_price(ticker: str, timeout: int = 8, retries: int = 2) -> dict | None:
    """
    Holt Preis + Meta von Yahoo Finance.
    Bei temporären Fehlern: bis zu 2 Retries mit exponentiellem Backoff.
    Returns dict oder None.
    """
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            result = data['chart']['result'][0]
            meta = result['meta']
            quote = result['indicators']['quote'][0]

            price = meta.get('regularMarketPrice', 0)
            prev_close = meta.get('chartPreviousClose', meta.get('previousClose', price))

            closes = [v for v in (quote.get('close') or []) if v is not None]
            opens  = [v for v in (quote.get('open')  or []) if v is not None]
            highs  = [v for v in (quote.get('high')  or []) if v is not None]
            lows   = [v for v in (quote.get('low')   or []) if v is not None]

            return {
                'price':      price,
                'prev_close': prev_close,
                'change_pct': (price - prev_close) / prev_close * 100 if prev_close else 0,
                'closes': closes,
                'opens':  opens,
                'highs':  highs,
                'lows':   lows,
            }
        except Exception as e:
            if attempt < retries:
                wait = 1.5 ** attempt  # 1.0s, 1.5s
                log(f"Yahoo RETRY {attempt+1}/{retries} für {ticker} (Fehler: {e}) — warte {wait:.1f}s")
                time.sleep(wait)
            else:
                log(f"Yahoo FEHLER {ticker} (alle {retries+1} Versuche): {e}")
                return None


def yahoo_batch(tickers: list) -> dict:
    """Holt Preise für mehrere Ticker. Returns {ticker: data}."""
    results = {}
    for t in tickers:
        data = yahoo_price(t)
        if data:
            results[t] = data
        time.sleep(0.3)
    return results


# ─── Onvista ─────────────────────────────────────────────────────────

def onvista_price(url: str) -> float | None:
    """Holt Kurs von Onvista via HTML-Scraping."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode('utf-8', errors='ignore')
        matches = re.findall(r'"last":([0-9.]+)', html)
        return float(matches[0]) if matches else None
    except Exception as e:
        log(f"Onvista FEHLER {url[-40:]}: {e}")
        return None


def prefetch_onvista(config: dict) -> dict:
    """
    Lädt alle Onvista-URLs einmalig in einen Cache.
    Verhindert Doppel-Crawl zwischen check_positions, check_watchlist und Export.
    Returns: {url: price_float}
    """
    urls = set()
    for pos in config.get('positions', {}).values():
        if url := pos.get('onvista'):
            urls.add(url)
    for watch in config.get('watchlist', []):
        if url := watch.get('onvista'):
            urls.add(url)

    cache = {}
    for url in urls:
        price = onvista_price(url)
        if price is not None:
            cache[url] = price
        time.sleep(0.5)  # Höfliche Pause zwischen Onvista-Requests
    log(f"Onvista: {len(cache)}/{len(urls)} URLs gecacht")
    return cache


# ─── Preis-Konvertierung ────────────────────────────────────────────

def to_eur(price: float, currency: str, fx: dict, ticker: str = '') -> float | None:
    """Konvertiert Preis in EUR. Loggt Warnung bei unbekannter Währung."""
    if currency == 'EUR':
        return price
    if currency == 'USD' and fx.get('EURUSD'):
        return price / fx['EURUSD']
    if currency == 'NOK' and fx.get('EURNOK'):
        return price / fx['EURNOK']
    if currency == 'GBP' and fx.get('GBPEUR'):
        # LSE quotiert in Pence (GBX): /100 → GBP, dann * GBPEUR (GBP/EUR-Rate)
        return (price / 100) * fx['GBPEUR']
    log(f"WARNUNG: Unbekannte Währung '{currency}' für {ticker} — Position übersprungen")
    return None


# ─── Zentraler Preis-Helper ──────────────────────────────────────────

def get_price_eur(item: dict, prices: dict, fx: dict, onvista_cache: dict,
                  key: str = '') -> tuple:
    """
    Zentraler Helper für Preis-Abruf: gibt (price_eur, price_raw) zurück.
    Nutzt Onvista-Cache (keine Doppel-Requests) oder Yahoo.
    Returns: (price_eur, price_raw) oder (None, None)
    """
    onvista_url = item.get('onvista')
    yahoo_ticker = item.get('yahoo')
    currency = item.get('currency', 'USD')

    if onvista_url:
        raw = onvista_cache.get(onvista_url)
        if raw is not None:
            return (raw, raw)
        return (None, None)

    if yahoo_ticker and yahoo_ticker in prices:
        raw = prices[yahoo_ticker]['price']
        eur = to_eur(raw, currency, fx, ticker=key or yahoo_ticker)
        return (eur, raw)

    return (None, None)


# ─── Candlestick Pattern Detection ──────────────────────────────────

def detect_candlestick(data: dict) -> str | None:
    """
    Erkennt Umkehrkerzen in 5-Min-Daten.
    Bullish: HAMMER, BULLISH_ENGULFING
    Bearish: SHOOTING_STAR, BEARISH_ENGULFING
    Returns Pattern-Name oder None.
    """
    closes = data.get('closes', [])
    opens  = data.get('opens',  [])
    highs  = data.get('highs',  [])
    lows   = data.get('lows',   [])

    if len(closes) < 2 or len(opens) < 2 or len(highs) < 2 or len(lows) < 2:
        return None

    k1 = {'o': opens[-2], 'c': closes[-2], 'h': highs[-2], 'l': lows[-2]}
    k2 = {'o': opens[-1], 'c': closes[-1], 'h': highs[-1], 'l': lows[-1]}

    range_k2 = k2['h'] - k2['l']
    if range_k2 < 0.01:
        return None

    body_k2      = abs(k2['c'] - k2['o'])
    lower_wick   = min(k2['o'], k2['c']) - k2['l']
    upper_wick   = k2['h'] - max(k2['o'], k2['c'])

    # ── Bullish ──
    # Hammer: langer unterer Docht (>2× Body), Schlusskurs über Öffnung
    if lower_wick > body_k2 * 2 and k2['c'] > k2['o']:
        return 'HAMMER'

    # Bullish Engulfing: bullische Kerze umschließt die vorherige bärische
    if (k1['c'] < k1['o']  # Vortag bärisch
            and k2['c'] > k2['o']  # Heute bullisch
            and k2['o'] <= k1['c']
            and k2['c'] >= k1['o']):
        return 'BULLISH_ENGULFING'

    # ── Bearish ──
    # Shooting Star: langer oberer Docht (>2× Body), Schlusskurs unter Öffnung
    if upper_wick > body_k2 * 2 and k2['c'] < k2['o']:
        return 'SHOOTING_STAR'

    # Bearish Engulfing: bärische Kerze umschließt die vorherige bullische
    if (k1['c'] > k1['o']  # Vortag bullisch
            and k2['c'] < k2['o']  # Heute bärisch
            and k2['o'] >= k1['c']
            and k2['c'] <= k1['o']):
        return 'BEARISH_ENGULFING'

    return None


# ─── Check-Funktionen ───────────────────────────────────────────────

def check_positions(config: dict, prices: dict, fx: dict, state: dict,
                    onvista_cache: dict,
                    strategy_statuses: dict = None,
                    conviction_cache: dict = None) -> list:
    """Prüft alle Positionen auf Stop-Nähe, Ziel-Erreichung, Trailing Stops."""
    from datetime import datetime
    alerts = []
    today = datetime.now().date().isoformat()
    settings   = config.get('settings', {})
    stop_warn  = settings.get('stop_warn_pct', 3.0)
    stop_crit  = settings.get('stop_critical_pct', 1.5)
    trail_start   = settings.get('trailing_start_pct', 5.0)
    trail_secure  = settings.get('trailing_secure_pct', 10.0)
    sent_today = state.get('alerts_sent_today', set())
    if strategy_statuses is None:
        strategy_statuses = {}
    if conviction_cache is None:
        conviction_cache = {}

    macro_wti = prices.get('CL=F', {}).get('price')
    macro_vix = prices.get('^VIX', {}).get('price')

    for key, pos in config.get('positions', {}).items():
        if pos.get('status') == 'CLOSED':
            continue

        name   = pos['name']
        ticker = f"{name} ({key})"
        stop   = pos.get('stop_eur')
        entry  = pos.get('entry_eur', 0)

        price_eur, _ = get_price_eur(pos, prices, fx, onvista_cache, key)
        if price_eur is None:
            continue

        pnl_pct = (price_eur - entry) / entry * 100 if entry else 0

        # Conviction Score
        conv     = conviction_score(key, pos, price_eur, stop, entry, macro_vix, strategy_statuses)
        conviction_cache[key] = conv
        conv_str = f" [Conviction: {conv['score']}/100]"

        if stop:
            # Stop-Margin: relativ zum aktuellen Preis (konventionell)
            margin_pct = (price_eur - stop) / price_eur * 100
            alert_key  = f"{key}_STOP_HIT"
            warn_key   = f"{key}_STOP_WARN"
            crit_key   = f"{key}_STOP_CRIT"

            if price_eur <= stop and alert_key not in sent_today:
                msg = (f"🔴 STOP GETROFFEN: {ticker} @ {price_eur:.2f}€ | Stop: {stop}€ | SOFORT PRÜFEN!{conv_str}")
                alerts.append(msg)
                sent_today.add(alert_key)
                _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Stop-Breach',
                    'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                    'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})

            elif margin_pct < stop_crit and crit_key not in sent_today:
                msg = (f"⚠️ STOP KRITISCH: {ticker} @ {price_eur:.2f}€ | Stop: {stop}€ | "
                       f"Nur noch {margin_pct:.1f}% Abstand!{conv_str}")
                alerts.append(msg)
                sent_today.add(crit_key)
                _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Stop-Kritisch',
                    'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                    'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})

            elif margin_pct < stop_warn and warn_key not in sent_today:
                msg = (f"⚡ Stop-Nähe: {ticker} @ {price_eur:.2f}€ | Stop: {stop}€ | "
                       f"{margin_pct:.1f}% Abstand{conv_str}")
                alerts.append(msg)
                sent_today.add(warn_key)
                _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Stop-Warnung',
                    'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                    'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})

            # Reset wenn Kurs sich erholt
            elif margin_pct > stop_warn + 2:
                sent_today.discard(warn_key)
                sent_today.discard(crit_key)

        # Ziel-Checks
        for i, target in enumerate(pos.get('targets_eur', [])):
            tgt_key = f"{key}_ZIEL{i+1}"
            if price_eur >= target and tgt_key not in sent_today:
                msg = (f"🎯 ZIEL {i+1} ERREICHT: {ticker} @ {price_eur:.2f}€ | Ziel: {target}€ | "
                       f"P&L: {pnl_pct:+.1f}% | Stop nachziehen?{conv_str}")
                alerts.append(msg)
                sent_today.add(tgt_key)
                _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Target-Reached',
                    'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                    'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})

        # Trailing Stop Trigger — permanenter State (trail_sent), nicht tagesabhängig
        # Regel: Immer nur EINE Nachricht pro Position — höchste zutreffende Schwelle gewinnt
        trail_sent = state.get('trail_sent', {})

        trail_key  = f"{key}_TRAIL_{int(trail_start)}"
        trail_key2 = f"{key}_TRAIL_{int(trail_secure)}"

        # Reset-Logik: Key löschen wenn P&L >2% unter jeweilige Schwelle gefallen
        if entry and pnl_pct < trail_start - 2:
            trail_sent.pop(trail_key, None)
            trail_sent.pop(trail_key2, None)
            state['trail_sent'] = trail_sent
        elif entry and pnl_pct < trail_secure - 2:
            trail_sent.pop(trail_key2, None)
            state['trail_sent'] = trail_sent

        # Schwelle 2 (trail_secure) hat Vorrang — wenn zutreffend, Schwelle 1 unterdrücken
        if entry and pnl_pct >= trail_secure and trail_key2 not in trail_sent:
            secure_price = entry + (price_eur - entry) * 0.5
            msg = (f"🔒 Gewinn sichern: {ticker} @ {price_eur:.2f}€ | P&L: {pnl_pct:+.1f}% "
                   f"(>{trail_secure}%) | 50% Gewinn sichern → Stop auf {secure_price:.2f}€{conv_str}")
            alerts.append(msg)
            trail_sent[trail_key]  = today  # Beide Keys setzen → Schwelle 1 wird nicht mehr feuern
            trail_sent[trail_key2] = today
            state['trail_sent'] = trail_sent
            _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Trailing-Signal',
                'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})

        elif entry and pnl_pct >= trail_start and trail_key not in trail_sent:
            # Nur Schwelle 1 — Schwelle 2 noch nicht erreicht
            msg = (f"📈 Trailing Stop fällig: {ticker} @ {price_eur:.2f}€ | P&L: {pnl_pct:+.1f}% "
                   f"(>{trail_start}%) | Stop auf Breakeven ({entry:.2f}€) nachziehen!{conv_str}")
            alerts.append(msg)
            trail_sent[trail_key] = today
            state['trail_sent'] = trail_sent
            _journal_log_alert({'ticker': key, 'name': name, 'alert_type': 'Trailing-Signal',
                'price_eur': price_eur, 'entry_eur': entry, 'pnl_pct': pnl_pct,
                'stop_eur': stop, 'vix': macro_vix, 'wti': macro_wti, 'conviction': conv})

        # Spezial-Alerts (z.B. NVDA Kursstufen)
        yahoo_t = pos.get('yahoo')
        for alert_name, threshold in pos.get('alerts', {}).items():
            ckey = f"{key}_{alert_name}"
            if ckey in sent_today or not yahoo_t or yahoo_t not in prices:
                continue
            raw_price = prices[yahoo_t]['price']
            if 'below' in alert_name and raw_price <= threshold:
                alerts.append(f"🔔 {ticker}: ${raw_price:.2f} — {alert_name.replace('_', ' ').title()} Zone ({threshold})! Setup beobachten.")
                sent_today.add(ckey)
            elif 'above' in alert_name and raw_price >= threshold:
                alerts.append(f"🔔 {ticker}: ${raw_price:.2f} — {alert_name.replace('_', ' ').title()} ({threshold})! Signal prüfen.")
                sent_today.add(ckey)

    state['alerts_sent_today'] = sent_today
    return alerts


def check_watchlist(config: dict, prices: dict, fx: dict, state: dict,
                    onvista_cache: dict) -> list:
    """Prüft Watchlist-Aktien auf Entry-Signale + Candlestick-Patterns."""
    alerts = []
    sent_today = state.get('alerts_sent_today', set())

    for watch in config.get('watchlist', []):
        key = watch['ticker']
        name   = watch['name']
        ticker = f"{name} ({key})"

        price_eur, price_raw = get_price_eur(watch, prices, fx, onvista_cache, key)
        if price_raw is None:
            continue

        # EUR-basierte Signale
        for sig_key, threshold, label in [
            ('signal_a_above_eur', watch.get('signal_a_above_eur'), f"SIGNAL A: über {{t}}€! Entry-Setup aktiv."),
            ('signal_b_below_eur', watch.get('signal_b_below_eur'), f"SIGNAL B: unter {{t}}€! Rücklauf-Entry-Zone."),
            ('entry_below_eur',    watch.get('entry_below_eur'),    f"ENTRY-ZONE: unter {{t}}€! Setup prüfen."),
            ('entry_b_below_eur',  watch.get('entry_b_below_eur'),  f"ENTRY B: unter {{t}}€!"),
        ]:
            if not threshold or price_eur is None:
                continue
            hit = (price_eur >= threshold if 'above' in sig_key else price_eur <= threshold)
            akey = f"WL_{key}_{sig_key.upper()}"
            if hit and akey not in sent_today:
                t = threshold
                alerts.append(f"🔔 {ticker} @ {price_eur:.2f}€ — {label.format(t=t)}")
                sent_today.add(akey)

        # USD-basierte Signale
        ea_usd = watch.get('entry_a_above_usd')
        if ea_usd and price_raw >= ea_usd:
            akey = f"WL_{key}_ENTRY_A_USD"
            if akey not in sent_today:
                alerts.append(f"🔔 ENTRY A: {ticker} @ ${price_raw:.2f} (>{ea_usd}) — Breakout!")
                sent_today.add(akey)

        eb_usd = watch.get('entry_b_below_usd')
        if eb_usd and price_raw <= eb_usd:
            bkey = f"WL_{key}_ENTRY_B_USD"
            if bkey not in sent_today:
                alerts.append(f"🔔 ENTRY B: {ticker} @ ${price_raw:.2f} (<{eb_usd}) — Rücklauf-Zone!")
                sent_today.add(bkey)

        # Candlestick Detection (nur für Yahoo-Ticker)
        yahoo_t = watch.get('yahoo')
        if watch.get('candlestick_detect') and yahoo_t and yahoo_t in prices:
            pattern = detect_candlestick(prices[yahoo_t])
            if pattern:
                ckey = f"WL_{key}_CANDLE_{pattern}"
                if ckey not in sent_today:
                    direction = '🐻 BEARISH' if 'BEARISH' in pattern or 'SHOOTING' in pattern else '🐂 BULLISH'
                    alerts.append(f"🕯️ UMKEHRKERZE {direction}: {ticker} — {pattern} @ ${price_raw:.2f}! Entry-Bestätigung?")
                    sent_today.add(ckey)

        # WPR Monatssignal (Eriksen 13.03.2026: Akkumulierungs-Indikator)
        # Nur einmal täglich, nur für Watchlist-Items mit wpr_monthly_check: true
        if watch.get('wpr_monthly_check') and yahoo_t:
            wkey = f"WL_{key}_WPR_MONTHLY"
            if wkey not in sent_today:
                wpr_data = calc_wpr_monthly(yahoo_t)
                if wpr_data:
                    wpr = wpr_data['wpr']
                    wpr_prev = wpr_data.get('wpr_prev')
                    # Signal 1: WPR steigt aus überverkaufter Zone heraus (>-80 nach <-80)
                    if wpr_prev and wpr_prev < -80 and wpr > -80:
                        alerts.append(
                            f"📊 WPR-MONATSSIGNAL 🟡 STUFE 1 — {ticker}\n"
                            f"WPR Monat: {wpr_prev:.0f} → {wpr:.0f} (steigt aus <-80 Zone)\n"
                            f"→ Mögliche Bodenbildung / Smart Money Akkumulation (Eriksen-Methodik)\n"
                            f"→ Noch kein Kaufsignal — Wochenschlusskurs über definiertem Level abwarten"
                        )
                        sent_today.add(wkey)
                    # Signal 2: WPR steigt über -50 (Momentum bestätigt)
                    elif wpr_prev and wpr_prev < -50 and wpr > -50:
                        alerts.append(
                            f"📊 WPR-MONATSSIGNAL 🟢 STUFE 2 — {ticker}\n"
                            f"WPR Monat: {wpr_prev:.0f} → {wpr:.0f} (über -50 — Momentum bestätigt)\n"
                            f"→ Prozyklisches Kaufsignal. Einstieg wenn Kurs über fallenden GD (Wochenchart).\n"
                            f"14M-Range: ${wpr_data['ll_14m']:.2f} – ${wpr_data['hh_14m']:.2f} | Akt. ${wpr_data['price']:.2f}"
                        )
                        sent_today.add(wkey)
                    # Info: tief in überverkaufter Zone (Monitoring)
                    elif wpr < -85:
                        alerts.append(
                            f"📊 WPR-MONITORING — {ticker}: WPR Monat {wpr:.0f} (tief überverkauft)\n"
                            f"→ Noch kein Signal. Beobachten ob Umkehr aus Zone einsetzt."
                        )
                        sent_today.add(wkey)

    state['alerts_sent_today'] = sent_today
    return alerts


# ─── Kausalketten-System ─────────────────────────────────────────────

# Wie sich bekannte Makro-Ursachen auf Positionen auswirken
# direction: '+' = bullish, '-' = bearish, '0' = neutral
# strength: 'stark' | 'mittel' | 'leicht'
CAUSAL_CHAINS = {
    'oil_shock': {
        'label': 'Öl-Schock',
        'explanation': 'Brent/WTI steigt → Energie-Importeure (Japan) unter Kosten-Druck → Nikkei fällt',
        'headlines_kw': ['oil', 'crude', 'brent', 'wti', 'opec', 'iran', 'energy', 'barrel', 'petroleum', 'öl'],
        'impact': {
            'EQNR':    ('+', 'stark',  'Ölproduzent — profitiert direkt'),
            'NVDA':    ('-', 'leicht', 'Energiekosten der Rechenzentren steigen'),
            'MSFT':    ('-', 'leicht', 'Energiekosten steigen'),
            'PLTR':    ('0', 'neutral','Kein direkter Öl-Bezug'),
            'BAYN.DE': ('0', 'neutral','Kein direkter Öl-Bezug'),
        },
        'strategy_menu': [
            '🟢 Halten: EQNR Stop nachziehen — Thesis bestätigt',
            '🟡 Teilverkauf Tech: NVDA/MSFT reduzieren wenn VIX > 27',
            '🔴 Voll Exit Rohstoffe: Wenn Nikkei bis 12 Uhr nicht erholt',
        ],
    },
    'china_slowdown': {
        'label': 'China-Abschwächung',
        'explanation': 'Schwache China-Nachfrage → Rohstoff-Preise fallen → Bergbau und Energie verlieren',
        'headlines_kw': ['china', 'pmi', 'manufacturing', 'iron ore', 'copper', 'steel', 'demand', 'slowdown', 'industrial'],
        'impact': {
            'EQNR':    ('-', 'mittel', 'Energienachfrage sinkt'),
            'NVDA':    ('-', 'leicht', 'Lieferkette/Absatzmarkt unter Druck'),
            'MSFT':    ('0', 'neutral','Kaum China-Exposure im Cloud-Bereich'),
        },
        'strategy_menu': [
            '🟢 Halten: Kurzfristig schmerzt es, mittelfristig erholt sich China',
            '🟡 Stop enger setzen bei Energie-Positionen (EQNR)',
            '🔴 Exit Rohstoffe: Wenn PMI < 49 für 2+ Monate bestätigt',
        ],
    },
    'boj_rate_hike': {
        'label': 'BoJ-Zinsschock',
        'explanation': 'Bank of Japan hebt Zinsen → Yen stärkt sich stark → japanische Exporteure verlieren → Nikkei fällt',
        'headlines_kw': ['boj', 'bank of japan', 'yen', 'rate hike', 'interest rate', 'usd/jpy', 'kuroda', 'ueda'],
        'impact': {
            'NVDA':    ('-', 'mittel', 'Risk-Off, Kapitalabfluss aus Growth-Aktien'),
            'PLTR':    ('-', 'mittel', 'Risk-Off drückt auf hochbewertete Tech-Aktien'),
            'MSFT':    ('-', 'leicht', 'Leichter Risk-Off Effekt'),
            'EQNR':    ('0', 'neutral','Kein direkter BoJ-Bezug'),
        },
        'strategy_menu': [
            '🟢 Halten: BoJ-Hikes sind strukturell bullisch für Finanzstabilität, kurzfristiger Schmerz',
            '🟡 PLTR Stop prüfen — hoch bewertet = am stärksten betroffen bei Risk-Off',
            '🔴 Growth-Tech reduzieren wenn USD/JPY < 145',
        ],
    },
    'us_contagion': {
        'label': 'US-Marktdruck',
        'explanation': 'US-Märkte (Nasdaq/S&P) fallen → überträgt sich auf Asien über globale Risikoaversion',
        'headlines_kw': ['nasdaq', 's&p', 'sp500', 'fed', 'recession', 'inflation', 'powell', 'fomc', 'tech selloff'],
        'impact': {
            'NVDA':    ('-', 'stark',  'Tech-Selloff trifft NVDA direkt'),
            'MSFT':    ('-', 'stark',  'Tech-Selloff trifft MSFT direkt'),
            'PLTR':    ('-', 'stark',  'High-Beta, verliert überproportional'),
            'EQNR':    ('-', 'leicht', 'Leichter Risk-Off Effekt'),
            'BAYN.DE': ('-', 'leicht', 'Defensive, aber nicht immun'),
        },
        'strategy_menu': [
            '🟢 Halten: Wenn US-Markt nur korrigiert (< −5%), nicht crasht',
            '🟡 PLTR Stop sofort prüfen — enger als normale Korrektur erlaubt',
            '🔴 Tech-Positionen halbieren wenn Nasdaq −3% intraday',
        ],
    },
    'geopolitical': {
        'label': 'Geopolitische Eskalation',
        'explanation': 'Geopolitische Krise → Öl-Risikoprämie steigt, Safe-Haven-Nachfrage, Rüstung profitiert',
        'headlines_kw': ['war', 'attack', 'conflict', 'military', 'iran', 'missile', 'ukraine', 'taiwan', 'escalat', 'sanction'],
        'impact': {
            'EQNR':    ('+', 'stark',  'Öl-Risikoprämie steigt — direkt profitiert'),
            'NVDA':    ('-', 'mittel', 'Risk-Off, Lieferketten-Unsicherheit'),
            'MSFT':    ('-', 'leicht', 'Leichter Risk-Off'),
            'BAYN.DE': ('0', 'neutral','Defensiver Sektor, kaum betroffen'),
        },
        'strategy_menu': [
            '🟢 Halten EQNR + Öl-Positionen — Thesis verstärkt sich',
            '🟡 VIX monitoren: über 30 → Stops bei Tech enger setzen',
            '🔴 Wenn Konflikt eskaliert (US involviert) → breiter Risikoabbau',
        ],
    },
}


def fetch_macro_headlines(query: str, max_results: int = 5) -> list[str]:
    """Holt aktuelle Headlines via Google News RSS (kein API-Key nötig)."""
    try:
        import xml.etree.ElementTree as ET
        url = f'https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en&gl=US&ceid=US:en'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            xml_data = r.read()
        root = ET.fromstring(xml_data)
        headlines = []
        for item in root.findall('.//item')[:max_results]:
            title = item.findtext('title', '')
            if title:
                headlines.append(title.lower())
        return headlines
    except Exception:
        return []


def classify_macro_cause(headlines: list[str], fallback: str = 'unknown') -> str:
    """Bestimmt die Ursache eines Macro-Signals anhand von Headline-Keywords."""
    text = ' '.join(headlines)
    scores = {}
    for cause, chain in CAUSAL_CHAINS.items():
        score = sum(1 for kw in chain['headlines_kw'] if kw in text)
        if score > 0:
            scores[cause] = score
    if not scores:
        return fallback
    return max(scores, key=scores.get)


def build_macro_alert(signal_name: str, signal_value: str,
                      cause: str, positions: dict) -> str:
    """Baut eine vollständige Makro-Alert-Nachricht mit Kausalkette + Strategie-Menu."""
    chain = CAUSAL_CHAINS.get(cause)
    if not chain:
        return f"⚠️ {signal_name}: {signal_value} — Ursache unbekannt, Stops prüfen!"

    # Betroffene Positionen aus aktuellem Portfolio filden
    active = [t for t, p in positions.items()
              if isinstance(p, dict) and p.get('status') != 'CLOSED']
    affected_lines = []
    for ticker in active:
        # Ticker-Varianten prüfen (EQNR.OL → EQNR etc.)
        base = ticker.replace('.DE', '').replace('.L', '').replace('.OL', '').replace('.AS', '')
        match = chain['impact'].get(ticker) or chain['impact'].get(base)
        if match:
            direction, strength, note = match
            icon = '📈' if direction == '+' else ('📉' if direction == '-' else '➡️')
            affected_lines.append(f"  {icon} {ticker}: {strength} — {note}")

    affected_str = '\n'.join(affected_lines) if affected_lines else '  Keine direkt betroffenen Positionen'
    strategy_str = '\n'.join(f'  {s}' for s in chain['strategy_menu'])

    return (
        f"⚠️ MACRO: {signal_name} {signal_value}\n"
        f"📌 Ursache: {chain['label']}\n"
        f"🔗 Kausalkette: {chain['explanation']}\n\n"
        f"📊 Portfolio-Impact:\n{affected_str}\n\n"
        f"🎯 Strategie-Menu:\n{strategy_str}"
    )


def check_macro(config: dict, prices: dict, state: dict) -> list:
    """Prüft WTI-Öl, VIX und Nikkei 225 — mit Kausalketten-Analyse bei Alarm."""
    alerts     = []
    macro      = config.get('macro', {})
    positions  = config.get('positions', {})
    sent_today = state.get('alerts_sent_today', set())

    # ── WTI Öl ──
    wti_t = macro.get('wti_ticker', 'CL=F')
    if wti_t in prices:
        wti      = prices[wti_t]['price']
        wti_prev = state.get('prev_wti', wti)
        wti_open = state.get('wti_open', wti)

        # Tageseröffnung setzen (nur wenn noch nicht gesetzt — wird in main() täglich gecleart)
        if 'wti_open' not in state:
            state['wti_open'] = wti
            wti_open = wti

        # 30-Min-Momentum
        if wti_prev > 0:
            wti_30m   = (wti - wti_prev) / wti_prev * 100
            threshold = macro.get('wti_30m_alert_pct', 3.0)
            if abs(wti_30m) >= threshold:
                mkey = 'MACRO_WTI_30M'
                if mkey not in sent_today:
                    headlines = fetch_macro_headlines('WTI crude oil price today')
                    cause     = classify_macro_cause(headlines, fallback='oil_shock')
                    msg       = build_macro_alert(
                        'WTI ÖL 30-Min-Bewegung',
                        f'{"+" if wti_30m>0 else ""}{wti_30m:.1f}% (${wti_prev:.2f}→${wti:.2f})',
                        cause, positions
                    )
                    alerts.append(msg)
                    sent_today.add(mkey)

        # Tagesbewegung
        if wti_open > 0:
            wti_daily   = (wti - wti_open) / wti_open * 100
            threshold_d = macro.get('wti_daily_alert_pct', 5.0)
            if abs(wti_daily) >= threshold_d:
                dkey = 'MACRO_WTI_DAILY'
                if dkey not in sent_today:
                    headlines = fetch_macro_headlines('WTI crude oil market today')
                    cause     = classify_macro_cause(headlines, fallback='oil_shock')
                    msg       = build_macro_alert(
                        'WTI ÖL Tagesbewegung',
                        f'{wti_daily:+.1f}% (${wti_open:.2f}→${wti:.2f})',
                        cause, positions
                    )
                    alerts.append(msg)
                    sent_today.add(dkey)

        state['prev_wti'] = wti

    # ── Brent-WTI Spread (TRA-177) ──
    brent_t = macro.get('brent_ticker', 'BZ=F')
    if brent_t in prices and wti_t in prices:
        brent = prices[brent_t]['price']
        wti   = prices[wti_t]['price']
        spread = brent - wti
        threshold_spread = macro.get('brent_wti_spread_alert', 8.0)
        if spread > threshold_spread:
            skey = 'MACRO_BRENT_WTI_SPREAD'
            if skey not in sent_today:
                msg = (f"⚠️ BRENT-WTI SPREAD: ${spread:.2f} "
                       f"(Brent ${brent:.2f} - WTI ${wti:.2f}) — Lieferunterbrechung Warnsignal!")
                alerts.append(msg)
                sent_today.add(skey)

    # ── VIX ──
    vix_t = macro.get('vix_ticker', '^VIX')
    if vix_t in prices:
        vix      = prices[vix_t]['price']
        vix_open = state.get('vix_open', vix)

        if 'vix_open' not in state:
            state['vix_open'] = vix
            vix_open = vix

        vix_delta   = vix - vix_open
        threshold_v = macro.get('vix_spike_delta', 5.0)
        if vix_delta >= threshold_v:
            vkey = 'MACRO_VIX_SPIKE'
            if vkey not in sent_today:
                headlines = fetch_macro_headlines('VIX volatility market fear spike')
                cause     = classify_macro_cause(headlines, fallback='us_contagion')
                msg       = build_macro_alert(
                    'VIX SPIKE',
                    f'+{vix_delta:.1f} Punkte ({vix_open:.1f}→{vix:.1f})',
                    cause, positions
                )
                alerts.append(msg)
                sent_today.add(vkey)

    # ── Nikkei 225 ──
    # Japan = weltgrößter Öl-Nettoimporteur → Frühindikator für Öl/Macro-Schocks
    nikkei_t = macro.get('nikkei_ticker', '^N225')
    if nikkei_t in prices:
        nikkei      = prices[nikkei_t]
        nikkei_chg  = nikkei.get('change_pct', 0)
        threshold_n = macro.get('nikkei_drop_pct', -3.0)
        if nikkei_chg <= threshold_n:
            nkey = 'MACRO_NIKKEI_DROP'
            if nkey not in sent_today:
                # News holen → Ursache klassifizieren → vollständige Analyse
                headlines = fetch_macro_headlines('Nikkei 225 fall today reason')
                cause     = classify_macro_cause(headlines, fallback='oil_shock')
                msg       = build_macro_alert(
                    'NIKKEI 225',
                    f'{nikkei_chg:+.1f}%',
                    cause, positions
                )
                alerts.append(msg)
                sent_today.add(nkey)

    # ── SX7E Euro Stoxx Banks (TRA-178) ──
    # Frühindikator für europäischen Bankensektor / systemische Risiken
    sx7e_t = macro.get('sx7e_ticker', 'EXV1.DE')
    if sx7e_t in prices:
        sx7e      = prices[sx7e_t]
        sx7e_chg  = sx7e.get('change_pct', 0)
        threshold_sx7e = macro.get('sx7e_drop_pct', -2.0)
        if sx7e_chg <= threshold_sx7e:
            xkey = 'MACRO_SX7E_DROP'
            if xkey not in sent_today:
                headlines = fetch_macro_headlines('Euro Stoxx Banks EXV1 European banks fall today')
                cause     = classify_macro_cause(headlines, fallback='us_contagion')
                msg       = build_macro_alert(
                    'EURO STOXX BANKS (SX7E)',
                    f'{sx7e_chg:+.1f}%',
                    cause, positions
                )
                alerts.append(msg)
                sent_today.add(xkey)

    # ── S&P 500 / 200-MA Check (Eriksen 28.03.2026: Regime-Framework) ──
    # Signal: S&P über/unter 200-MA = Risk-On/Off Regime-Indikator
    spy_t = macro.get('spy_ticker', 'SPY')
    spy_ema = get_ema_data(spy_t)
    if spy_ema and spy_ema.get('ema200') and spy_ema.get('price'):
        spy_price = spy_ema['price']
        spy_ma200 = spy_ema['ema200']
        prev_spy_above = state.get('spy_above_ma200', None)
        curr_spy_above = spy_price > spy_ma200
        pct_from_ma200 = (spy_price - spy_ma200) / spy_ma200 * 100

        # Beim ersten Run nur State setzen, kein Alert
        if prev_spy_above is None:
            state['spy_above_ma200'] = curr_spy_above
        elif prev_spy_above != curr_spy_above:
            # Regime-Wechsel: S&P 500 kreuzt 200-MA
            mkey = 'MACRO_SPY_MA200_CROSS'
            if mkey not in sent_today:
                direction = "📈 ÜBER" if curr_spy_above else "📉 UNTER"
                emoji = "🟢" if curr_spy_above else "🔴"
                msg = (
                    f"{emoji} S&P 500 (SPY) **KREUZT 200-TAGE-MA** {direction}\n"
                    f"SPY ${spy_price:.2f} | MA200 ${spy_ma200:.2f} ({pct_from_ma200:+.1f}%)\n"
                    f"{'→ Risk-ON: Regime-Wechsel bullisch. Aktives Positionieren möglich.' if curr_spy_above else '→ Risk-OFF: Strukturelle Schwäche. Keine neuen aggressiven Longs. (Eriksen-Regel)'}"
                )
                alerts.append(msg)
                sent_today.add(mkey)
            state['spy_above_ma200'] = curr_spy_above
        else:
            state['spy_above_ma200'] = curr_spy_above

        # Tägliche Erinnerung wenn S&P unter 200-MA (einmal/Tag)
        if not curr_spy_above:
            dkey = 'MACRO_SPY_UNDER_MA200_DAILY'
            if dkey not in sent_today:
                msg = (f"⚠️ S&P 500 UNTER 200-MA | SPY ${spy_price:.2f} vs MA200 ${spy_ma200:.2f} "
                       f"({pct_from_ma200:.1f}%) — Risk-OFF aktiv. Kein aggressiver Aufbau.")
                alerts.append(msg)
                sent_today.add(dkey)

    # ── FedEx (FDX) als Realwirtschafts-Frühindikator (Eriksen 22.03.2026) ──
    # Logistikkonzerne sehen Wirtschaftsdaten 4-6 Wochen früher als offizielle Statistiken.
    # FDX Tageseinbruch >4% = potenzielles Phase-2-Signal (Wachstumsschock kommt)
    fdx_t = macro.get('fedex_ticker', 'FDX')
    if fdx_t in prices:
        fdx       = prices[fdx_t]
        fdx_chg   = fdx.get('change_pct', 0)
        fdx_price = fdx.get('price', 0)
        threshold_fdx = macro.get('fedex_drop_pct', -4.0)
        if fdx_chg <= threshold_fdx:
            fkey = 'MACRO_FEDEX_DROP'
            if fkey not in sent_today:
                msg = (
                    f"🚨 FEDEX (FDX) EINBRUCH: {fdx_chg:+.1f}% (${fdx_price:.2f})\n"
                    f"→ Frühindikator: Logistiker sehen Wirtschaft 4-6 Wochen früher.\n"
                    f"→ FDX >-4% Tageseinbruch = mögliches **Phase-2-Signal** (Eriksen-Framework).\n"
                    f"→ Prüfen: Guidance gesenkt? Volumen-Prognose runter? → Rezession 1-2 Quartale voraus."
                )
                alerts.append(msg)
                sent_today.add(fkey)

    state['alerts_sent_today'] = sent_today
    return alerts


# ─── WPR Monthly Signal (Williams Percentage Range, Monatsbasis) ────
# Eriksen 13.03.2026: WPR auf Monatsbasis = seltenes Akkumulierungs-Signal
# Zeigt wenn Smart Money still kauft, auch wenn Kurs noch fällt.

def calc_wpr_monthly(ticker: str) -> dict | None:
    """
    Berechnet Williams Percentage Range (WPR) auf Monatsbasis.
    WPR = (Highest High - Close) / (Highest High - Lowest Low) * -100
    Skala: 0 (überkauft) bis -100 (überverkauft)
    Signal: WPR steigt aus Zone <-80 heraus = Akkumulation / Bodenbildung
    """
    import urllib.parse
    end   = int(__import__('time').time())
    start = end - (365 * 24 * 3600 * 2)  # 2 Jahre für monatliche Daten
    url   = (f"https://query2.finance.yahoo.com/v8/finance/chart/"
             f"{urllib.parse.quote(ticker)}?interval=1mo&period1={start}&period2={end}")
    req   = __import__('urllib.request', fromlist=['Request', 'urlopen'])
    try:
        import json as _json
        import urllib.request as _ur
        r = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = _json.loads(_ur.urlopen(r, timeout=10).read())
        result = d['chart']['result'][0]
        q = result['indicators']['quote'][0]
        highs  = [h for h in q.get('high', [])  if h is not None]
        lows   = [l for l in q.get('low', [])   if l is not None]
        closes = [c for c in q.get('close', []) if c is not None]
        if len(closes) < 3:
            return None
        # Letzten 14 Monate für WPR-Berechnung
        period = min(14, len(closes))
        hh = max(highs[-period:])
        ll = min(lows[-period:])
        close = closes[-1]
        prev_close = closes[-2]
        if hh == ll:
            return None
        wpr_curr = (hh - close) / (hh - ll) * -100
        wpr_prev = (max(highs[-period-1:-1]) - prev_close) / (max(highs[-period-1:-1]) - min(lows[-period-1:-1])) * -100 if len(closes) > period else None
        return {
            'ticker':   ticker,
            'wpr':      round(wpr_curr, 1),
            'wpr_prev': round(wpr_prev, 1) if wpr_prev else None,
            'price':    round(close, 2),
            'hh_14m':   round(hh, 2),
            'll_14m':   round(ll, 2),
        }
    except Exception as e:
        return None


# ─── EMA Cache (EMA10, EMA20, EMA50, EMA200) ────────────────────────

def get_ema_data(ticker: str) -> dict | None:
    """
    Holt EMA10/EMA20/EMA50/EMA200 für einen Yahoo-Ticker.
    Gecacht für 1 Stunde in ema-cache.json.
    SMA-Initialisierung für korrekteren EMA-Startwert.
    Returns: {'ema10': float, 'ema20': float, 'ema50': float, 'ema200': float, 'price': float}
    """
    cache  = load_json(EMA_CACHE_PATH, {})
    now_ts = time.time()

    if ticker in cache:
        entry = cache[ticker]
        if now_ts - entry.get('fetched_at', 0) < 3600:
            return entry

    # TRA-142: EMA aus Daily Close statt Intraday-Snapshots
    # Nutze period1/period2 mit interval=1d für konsistente Tagesdaten
    # 1 Jahr Tagesdaten für EMA200 (braucht ~200 Handelstage)
    import calendar
    end_ts = int(time.time())
    start_ts = end_ts - 365 * 86400  # 1 Jahr zurück
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?period1={start_ts}&period2={end_ts}&interval=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        result = data['chart']['result'][0]
        # Prefer adjusted close for accurate EMA (accounts for splits/dividends)
        adjclose_data = result.get('indicators', {}).get('adjclose', [{}])
        adjcloses = [v for v in (adjclose_data[0].get('adjclose') or []) if v is not None] if adjclose_data else []
        raw_closes = [v for v in (result['indicators']['quote'][0].get('close') or []) if v is not None]
        closes = adjcloses if len(adjcloses) >= len(raw_closes) * 0.9 else raw_closes

        if len(closes) < 20:
            log(f"EMA: zu wenig Daten für {ticker} ({len(closes)} Datenpunkte)")
            return None

        def calc_ema(prices: list, period: int) -> float:
            """EMA mit SMA als korrektem Startwert."""
            if len(prices) < period:
                return prices[-1] if prices else 0.0
            k   = 2 / (period + 1)
            val = sum(prices[:period]) / period  # SMA als Seed
            for p in prices[period:]:
                val = p * k + val * (1 - k)
            return round(val, 4)

        entry = {
            'ema10':  calc_ema(closes, 10),
            'ema20':  calc_ema(closes, 20),
            'ema50':  calc_ema(closes, min(50, len(closes))),
            'ema200': calc_ema(closes, min(200, len(closes))),
            'price':  closes[-1],
            'fetched_at': now_ts,
        }
        cache[ticker] = entry
        save_json(EMA_CACHE_PATH, cache)
        return entry

    except Exception as e:
        log(f"EMA FEHLER {ticker}: {e}")
        return None


# ─── Strategie-Status Parser ─────────────────────────────────────────

def get_strategy_statuses() -> dict:
    """
    Liest alle Strategie-Status aus strategien.md.
    Returns: {1: '🟢🔥', 2: '🟢', 3: '🟡', ...}
    """
    try:
        content = STRATEGIEN_PATH.read_text(encoding='utf-8')
    except FileNotFoundError:
        return {}

    result = {}
    for num in range(1, 8):
        pattern = rf'## STRATEGIE [S]?{num}[:\s].*?\*\*Status:\s*([^\*\n]+)\*\*'
        match   = re.search(pattern, content, re.DOTALL)
        if match:
            status_raw  = match.group(1).strip()
            emoji_match = re.match(r'([\U0001F7E2\U0001F7E1\U0001F534🔥⬆️🚨]+)', status_raw)
            result[num] = emoji_match.group(1) if emoji_match else status_raw[:4]
    return result


_TICKER_TO_STRATEGY = {
    'EQNR': 1, 'EQNR.OL': 1, 'DR0.DE': 1, 'CL=F': 1, 'A3D42Y': 1, 'OIH': 1,
    'ISPA.DE': 1, 'AG': 1, 'A2QQ9R': 1, 'TAN': 1,
    'RHM.DE': 2, 'BAYN.DE': 2,
    'NVDA': 3, 'MSFT': 3, 'PLTR': 3, 'A14WU5': 3, 'CIBR': 3,
    'ISPA': 4, 'GLD': 4,
    'RIO.L': 5, 'BHP.L': 5,
    'A2DWAW': 7, 'IBB': 7,
}


def conviction_score(ticker: str, pos: dict, price_eur: float,
                     stop_eur: float | None, entry_eur: float,
                     vix: float | None, strategy_statuses: dict) -> dict:
    """
    Conviction Score — nutzt TradeMind v2 (8 Faktoren) wenn verfügbar,
    sonst Fallback auf 4-Faktor-Version.
    Returns: {'score': int, 'factors': dict, 'recommendation': str}
    """
    # ── TradeMind v2: 8-Faktor Conviction Scorer ──
    if TRADEMIND_V2:
        try:
            s_num = _TICKER_TO_STRATEGY.get(ticker, 0)
            strategy = f'S{s_num}' if s_num > 0 else 'S1'
            targets = pos.get('targets_eur', []) if isinstance(pos, dict) else []
            target = targets[0] if targets else None
            
            result = _calc_conviction_v2(ticker, strategy, entry_eur, stop_eur, target)
            return {
                'score': int(result['score']),
                'factors': result['factors'],
                'recommendation': result['recommendation'],
            }
        except Exception as e:
            log(f"Conviction v2 fallback für {ticker}: {e}")
    
    # ── Fallback: 4-Faktor-Version ──
    factors = {'trend': 0, 'vix': 0, 'stop_abstand': 0, 'strategie': 0}

    yahoo_ticker = pos.get('yahoo') if isinstance(pos, dict) else ticker
    ema_data = get_ema_data(yahoo_ticker) if yahoo_ticker else None
    if ema_data:
        ema20        = ema_data.get('ema20', 0)
        ema50        = ema_data.get('ema50', 0)
        native_price = ema_data.get('price', 0)
        if native_price > 0 and ema20 > 0 and ema50 > 0:
            if native_price > ema20 and native_price > ema50:
                factors['trend'] = 20
            elif native_price < ema20 and native_price < ema50:
                factors['trend'] = -20

    if vix is not None:
        if vix < 20: factors['vix'] = 20
        elif vix <= 25: factors['vix'] = 0
        elif vix <= 30: factors['vix'] = -10
        else: factors['vix'] = -20

    if stop_eur and price_eur and price_eur > 0:
        abstand_pct = (price_eur - stop_eur) / price_eur * 100
        if abstand_pct > 5: factors['stop_abstand'] = 20
        elif abstand_pct >= 3: factors['stop_abstand'] = 0
        else: factors['stop_abstand'] = -20
    else:
        factors['stop_abstand'] = -20

    s_num    = _TICKER_TO_STRATEGY.get(ticker, 0)
    s_status = strategy_statuses.get(s_num, '🟡')
    if '🟢' in s_status: factors['strategie'] = 20
    elif '🔴' in s_status: factors['strategie'] = -20
    else: factors['strategie'] = 0

    score = max(0, min(100, 50 + sum(factors.values())))

    if score >= 80: recommendation = 'Starkes Signal'
    elif score >= 50: recommendation = 'Moderates Signal'
    elif score >= 20: recommendation = 'Schwaches Signal — Vorsicht'
    else: recommendation = 'Kein Entry / Exit prüfen'

    return {'score': score, 'factors': factors, 'recommendation': recommendation}


# ─── State Snapshot ──────────────────────────────────────────────────

def update_state_snapshot(config: dict, export: dict, strategy_statuses: dict,
                          conviction_scores: dict, all_alerts: list):
    """
    Schreibt memory/state-snapshot.md — der "Weckbrief" für den nächsten Agenten.
    Wird am Ende jeden Monitor-Laufs überschrieben.
    """
    now       = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    positions = export.get('positions', {})
    wl_data   = export.get('watchlist', {})
    macro     = export.get('macro', {})
    fx        = export.get('fx', {})

    # Portfolio-Tabelle
    portfolio_rows  = []
    critical_alerts = []

    for key, p in positions.items():
        if p.get('status') == 'CLOSED':  # TRA-174: CLOSED überspringen
            continue
        price = p.get('price_eur', 0)
        entry = p.get('entry_eur', 0)
        pnl   = p.get('pnl_pct', 0)
        stop  = p.get('stop_eur')
        name  = p.get('name', key)
        conv  = conviction_scores.get(key, {})
        last_alert = _last_alert_for(key, all_alerts)

        stop_str = f"{stop:.2f}€" if stop else "❌ kein Stop"

        if stop and price > 0:
            margin_pct = (price - stop) / price * 100
            if margin_pct < 3:
                critical_alerts.append(
                    f"⚠️ {name} ({key}): {margin_pct:.1f}% über Stop {stop_str}"
                )

        # Relative Stärke vs. QQQ (TRA-179)
        rs_raw = p.get('rs_qqq')
        if rs_raw is not None:
            rs_str = f"+{rs_raw:.1f}x" if rs_raw >= 0 else f"{rs_raw:.1f}x"
        else:
            rs_str = "—"

        portfolio_rows.append(
            f"| {name} ({key}) | {price:.2f}€ | {entry:.2f}€ | {pnl:+.1f}% | "
            f"{stop_str} | {conv.get('score', '—')} | {rs_str} | {last_alert} |"
        )

    portfolio_table = (
        "| Aktie | Kurs | Entry | P&L | Stop | Conviction | RS/QQQ | Letzter Alert |\n"
        "|---|---|---|---|---|---|---|---|\n"
        + "\n".join(portfolio_rows)
    )

    # Watchlist-Tabelle
    wl_rows = []
    # Build watchlist config dict from list
    wl_config_dict = {x['ticker']: x for x in config.get('watchlist', [])}
    for key, w in wl_data.items():
        wconf  = wl_config_dict.get(key, {})
        name   = w.get('name', key)
        price_r = w.get('price_raw', w.get('price_eur', '?'))
        currency = wconf.get('currency', 'USD')
        signal = _watchlist_signal_text(wconf, w)
        wl_rows.append(f"| {name} ({key}) | {price_r} {currency} | {signal} | Beobachten |")

    wl_table = (
        "| Aktie | Kurs | Signal | Status |\n|---|---|---|---|\n" + "\n".join(wl_rows)
    ) if wl_rows else "_(keine Watchlist-Daten)_"

    # Makro-Tabelle
    vix    = macro.get('vix', 0)
    wti    = macro.get('wti', 0)
    nikkei = macro.get('nikkei', 0)
    eurusd = fx.get('EURUSD', 0)
    vix_signal    = '🔴 Panik'   if vix > 30 else ('🟡 Erhöht'  if vix > 20 else '🟢 Normal')
    wti_signal    = '🔴 Nahe $100' if wti > 95 else ('🟡 Erhöht' if wti > 85 else '🟢 Normal')
    nikkei_signal = f"{nikkei:+.1f}%" if nikkei else "—"

    macro_table = (
        "| Indikator | Wert | Signal |\n|---|---|---|\n"
        f"| VIX | {vix:.1f} | {vix_signal} |\n"
        f"| WTI | ${wti:.2f} | {wti_signal} |\n"
        f"| Nikkei 225 | {nikkei_signal} | Öl-Frühindikator |\n"
        f"| EUR/USD | {eurusd:.4f} | — |"
    )

    # Strategie-Status
    strat_names = {
        1: 'Iran/Öl', 2: 'Rüstung', 3: 'KI-Halbleiter',
        4: 'Silber/Gold', 5: 'Rohstoffe/Kupfer', 6: 'Solar/Energie', 7: 'Biotech'
    }
    strat_rows  = [
        f"| S{n} | {strat_names.get(n, f'S{n}')} | {strategy_statuses.get(n, '🟡')} |"
        for n in range(1, 8)
    ]
    strat_table = "| # | Strategie | Status |\n|---|---|---|\n" + "\n".join(strat_rows)

    # Offene Alerts
    queue_path  = WORKSPACE / 'memory' / 'alert-queue.json'
    queue       = load_json(queue_path, [])
    action_items = critical_alerts + [f"🔔 {q['message'][:100]}" for q in queue[-5:]]
    if not action_items:
        action_items = ['✅ Keine kritischen Alerts']
    action_list = '\n'.join(f"- {a}" for a in action_items)

    # Conviction Scores Tabelle
    conv_rows = [
        f"| {key} | {conv.get('score', '?')} | {conv.get('recommendation', '—')} |"
        for key, conv in conviction_scores.items() if conv
    ]
    conv_table = (
        "| Ticker | Score | Empfehlung |\n|---|---|---|\n" + "\n".join(conv_rows)
    ) if conv_rows else "_(Conviction Scores noch nicht berechnet)_"

    pos_count = len(positions)
    snapshot  = f"""# State Snapshot — Trading Bot
**Zuletzt aktualisiert:** {now}
**Positionen:** {pos_count} | **Alerts heute:** {len(all_alerts)} | **Queue:** {len(queue)} ausstehend

---

## Portfolio ({pos_count} Positionen)

{portfolio_table}

## Watchlist

{wl_table}

## Makro

{macro_table}

## Strategien-Status

{strat_table}

## Offene Alerts / Handlungsbedarf

{action_list}

## Letzte Conviction Scores

{conv_table}

---
*Wird automatisch bei jedem Monitor-Lauf (alle 15 Min) überschrieben.*
*Nächster Agent: Lies diese Datei zuerst — sie ist die Basis für Morgen-Briefing + Strategie-Checks.*
"""
    SNAPSHOT_PATH.write_text(snapshot, encoding='utf-8')
    log(f"State Snapshot geschrieben: {pos_count} Positionen, {len(all_alerts)} Alerts")
    # Gleichzeitig positions-live.md aktualisieren
    update_positions_live(config, export)


def update_positions_live(config: dict, export: dict):
    """
    Schreibt memory/positions-live.md — human-readable Single Source of Truth.
    Wird bei jedem Monitor-Lauf synchron mit state-snapshot.md überschrieben.
    Liest direkt aus trading_config.json (Stops, Entries) + live Preise aus export.
    """
    now = datetime.now(tz=ZoneInfo("Europe/Berlin")).strftime('%Y-%m-%d %H:%M CET')
    positions = export.get('positions', {})
    config_pos = config.get('positions', {})

    active_rows = []
    closed_rows = []
    protocol_rows = []

    for key, p in config_pos.items():
        name  = p.get('name', key)
        entry = p.get('entry_eur', 0)
        stop  = p.get('stop_eur')
        stop_str = f"{stop:.2f}€" if stop else "❌ kein Stop"

        if p.get('status') == 'CLOSED':
            exit_eur  = p.get('exit_eur')
            exit_date = p.get('exit_date', '—')
            exit_str  = f"{exit_eur:.2f}€" if exit_eur else "—"
            pnl_str   = f"{((exit_eur - entry) / entry * 100):.1f}%" if exit_eur and entry else "—"
            note      = p.get('notes', '—')
            closed_rows.append(f"| {name} ({key}) | {entry:.2f}€ | {exit_str} | {pnl_str} | {exit_date} | {note} |")
        else:
            live = positions.get(key, {})
            price = live.get('price_eur', 0)
            pnl   = live.get('pnl_pct', 0)
            price_str = f"{price:.2f}€" if price else "—"
            pnl_str   = f"{pnl:+.1f}%" if price else "—"
            note      = p.get('notes', '—')
            active_rows.append(f"| {name} ({key}) | {entry:.2f}€ | {stop_str} | {price_str} | {pnl_str} | {note} |")

    # Update-Protokoll: letzte 10 Einträge aus bestehendem File lesen
    live_path = WORKSPACE / 'memory' / 'positions-live.md'
    existing_protocol = ""
    if live_path.exists():
        content = live_path.read_text(encoding='utf-8')
        if '## 📋 Update-Protokoll' in content:
            existing_protocol = content.split('## 📋 Update-Protokoll')[1].split('---')[0].strip()

    active_table = "\n".join(active_rows) if active_rows else "| — | — | — | — | — | Keine aktiven Positionen |"
    closed_table = "\n".join(closed_rows) if closed_rows else "| — | — | — | — | — | — |"

    md = f"""# Positions Live — Einzige Wahrheitsquelle für aktuelle Positionen

> **PFLICHT:** Nach jeder Stop-Änderung, jedem Kauf/Verkauf sofort hier updaten.
> **Sync:** Albert updated immer GLEICHZEITIG diese Datei + trading_config.json
> Format: immer in EUR. Letzter Update-Zeitstempel pflegen.

**Zuletzt aktualisiert:** {now} (Auto-Sync vom Monitor)

---

## 🟢 Aktive Positionen

| Name (Ticker) | Entry | Stop (REAL in TR) | Letzter Kurs | P&L | Notiz |
|---|---|---|---|---|---|
{active_table}

---

## ✅ Geschlossene Positionen (letzte 30 Tage)

| Name (Ticker) | Entry | Exit | P&L | Datum | Notiz |
|---|---|---|---|---|---|
{closed_table}

---

## 📋 Update-Protokoll

{existing_protocol}

---

## ⚡ Sync-Regeln (PFLICHT)

Wenn Victor eine Stop-Änderung oder einen Trade mitteilt:
1. `trading_config.json` updaten (positions Array) — Monitor liest von hier
2. Diese Datei wird beim nächsten Monitor-Run (alle 15 Min) automatisch aktualisiert
3. Bei dringenden Änderungen: Albert updated beide Dateien sofort manuell
4. `state-snapshot.md` = Monitor-Output mit live Preisen, kann 15 Min veraltet sein
5. `projekt-trading.md` = nur Strategie-Doku — NICHT für live Daten
"""
    live_path.write_text(md, encoding='utf-8')
    log(f"positions-live.md aktualisiert: {len(active_rows)} aktiv, {len(closed_rows)} geschlossen")


def _last_alert_for(ticker: str, alerts: list) -> str:
    for alert in reversed(alerts):
        if ticker in alert:
            if 'STOP'    in alert.upper(): return 'Stop-Warnung'
            if 'ZIEL'    in alert.upper(): return 'Ziel erreicht'
            if 'TRAIL'   in alert.upper(): return 'Trailing'
            return 'Signal'
    return '—'


def _watchlist_signal_text(wconf: dict, wdata: dict) -> str:
    price_eur = wdata.get('price_eur', 0)
    price_raw = wdata.get('price_raw', 0)
    if not price_eur:
        return '—'
    sig_a  = wconf.get('signal_a_above_eur')
    sig_b  = wconf.get('signal_b_below_eur')
    entry_b = wconf.get('entry_b_below_eur')
    ea_usd  = wconf.get('entry_a_above_usd')
    eb_usd  = wconf.get('entry_b_below_usd')
    if sig_a   and price_eur >= sig_a:   return f'Signal A aktiv (>{sig_a}€)'
    if sig_b   and price_eur <= sig_b:   return f'Signal B aktiv (<{sig_b}€)'
    if entry_b and price_eur <= entry_b: return f'Entry B Zone (<{entry_b}€)'
    if ea_usd  and price_raw >= ea_usd:  return f'Entry A aktiv (>${ea_usd})'
    if eb_usd  and price_raw <= eb_usd:  return f'Entry B aktiv (<${eb_usd})'
    return 'Kein Signal'


def write_overnight_context(export: dict, all_alerts: list, strategy_statuses: dict):
    """
    Schreibt memory/overnight-context.md — Tagesabschluss für Morgen-Briefing.
    Nur nach 21:00 Berliner Zeit aufrufen.
    """
    now       = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    today_str = berlin_now().strftime('%d.%m.%Y')
    macro     = export.get('macro', {})
    positions = export.get('positions', {})

    sorted_pos = sorted(positions.items(), key=lambda x: x[1].get('pnl_pct', 0))
    losers  = [(k, v) for k, v in sorted_pos            if v.get('pnl_pct', 0) < 0][:3]
    winners = [(k, v) for k, v in reversed(sorted_pos)  if v.get('pnl_pct', 0) > 0][:3]

    crit_stops = [
        f"{p['name']} ({k}): {(p['price_eur']-p['stop_eur'])/p['price_eur']*100:.1f}% über Stop {p['stop_eur']:.2f}€"
        for k, p in positions.items()
        if p.get('stop_eur') and p.get('price_eur') and (p['price_eur'] - p['stop_eur']) / p['price_eur'] * 100 < 3
    ]

    winners_str = '\n'.join(f"- {v['name']} ({k}): {v['price_eur']:.2f}€ ({v['pnl_pct']:+.1f}%)" for k, v in winners) or '— keine'
    losers_str  = '\n'.join(f"- {v['name']} ({k}): {v['price_eur']:.2f}€ ({v['pnl_pct']:+.1f}%)" for k, v in losers)  or '— keine'
    alerts_str  = '\n'.join(f"- {a[:120]}" for a in all_alerts[-10:]) or '— keine Alerts heute'
    crit_str    = '\n'.join(f"- ⚠️ {c}" for c in crit_stops) or '— alle Stops sicher'

    strat_names = {1: 'Iran/Öl', 2: 'Rüstung', 3: 'KI-Halbleiter',
                   4: 'Silber/Gold', 5: 'Rohstoffe', 6: 'Solar', 7: 'Biotech'}
    strat_str = '\n'.join(f"- S{n} ({strat_names.get(n,'?')}): {s}" for n, s in strategy_statuses.items())

    content = f"""# Overnight Context — {today_str}
*Erstellt: {now} | Für Morgen-Briefing 08:00*

---

## Was heute passiert ist

### Wichtigste Alerts
{alerts_str}

### Top-Performer heute
{winners_str}

### Underperformer / Verlierer
{losers_str}

## Kritische Positionen (Stop <3% entfernt)

{crit_str}

## Geopolitik-Lage (aus Strategie-Status)

{strat_str}

## Makro-Schlusskurse

- VIX: {macro.get('vix', '?')}
- WTI: ${macro.get('wti', '?')}
- EUR/USD: {export.get('fx', {}).get('EURUSD', '?')}

## Entscheidungen die morgen anstehen

- [ ] Alle Stops in Trade Republic prüfen (besonders kritische oben)
- [ ] Conviction-Scores bei Stop-nahen Positionen neu bewerten

---
*Morgen-Agent: Lies state-snapshot.md + diese Datei → dann Morgen-Briefing ausführen*
"""
    OVERNIGHT_PATH.write_text(content, encoding='utf-8')
    log(f"Overnight Context geschrieben: {today_str}")


# ─── Main ────────────────────────────────────────────────────────────

def main():
    # ── Single Source of Truth Sync (positions-live.md → config + DB) ──
    try:
        import subprocess
        sync_script = Path(__file__).parent / 'sync_positions.py'
        if sync_script.exists():
            result = subprocess.run(
                ['python3', str(sync_script)],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                print(f"⚠️  Positions-Sync Fehler: {result.stderr[:200]}")
    except Exception as e:
        print(f"⚠️  Positions-Sync konnte nicht ausgeführt werden: {e}")

    config = load_json(CONFIG_PATH)
    if not config:
        log("FEHLER: trading_config.json nicht gefunden oder leer!")
        print("FEHLER: Config nicht gefunden")
        return

    # State laden + tagesabhängiges Reset
    state = load_json(STATE_PATH, {})
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if state.get('date') != today:
        # Tägliches Reset: sent_today + run_count — ABER trail_sent bleibt erhalten!
        trail_sent_carry = state.get('trail_sent', {})
        state = {'date': today, 'alerts_sent_today': [], 'run_count': 0,
                 'trail_sent': trail_sent_carry}

    # sent_today als Set (O(1) Lookup) — beim Speichern zurück zu List
    state['alerts_sent_today'] = set(state.get('alerts_sent_today', []))
    state['run_count'] = state.get('run_count', 0) + 1
    # trail_sent: permanenter Dict {key: date_str} — überlebt tägliches Reset
    if 'trail_sent' not in state:
        state['trail_sent'] = {}

    # ── Alle Yahoo-Ticker sammeln ──
    yahoo_tickers = set(['EURUSD=X', 'EURNOK=X', 'GBPEUR=X'])
    yahoo_tickers.add(config.get('macro', {}).get('wti_ticker', 'CL=F'))
    yahoo_tickers.add(config.get('macro', {}).get('vix_ticker', '^VIX'))
    yahoo_tickers.add(config.get('macro', {}).get('nikkei_ticker', '^N225'))
    yahoo_tickers.add(config.get('macro', {}).get('brent_ticker', 'BZ=F'))    # TRA-177: Brent Crude
    yahoo_tickers.add(config.get('macro', {}).get('sx7e_ticker', 'EXV1.DE'))  # TRA-178: Euro Stoxx Banks
    yahoo_tickers.add('QQQ')                                                   # TRA-179: Nasdaq RS
    yahoo_tickers.add(config.get('macro', {}).get('fedex_ticker', 'FDX'))     # Eriksen: Realwirtschafts-Frühindikator

    for pos in config.get('positions', {}).values():
        if pos.get('yahoo'):
            yahoo_tickers.add(pos['yahoo'])
    for watch in config.get('watchlist', []):
        if watch.get('yahoo'):
            yahoo_tickers.add(watch['yahoo'])

    # ── Batch-Fetch Yahoo ──
    log(f"Fetching {len(yahoo_tickers)} Yahoo tickers...")
    prices = yahoo_batch(list(yahoo_tickers))

    # FX extrahieren
    fx = {}
    for fx_key, fx_ticker in [('EURUSD', 'EURUSD=X'), ('EURNOK', 'EURNOK=X'), ('GBPEUR', 'GBPEUR=X')]:
        if fx_ticker in prices:
            fx[fx_key] = prices[fx_ticker]['price']

    # FX-Alert wenn EUR/USD fehlt
    if not fx.get('EURUSD'):
        log("WARNUNG: EUR/USD nicht verfügbar — Konvertierungen eingeschränkt")
        send_alert("⚠️ EUR/USD Kurs nicht abrufbar — USD/NOK/GBP-Positionen ohne Währungsumrechnung!")

    # ── Onvista: einmalig vorabladen (kein Doppel-Crawl) ──
    log("Fetching Onvista prices (cache)...")
    onvista_cache = prefetch_onvista(config)

    # ── Strategie-Status ──
    strategy_statuses = get_strategy_statuses()

    # ── Conviction Cache ──
    conviction_cache = {}

    # ── Alle Checks ──
    all_alerts  = []
    all_alerts += check_positions(config, prices, fx, state, onvista_cache, strategy_statuses, conviction_cache)
    all_alerts += check_watchlist(config, prices, fx, state, onvista_cache)
    all_alerts += check_macro(config, prices, state)

    for alert in all_alerts:
        send_alert(alert)

    # ── State speichern (Set → List für JSON, trail_sent bleibt Dict) ──
    state['last_run'] = datetime.now(timezone.utc).isoformat()
    state_to_save = {**state, 'alerts_sent_today': list(state['alerts_sent_today'])}
    # trail_sent ist bereits ein Dict — direkt speichern
    save_json(STATE_PATH, state_to_save)

    # ── Export für AI-Jobs (latest-prices.json) ──
    export = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'fx':        fx,
        'macro':     {},
        'positions': {},
        'watchlist': {},
    }

    wti_t   = config.get('macro', {}).get('wti_ticker', 'CL=F')
    vix_t   = config.get('macro', {}).get('vix_ticker', '^VIX')
    nk_t    = config.get('macro', {}).get('nikkei_ticker', '^N225')
    if wti_t in prices: export['macro']['wti']    = prices[wti_t]['price']
    if vix_t in prices: export['macro']['vix']    = prices[vix_t]['price']
    if nk_t  in prices: export['macro']['nikkei'] = prices[nk_t]['change_pct']

    # QQQ für Relative Stärke (TRA-179)
    qqq_data   = prices.get('QQQ', {})
    qqq_change = qqq_data.get('change_pct') if qqq_data else None

    # Positionen (nutzt onvista_cache — kein zweiter Crawl)
    for key, pos in config.get('positions', {}).items():
        if pos.get('status') == 'CLOSED':  # TRA-174: CLOSED überspringen
            continue
        price_eur, price_raw = get_price_eur(pos, prices, fx, onvista_cache, key)
        if price_eur is not None:
            entry = pos.get('entry_eur', 0)
            pnl   = (price_eur - entry) / entry * 100 if entry else 0

            # Relative Stärke vs. QQQ (TRA-179)
            yahoo_t    = pos.get('yahoo')
            pos_change = prices[yahoo_t].get('change_pct') if (yahoo_t and yahoo_t in prices) else None
            rs_qqq     = None
            if pos_change is not None and qqq_change and abs(qqq_change) > 0.1:
                rs_qqq = round(pos_change / qqq_change, 2)

            export['positions'][key] = {
                'name':      pos['name'],
                'price_eur': round(price_eur, 2),
                'price_raw': round(price_raw, 2) if price_raw else None,
                'entry_eur': entry,
                'pnl_pct':   round(pnl, 2),
                'stop_eur':  pos.get('stop_eur'),
                'rs_qqq':    rs_qqq,
            }

    # Watchlist (nutzt onvista_cache)
    for watch in config.get('watchlist', []):
        key = watch['ticker']
        price_eur, price_raw = get_price_eur(watch, prices, fx, onvista_cache, key)
        if price_raw is not None:
            export['watchlist'][key] = {
                'ticker':    key,
                'name':      watch['name'],
                'price_eur': round(price_eur, 2) if price_eur else None,
                'price_raw': round(price_raw, 2),
            }

    # Conviction Scores einbauen
    for key, conv in conviction_cache.items():
        if key in export['positions']:
            export['positions'][key]['conviction'] = conv.get('score')
    save_json(PRICES_PATH, export)

    # ── TradeMind v2: Regime + Risk in Export einbauen ──
    if TRADEMIND_V2:
        try:
            regime = _detect_regime()
            export['regime'] = {
                'current': regime['regime'],
                'velocity': regime.get('velocity', 'UNKNOWN'),
                'vix': regime['factors'].get('vix'),
                'sp500_vs_ma200': regime['factors'].get('sp500_vs_ma200'),
            }
            log(f"Regime: {regime['regime']} (Velocity: {regime.get('velocity')})")
        except Exception as e:
            log(f"Regime detection error: {e}")
        
        try:
            risk = _risk_report()
            export['risk'] = {
                'score': risk['risk_score'],
                'label': risk['risk_label'],
            }
            log(f"Risk Score: {risk['risk_score']}/100 ({risk['risk_label']})")
        except Exception as e:
            log(f"Risk report error: {e}")

    # ── State Snapshot ──
    update_state_snapshot(config, export, strategy_statuses, conviction_cache, all_alerts)

    # ── Overnight Context (nur nach 21:00 Berliner Zeit, Sommer+Winter korrekt) ──
    if berlin_now().hour >= 21:
        write_overnight_context(export, all_alerts, strategy_statuses)

    # ── Summary Output ──
    if all_alerts:
        print(f"ALERTS: {len(all_alerts)}")
        for a in all_alerts:
            print(f"  → {a[:120]}")
    else:
        pos_summary = [
            f"{key} {p['price_eur']:.2f}€ ({p['pnl_pct']:+.1f}%)"
            for key, p in export.get('positions', {}).items()
        ]
        macro_s = f"WTI ${export['macro'].get('wti','?')} | VIX {export['macro'].get('vix','?')}"
        print(f"KEIN_SIGNAL | {macro_s} | {' | '.join(pos_summary)}")


if __name__ == '__main__':
    main()
