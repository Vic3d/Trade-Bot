#!/usr/bin/env python3
"""
source_consistency_audit.py — Phase 45ac (Victor 2026-05-07).

User-Direktive: 'Lass uns durch das ganze Projekt durchfahren und gucken
ob auch andere Dateien betroffen sind.'

Audit-Skript das systematisch nach Quellen-Inkonsistenzen sucht.
Wiederholbar — produziert Markdown-Bericht in
data/source_consistency_report.md.

4 Audit-Kategorien:
  1. Schema-Audit: Spalten-Konventionen (Prozent vs Fraction, EUR vs native)
  2. Currency-Audit: Currency-Mismatch zwischen paper_portfolio und prices
  3. Cross-Source: Cash + Open-Positions + Strategy-Status aus mehreren Quellen
  4. Health-Indikator: File-mtime als Job-Health (Silence-Detector-Bug-Klasse)

Run: python3 scripts/source_consistency_audit.py
"""
from __future__ import annotations
import json, os, re, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
REPORT = WS / 'data' / 'source_consistency_report.md'


# ─────────────────────────────────────────────────────────────────────
# 1. SCHEMA-AUDIT: Spalten-Konventionen
# ─────────────────────────────────────────────────────────────────────

def audit_schema() -> list[dict]:
    """Sucht inkonsistente Spalten-Konventionen.

    Konkret: Spalten die wir wissen sind kritisch:
      - paper_portfolio.pnl_pct: ist Prozent (nach Phase 45o)
      - paper_portfolio.close_price: EUR-konvertiert (für offene Pos.)
      - prices.close: native currency
      - paper_fund.value (current_cash): EUR
    """
    findings = []
    if not DB.exists(): return findings
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    # Check 1: pnl_pct-Distribution. Wenn |pnl_pct| > 100 → wahrscheinlich
    # Doppel-Prozent (mit *100 reingeschrieben statt Fraction).
    big_pct = c.execute(
        "SELECT id, ticker, pnl_pct FROM paper_portfolio "
        "WHERE pnl_pct IS NOT NULL AND ABS(pnl_pct) > 100"
    ).fetchall()
    if big_pct:
        findings.append({
            'category': 'schema',
            'severity': 'critical',
            'issue': f'paper_portfolio.pnl_pct: {len(big_pct)} Trades mit |pnl_pct| > 100',
            'detail': 'Wahrscheinlich Doppel-Prozent-Schreiber (Fraction × 100). '
                     'Konvention sollte sein: pnl_pct = bereits Prozent (z.B. -5.0 für -5%).',
            'samples': [(r['id'], r['ticker'], r['pnl_pct']) for r in big_pct[:5]],
            'recommendation': 'Migration: alle pnl_pct mit |x|>100 durch 100 dividieren.',
        })

    # Check 2: close_price = entry_price (Stop = Entry, sollte 0%-Stop nicht möglich)
    zero_stop = c.execute(
        "SELECT id, ticker, entry_price, stop_price FROM paper_portfolio "
        "WHERE stop_price IS NOT NULL AND entry_price IS NOT NULL "
        "  AND ABS(stop_price - entry_price) / entry_price < 0.01"
    ).fetchall()
    if zero_stop:
        findings.append({
            'category': 'schema',
            'severity': 'warning',
            'issue': f'paper_portfolio: {len(zero_stop)} Trades mit Stop-Distance < 1%',
            'detail': 'Phase 44n-Doktrin verlangt min 4%. Phase 45ab Guard 0b2 jetzt aktiv.',
            'samples': [(r['id'], r['ticker'], r['entry_price'], r['stop_price']) for r in zero_stop[:5]],
            'recommendation': 'Historische Trades als Lesson dokumentieren.',
        })

    # Check 3: close_date Format-Inkonsistenz
    sample_close_dates = c.execute(
        "SELECT DISTINCT substr(close_date, 1, 19) AS fmt "
        "FROM paper_portfolio WHERE close_date IS NOT NULL LIMIT 20"
    ).fetchall()
    formats = set()
    for r in sample_close_dates:
        f = r['fmt']
        if not f: continue
        if 'T' in f and '+' in f: formats.add('isoformat_with_tz')
        elif 'T' in f: formats.add('isoformat_naive')
        elif ' ' in f: formats.add('space_separated')
    if len(formats) > 1:
        findings.append({
            'category': 'schema',
            'severity': 'warning',
            'issue': f'paper_portfolio.close_date: {len(formats)} verschiedene Formate',
            'detail': f'Formate: {sorted(formats)}',
            'recommendation': 'Migration auf einheitliches isoformat_with_tz.',
        })

    # Check 4: trades-Tabelle vs paper_portfolio Strategy-SID Overlap
    # (Phantom-Trades: Swing-SIDs in trades-Tabelle die nicht hingehoeren)
    try:
        phantom_swing = c.execute(
            "SELECT COUNT(*) FROM trades "
            "WHERE strategy LIKE 'PS%' OR strategy LIKE 'S\\_%' ESCAPE '\\\\' "
            "   OR strategy IN ('PT', 'PM')"
        ).fetchone()[0]
        if phantom_swing > 0:
            findings.append({
                'category': 'schema',
                'severity': 'warning',
                'issue': f'trades-Tabelle hat {phantom_swing} Eintraege mit Swing-SIDs',
                'detail': 'Phase 45o: trades-Tabelle sollte nur DT*-SIDs enthalten. '
                         'load_closed_day_trades filtert bereits, aber Daten bleiben unsauber.',
                'recommendation': 'Optional: Swing-SIDs aus trades archivieren.',
            })
    except Exception: pass

    c.close()
    return findings


# ─────────────────────────────────────────────────────────────────────
# 2. CURRENCY-AUDIT
# ─────────────────────────────────────────────────────────────────────

EU_SUFFIXES = ('.DE', '.PA', '.AS', '.MI', '.MC', '.OL', '.VI', '.SW',
               '.L', '.ST', '.CO', '.HE', '.BR', '.LS')
ASIA_SUFFIXES = ('.HK', '.T', '.SS', '.SZ')


def audit_currency() -> list[dict]:
    """Currency-Mismatch zwischen paper_portfolio (EUR-conv) und prices (native)."""
    findings = []
    if not DB.exists(): return findings
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    # Pro Non-USD-Ticker: vergleiche entry_price mit prices.close vom Entry-Datum
    rows = c.execute(
        "SELECT id, ticker, entry_price, substr(entry_date, 1, 10) AS d "
        "FROM paper_portfolio WHERE entry_price IS NOT NULL"
    ).fetchall()
    mismatches = []
    for r in rows:
        ticker = r['ticker'] or ''
        if not any(ticker.endswith(s) for s in EU_SUFFIXES + ASIA_SUFFIXES):
            continue
        pr = c.execute(
            "SELECT close FROM prices WHERE ticker=? AND date=? LIMIT 1",
            (ticker, r['d'])
        ).fetchone()
        if not pr or not pr[0]: continue
        diff_pct = abs(r['entry_price'] - pr[0]) / pr[0] * 100
        if diff_pct > 5:
            mismatches.append({
                'id': r['id'], 'ticker': ticker,
                'paper_portfolio_entry': r['entry_price'],
                'prices_native': pr[0],
                'diff_pct': round(diff_pct, 1),
            })

    if mismatches:
        findings.append({
            'category': 'currency',
            'severity': 'warning',
            'issue': f'{len(mismatches)} Non-USD-Trades mit >5% Diff zwischen paper_portfolio und prices',
            'detail': 'paper_portfolio speichert EUR-konvertiert, prices nativ. '
                     'Vergleiche zwischen beiden brauchen FX-Konvertierung.',
            'samples': mismatches[:5],
            'recommendation': 'Konvention dokumentieren: paper_portfolio = EUR, prices = native.',
        })
    c.close()
    return findings


# ─────────────────────────────────────────────────────────────────────
# 3. CROSS-SOURCE AUDIT
# ─────────────────────────────────────────────────────────────────────

def audit_cross_source() -> list[dict]:
    """Cash, Position-Count, Strategy-Status aus mehreren Quellen kreuzen."""
    findings = []
    if not DB.exists(): return findings
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    # 1. Cash: paper_fund vs computed (start - sum(open_pos.cost) + sum(realized))
    try:
        cash_paper_fund = float(c.execute(
            "SELECT value FROM paper_fund WHERE key='current_cash'"
        ).fetchone()[0])
        starting = float(c.execute(
            "SELECT value FROM paper_fund WHERE key='starting_capital'"
        ).fetchone()[0])
        realized = c.execute(
            "SELECT COALESCE(SUM(pnl_eur), 0) FROM paper_portfolio "
            "WHERE pnl_eur IS NOT NULL "
            "  AND (exit_type IS NULL OR exit_type NOT LIKE 'BUG_ROLLBACK%')"
        ).fetchone()[0] or 0
        open_value = c.execute(
            "SELECT COALESCE(SUM(entry_price*shares), 0) FROM paper_portfolio "
            "WHERE status='OPEN'"
        ).fetchone()[0] or 0
        computed_cash = starting + realized - open_value
        diff = abs(cash_paper_fund - computed_cash)
        if diff > 100:
            findings.append({
                'category': 'cross_source',
                'severity': 'warning',
                'issue': f'Cash-Diskrepanz: paper_fund={cash_paper_fund:.0f} '
                         f'vs computed={computed_cash:.0f}',
                'detail': f'Starting {starting:.0f} + Realized {realized:.0f} - Open {open_value:.0f} = {computed_cash:.0f}',
                'diff_eur': round(diff, 2),
                'recommendation': 'fund_reconciliation laeuft 23:15. Bei wiederkehrender Diff: Schreiber pruefen.',
            })
    except Exception as e:
        findings.append({
            'category': 'cross_source', 'severity': 'info',
            'issue': f'Cash-Cross-Check fehlgeschlagen: {e}',
        })

    # 2. Strategy-Status: strategies.json vs trading_learnings vs quant_metrics
    try:
        sf = WS / 'data' / 'strategies.json'
        lf = WS / 'data' / 'trading_learnings.json'
        qf = WS / 'data' / 'quant_metrics.json'
        if sf.exists() and lf.exists():
            strats = json.loads(sf.read_text(encoding='utf-8'))
            learnings = (json.loads(lf.read_text(encoding='utf-8'))
                         .get('strategy_scores') or {})
            # Strategien die in learnings aber nicht in strategies.json
            orphans = set(learnings.keys()) - set(strats.keys())
            if orphans:
                findings.append({
                    'category': 'cross_source',
                    'severity': 'info',
                    'issue': f'{len(orphans)} Strategien in learnings aber nicht in strategies.json',
                    'samples': list(orphans)[:10],
                    'recommendation': 'Vermutlich alte/archived. Cleanup bei Bedarf.',
                })
    except Exception: pass

    # 3. Open Positions: paper_portfolio vs trade_lifecycle
    try:
        n_open_pp = c.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'"
        ).fetchone()[0]
        try:
            n_open_tl = c.execute(
                "SELECT COUNT(*) FROM trade_lifecycle WHERE status='OPEN'"
            ).fetchone()[0]
            if n_open_pp != n_open_tl:
                findings.append({
                    'category': 'cross_source',
                    'severity': 'warning',
                    'issue': f'Open-Position-Count Diff: paper_portfolio={n_open_pp} '
                             f'vs trade_lifecycle={n_open_tl}',
                    'recommendation': 'trade_lifecycle als sekundaere Tabelle pruefen.',
                })
        except sqlite3.OperationalError:
            pass  # trade_lifecycle existiert nicht
    except Exception: pass

    c.close()
    return findings


# ─────────────────────────────────────────────────────────────────────
# 4. HEALTH-INDIKATOR AUDIT
# ─────────────────────────────────────────────────────────────────────

def audit_health_signals() -> list[dict]:
    """Sucht Code der File-mtime als Job-Health-Indikator nutzt.

    Pattern: stat().st_mtime + Vergleich mit "max_age" Schwelle ohne
    parallelen Check der Job-Existenz.
    """
    findings = []
    suspect_files = []
    scripts_dir = WS / 'scripts'
    pattern = re.compile(r'st_mtime|stat\(\)\.st_mtime|getmtime')
    for py in scripts_dir.rglob('*.py'):
        if '_archive' in str(py): continue
        try:
            content = py.read_text(encoding='utf-8', errors='replace')
            if pattern.search(content):
                # Prüfe ob auch scheduler.log oder ähnliche Job-Quelle gelesen
                has_job_check = bool(re.search(
                    r'scheduler\.log|systemd|journalctl|process_running',
                    content
                ))
                rel = py.relative_to(WS).as_posix()
                if not has_job_check:
                    suspect_files.append(rel)
        except Exception: continue

    if suspect_files:
        findings.append({
            'category': 'health_signal',
            'severity': 'info',
            'issue': f'{len(suspect_files)} Skripte nutzen st_mtime ohne paralleles Job-Check',
            'detail': 'Pattern wie Silence-Detector: File-mtime als Job-Health. '
                     'Bei stillen Phasen False-Positives.',
            'samples': suspect_files[:10],
            'recommendation': 'Pro Skript pruefen ob File-mtime fuer Job-Health gemeint ist. '
                             'Falls ja: kreuze mit scheduler.log.',
        })
    return findings


# ─────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────

def main() -> int:
    schema = audit_schema()
    currency = audit_currency()
    cross = audit_cross_source()
    health = audit_health_signals()

    all_findings = schema + currency + cross + health
    n_critical = sum(1 for f in all_findings if f.get('severity') == 'critical')
    n_warning = sum(1 for f in all_findings if f.get('severity') == 'warning')
    n_info = sum(1 for f in all_findings if f.get('severity') == 'info')

    # Markdown-Report
    lines = [
        f'# Source-Consistency-Audit — {datetime.now(timezone.utc).isoformat(timespec="seconds")}',
        '',
        f'**Gesamt:** {len(all_findings)} Findings — '
        f'{n_critical} critical, {n_warning} warning, {n_info} info',
        '',
    ]
    for cat_name, cat_findings in [
        ('1. Schema (DB-Spalten-Konventionen)', schema),
        ('2. Currency (Cross-Currency-Mismatch)', currency),
        ('3. Cross-Source (Quellen-Diskrepanzen)', cross),
        ('4. Health-Signal (File-mtime als Job-Health)', health),
    ]:
        lines.append(f'## {cat_name}')
        lines.append('')
        if not cat_findings:
            lines.append('✅ Keine Findings.')
            lines.append('')
            continue
        for f in cat_findings:
            sev = f.get('severity', 'info').upper()
            icon = {'CRITICAL': '🚨', 'WARNING': '⚠', 'INFO': 'ℹ'}.get(sev, '·')
            lines.append(f'### {icon} [{sev}] {f["issue"]}')
            if 'detail' in f:
                lines.append(f'> {f["detail"]}')
            if 'samples' in f:
                lines.append('Samples:')
                for s in f['samples'][:5]:
                    lines.append(f'  - `{s}`')
            if 'recommendation' in f:
                lines.append(f'**Empfehlung:** {f["recommendation"]}')
            lines.append('')

    REPORT.write_text('\n'.join(lines), encoding='utf-8')
    print(f'Report: {REPORT}')
    print(f'Total: {len(all_findings)} findings ({n_critical} crit, {n_warning} warn, {n_info} info)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
