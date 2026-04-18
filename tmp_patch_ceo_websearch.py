#!/usr/bin/env python3
"""
Patch-Script A: CEO Web Search Integration + Trader Intel in build_context()
Ziel: /opt/trademind/scripts/autonomous_ceo.py

Führt zwei Änderungen durch:
  A) execute_deep_dive() → Web Search Tool + News Scraper + text extraction
  B) build_context() → Trader Intel + Candidate Queue vor 6b. MULTI-EXCHANGE WATCHLIST

Aufruf: python3 /tmp/tmp_patch_ceo_websearch.py
"""
import sys
import py_compile
import tempfile
import os

TARGET = '/opt/trademind/scripts/autonomous_ceo.py'

# ─── A) PATCH: execute_deep_dive() API-Call ───────────────────────────────────

OLD_DEEP_DIVE_API = '''        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            messages=[{'role': 'user', 'content': prompt}],
        )
        response_text = response.content[0].text'''

NEW_DEEP_DIVE_API = '''        # News via Scraper holen
        scraped_context = ''
        try:
            import sys as _sys
            _core = str(WS / 'scripts' / 'core')
            if _core not in _sys.path:
                _sys.path.insert(0, _core)
            from news_scraper import search_news
            news_items = search_news(f'{ticker} stock news catalyst', tickers=[ticker], days=3)
            if news_items:
                scraped_context = '\\n\\nAKTUELLE NEWS (live gescrapt):\\n'
                for item in news_items[:5]:
                    scraped_context += f"- [{item.get('source','')}] {item.get('title','')}\\n"
                    if item.get('text'):
                        scraped_context += f"  {item['text'][:300]}...\\n"
        except Exception as _se:
            log(f'Deep Dive {ticker}: scraper unavailable ({_se})', 'WARN')

        # Prompt erweitern
        prompt = prompt + scraped_context

        client = anthropic.Anthropic(api_key=api_key)

        # Web Search Tool definieren
        tools = [{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }]

        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=3000,
                tools=tools,
                messages=[{'role': 'user', 'content': prompt}],
            )
        except Exception as _we:
            # Fallback ohne Web Search wenn Tool nicht verfügbar
            log(f'Deep Dive {ticker}: web_search unavailable, fallback ({_we})', 'WARN')
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2000,
                messages=[{'role': 'user', 'content': prompt}],
            )

        # Text aus Response extrahieren (auch bei tool_use Blöcken)
        response_text = ''
        for block in response.content:
            if hasattr(block, 'text'):
                response_text += block.text'''

# ─── B) PATCH: build_context() — Trader Intel vor 6b ────────────────────────

OLD_6B_MARKER = '''    # 6b. MULTI-EXCHANGE WATCHLIST (Frankfurt/EU/Asien live)'''

NEW_6B_BLOCK = '''    # 6a. TRADER INTELLIGENCE (YouTube/News Signale)
    try:
        import sys as _sys
        _core = str(WS / 'scripts' / 'core')
        if _core not in _sys.path:
            _sys.path.insert(0, _core)
        from trader_intel import get_daily_intel_summary
        from candidate_discovery import format_for_ceo, get_sector_balance
        intel_summary = get_daily_intel_summary()
        if intel_summary:
            parts.append(intel_summary)
        candidate_block = format_for_ceo()
        if candidate_block:
            parts.append(candidate_block)
        sector_warn = get_sector_balance([])
        if sector_warn:
            parts.append(f'\\n\u26a0\ufe0f SEKTOR-WARNUNG: {sector_warn}')
    except Exception as _ie:
        parts.append(f'\\n[Trader Intel nicht verfügbar: {_ie}]')

    # 6b. MULTI-EXCHANGE WATCHLIST (Frankfurt/EU/Asien live)'''


def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def verify_syntax(path):
    try:
        py_compile.compile(path, doraise=True)
        return True
    except py_compile.PyCompileError as e:
        print(f'SYNTAX ERROR: {e}')
        return False


def patch_A(content):
    """Patch A: Web Search in execute_deep_dive()"""
    sentinel_a = 'web_search_20250305'
    if sentinel_a in content:
        print('[A] SKIP — Web Search bereits gepatcht (idempotent)')
        return content, False

    if OLD_DEEP_DIVE_API not in content:
        # Try alternative spacing (server may differ slightly)
        alt_old = '''        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{'role': 'user', 'content': prompt}],
        )
        response_text = response.content[0].text'''
        if alt_old in content:
            print('[A] Fallback: patching max_tokens=2000 variant')
            new_content = content.replace(alt_old, NEW_DEEP_DIVE_API, 1)
            return new_content, True
        raise SystemExit(
            f'[A] FEHLER: OLD-String nicht gefunden in {TARGET}.\n'
            'Bitte prüfen ob autonomous_ceo.py korrekt ist.'
        )

    new_content = content.replace(OLD_DEEP_DIVE_API, NEW_DEEP_DIVE_API, 1)
    print('[A] OK — Web Search Patch angewendet')
    return new_content, True


def patch_B(content):
    """Patch B: Trader Intel Block vor 6b MULTI-EXCHANGE"""
    sentinel_b = '# 6a. TRADER INTELLIGENCE'
    if sentinel_b in content:
        print('[B] SKIP — Trader Intel bereits gepatcht (idempotent)')
        return content, False

    if OLD_6B_MARKER not in content:
        print(
            f'[B] WARN — "# 6b. MULTI-EXCHANGE WATCHLIST" nicht gefunden.\n'
            f'    Patch B wird übersprungen — bitte manuell prüfen ob Section in {TARGET} existiert.'
        )
        return content, False

    new_content = content.replace(OLD_6B_MARKER, NEW_6B_BLOCK, 1)
    print('[B] OK — Trader Intel Block vor 6b eingefügt')
    return new_content, True


def main():
    if not os.path.exists(TARGET):
        raise SystemExit(f'FEHLER: Zieldatei nicht gefunden: {TARGET}')

    print(f'Lese {TARGET} ...')
    content = read_file(TARGET)
    original = content

    content, changed_a = patch_A(content)
    content, changed_b = patch_B(content)

    if not changed_a and not changed_b:
        print('Keine Änderungen nötig — alles bereits gepatcht.')
        sys.exit(0)

    # Syntax-Check in temporärer Datei
    with tempfile.NamedTemporaryFile(suffix='.py', delete=False, mode='w', encoding='utf-8') as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        if not verify_syntax(tmp_path):
            raise SystemExit('[FEHLER] Syntax-Check fehlgeschlagen — Datei NICHT geschrieben!')
    finally:
        os.unlink(tmp_path)

    write_file(TARGET, content)
    print(f'OK — {TARGET} erfolgreich gepatcht und Syntax verifiziert.')


if __name__ == '__main__':
    main()
