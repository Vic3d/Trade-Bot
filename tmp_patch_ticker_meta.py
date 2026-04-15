#!/usr/bin/env python3
"""
tmp_patch_ticker_meta.py
========================
Patch 2: Erweitert TICKER_META in scripts/core/candidate_discovery.py
         um ~60 zusätzliche Ticker (US, EU, DE, UK, Asia, Canada, Australia).

Vorgehen:
  1. Datei lesen
  2. TICKER_META = { … } per Klammer-Balancierung vollständig lokalisieren
  3. Ersetzen durch neue, erweiterte Version
  4. py_compile prüfen
  5. OK ausgeben
"""

import py_compile
import sys
from pathlib import Path

# ── Pfad-Setup ──────────────────────────────────────────────────────────────
WS_LOCAL = Path(__file__).resolve().parent
VPS_ROOT  = Path('/opt/trademind')

def _target(rel: str) -> Path:
    local = WS_LOCAL / rel
    if local.exists():
        return local
    vps = VPS_ROOT / rel
    if vps.exists():
        return vps
    raise FileNotFoundError(f"Weder {local} noch {vps} gefunden.")


TARGET_REL = 'scripts/core/candidate_discovery.py'

# ── Neue TICKER_META — vollständig ──────────────────────────────────────────
NEW_TICKER_META = """\
TICKER_META: dict[str, tuple[str, str]] = {
    # US Technology
    'NVDA':     ('Technology',  'US'),
    'MU':       ('Technology',  'US'),
    'MRVL':     ('Technology',  'US'),
    'ADBE':     ('Technology',  'US'),
    'ADSK':     ('Technology',  'US'),
    'MSFT':     ('Technology',  'US'),
    'AAPL':     ('Technology',  'US'),
    'GOOGL':    ('Technology',  'US'),
    'META':     ('Technology',  'US'),
    'AMZN':     ('Technology',  'US'),
    'ORCL':     ('Technology',  'US'),
    'CRM':      ('Technology',  'US'),
    'PLTR':     ('Technology',  'US'),
    'SNOW':     ('Technology',  'US'),
    # US Space / Defense
    'RKLB':     ('Space',       'US'),
    'ASTS':     ('Space',       'US'),
    'LMT':      ('Defense',     'US'),
    'RTX':      ('Defense',     'US'),
    'NOC':      ('Defense',     'US'),
    'BA':       ('Defense',     'US'),
    # US Energy / Oil
    'OXY':      ('Energy',      'US'),
    'XOM':      ('Energy',      'US'),
    'CVX':      ('Energy',      'US'),
    'PSX':      ('Energy',      'US'),
    'DINO':     ('Energy',      'US'),
    'MPC':      ('Energy',      'US'),
    # US Tanker
    'FRO':      ('Tanker',      'US'),
    'DHT':      ('Tanker',      'US'),
    'EURN':     ('Tanker',      'US'),
    'TK':       ('Tanker',      'US'),
    # US Finance
    'JPM':      ('Finance',     'US'),
    'GS':       ('Finance',     'US'),
    'MS':       ('Finance',     'US'),
    'BAC':      ('Finance',     'US'),
    # US Clean Energy
    'BE':       ('CleanEnergy', 'US'),
    'FSLR':     ('CleanEnergy', 'US'),
    'ENPH':     ('CleanEnergy', 'US'),
    # US Biotech / Pharma
    'NVO':      ('Pharma',      'US'),
    'LLY':      ('Pharma',      'US'),
    'PFE':      ('Pharma',      'US'),
    'UNH':      ('Healthcare',  'US'),
    # Frankfurt / XETRA
    'SIE.DE':   ('Industry',    'DE'),
    'SAP.DE':   ('Technology',  'DE'),
    'RHM.DE':   ('Defense',     'DE'),
    'ALV.DE':   ('Finance',     'DE'),
    'BMW.DE':   ('Auto',        'DE'),
    'MUV2.DE':  ('Finance',     'DE'),
    'BAS.DE':   ('Chemicals',   'DE'),
    'IFX.DE':   ('Technology',  'DE'),
    'DTE.DE':   ('Telecom',     'DE'),
    'VOW3.DE':  ('Auto',        'DE'),
    'MBG.DE':   ('Auto',        'DE'),
    'ADS.DE':   ('Consumer',    'DE'),
    'DBK.DE':   ('Finance',     'DE'),
    'HEN3.DE':  ('Consumer',    'DE'),
    # Euronext Paris / Amsterdam
    'AIR.PA':   ('Defense',     'EU'),
    'MC.PA':    ('Luxury',      'EU'),
    'BNP.PA':   ('Finance',     'EU'),
    'SAN.PA':   ('Finance',     'EU'),
    'TTE.PA':   ('Energy',      'EU'),
    'OR.PA':    ('Consumer',    'EU'),
    'ASML.AS':  ('Technology',  'EU'),
    'PHIA.AS':  ('Technology',  'EU'),
    # London
    'SHEL.L':   ('Energy',      'UK'),
    'AZN.L':    ('Pharma',      'UK'),
    'BP.L':     ('Energy',      'UK'),
    'HSBA.L':   ('Finance',     'UK'),
    'VOD.L':    ('Telecom',     'UK'),
    'RIO.L':    ('Mining',      'UK'),
    # Norway
    'EQNR':     ('Energy',      'NO'),
    # Asia — Japan
    '7203.T':   ('Auto',        'JP'),
    '6758.T':   ('Technology',  'JP'),
    '9984.T':   ('Technology',  'JP'),
    '8306.T':   ('Finance',     'JP'),
    # Asia — Hong Kong / China
    '9988.HK':  ('Technology',  'HK'),
    '0700.HK':  ('Technology',  'HK'),
    '9999.HK':  ('Technology',  'HK'),
    '2318.HK':  ('Finance',     'HK'),
    # Canada
    'SHOP.TO':  ('Technology',  'CA'),
    'CNQ.TO':   ('Energy',      'CA'),
    # Australia
    'BHP.AX':   ('Mining',      'AU'),
    'CBA.AX':   ('Finance',     'AU'),
}\
"""


def _find_dict_end(text: str, start_idx: int) -> int:
    """
    Gibt den Index des schließenden '}' zurück, das zum öffnenden '{' gehört,
    das sich in text[start_idx:] befindet.
    Berücksichtigt verschachtelte Klammern und ignoriert Strings.
    """
    depth = 0
    i = start_idx
    in_single = False
    in_double = False

    while i < len(text):
        ch = text[i]

        # String-Grenzen (einfache/doppelte Anführungszeichen, kein Triple-String-Support nötig)
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return i
        i += 1

    raise ValueError("Kein schließendes '}' für TICKER_META gefunden.")


def patch_ticker_meta() -> None:
    target = _target(TARGET_REL)
    original = target.read_text(encoding='utf-8')

    # Alle neuen Ticker bereits drin?
    if "'MSFT'" in original and "'SHOP.TO'" in original and "'BHP.AX'" in original:
        print("[candidate_discovery.py] TICKER_META bereits erweitert — übersprungen.")
        return

    # Start des Dicts finden
    marker = 'TICKER_META: dict[str, tuple[str, str]] = {'
    start_marker_idx = original.find(marker)
    if start_marker_idx == -1:
        # Fallback ohne Typ-Annotation
        marker = 'TICKER_META = {'
        start_marker_idx = original.find(marker)
    if start_marker_idx == -1:
        raise ValueError("[candidate_discovery.py] TICKER_META-Definition nicht gefunden.")

    # Index des öffnenden '{'
    open_brace_idx = original.index('{', start_marker_idx)
    close_brace_idx = _find_dict_end(original, open_brace_idx)

    # Altes Dict herausschneiden und ersetzen
    old_block = original[start_marker_idx : close_brace_idx + 1]
    patched   = original.replace(old_block, NEW_TICKER_META, 1)

    target.write_text(patched, encoding='utf-8')
    print(f"[candidate_discovery.py] TICKER_META ersetzt ({len(NEW_TICKER_META)} Bytes).")

    try:
        py_compile.compile(str(target), doraise=True)
        print("[candidate_discovery.py] py_compile OK")
    except py_compile.PyCompileError as e:
        target.write_text(original, encoding='utf-8')
        raise RuntimeError(f"[candidate_discovery.py] Syntaxfehler — Patch zurückgerollt: {e}") from e


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    try:
        patch_ticker_meta()
        print("\nPatch 2 (TICKER_META Erweiterung) erfolgreich abgeschlossen.")
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        sys.exit(1)
