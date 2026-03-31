#!/usr/bin/env python3
"""Clean fix: sResults, dna arrays, version bump.
Uses single-quoted Python strings to avoid \" escaping issues."""

f = open('api/dashboard.js', 'rb')
c = f.read()
f.close()
print('Start size:', len(c))

# ── 1. Version 2.1.1 → 2.1.2 ─────────────────────────────────────────────
c = c.replace(b'TradeMind v2.1.1', b'TradeMind v2.1.2')
print('v2.1.2 set:', c.count(b'TradeMind v2.1.2'))

# ── 2. sResults: declaration fix ─────────────────────────────────────────
c = c.replace(
    b'const sResults=senti.results||{};',
    b'const sResults=Array.isArray(senti.results)?senti.results:[];',
    1
)
print('sResults decl:', b'Array.isArray(senti.results)' in c)

# ── 3. sResults: fix the map — Object.entries → .map(r=>...) ─────────────
# Find exact block: Object.entries(sResults).map(([k,v])=>...(v||0).toFixed(2)...
idx = c.find(b'Object.entries(sResults).map')
print('Object.entries(sResults) at:', idx)
if idx != -1:
    end = c.find(b").join('');", idx) + len(b").join('');")
    old_block = c[idx:end]
    print('Old block len:', len(old_block))
    print('Old block start:', repr(old_block[:60]))
    # New block: array-safe, uses r.ticker and r.score
    # Use single-quoted Python string — no escaping issues
    new_block = (
        b"sResults.map(r=>'<div style=\\"display:flex;justify-content:space-between;"
        b"padding:4px 0;border-bottom:1px solid rgba(30,41,59,0.3)\\">"
        b"<span class=\\"mono\\">'+esc(r.ticker||'')+'<span class=\\"dim\\" style=\\"font-size:.7rem\\"> "
        b"('+( r.articles||0)+')</span></span>"
        b"<span class=\\"'+((r.score||0)>3?'green':(r.score||0)<-3?'red':'amber')+'\\">'+((r.score||0))+"
        b"'</span></div>').join('');"
    )
    c = c[:idx] + new_block + c[end:]
    print('sResults map replaced, new len:', len(c))
    # Verify crash is gone
    print('(v||0).toFixed crash gone:', b'(v||0).toFixed' not in c)
    node_check = __import__('subprocess').run(['node', '--check', '/dev/stdin'],
        input=c, capture_output=True)
    print('Syntax after sResults fix:', 'OK' if node_check.returncode == 0 else node_check.stderr.decode()[:200])

# ── 4. dna.strategies: array-safe ────────────────────────────────────────
c = c.replace(
    b'const dnaS=dna.strategies||{};',
    b'const dnaS=Array.isArray(dna.strategies)?dna.strategies:[];',
    1
)
c = c.replace(
    b'Object.entries(dnaS).length?Object.entries(dnaS).map(([k,v])=>',
    b'dnaS.length?dnaS.map(v=>',
    1
)
# Fix key ref: esc(k) → esc(v.id||v.strategy||'')
c = c.replace(
    b"'<div class=\\"dna-card\\"><strong>'+esc(k)+'</strong>",
    b"'<div class=\\"dna-card\\"><strong>'+esc(v.id||v.strategy||'')+'</strong>",
    1
)
print('dnaS fixed:', b'Array.isArray(dna.strategies)' in c)

# ── 5. dna.regime_performance: array-safe ────────────────────────────────
c = c.replace(
    b'const dnaR=dna.regime_performance||{};',
    b'const dnaR=Array.isArray(dna.regime_performance)?dna.regime_performance:[];',
    1
)
# Fix Object.entries(dnaR) block
idx3 = c.find(b'Object.entries(dnaR).length?')
if idx3 != -1:
    end3 = c.find(b"Keine Regime-Daten</div>'", idx3)
    end3 += len(b"Keine Regime-Daten</div>'")
    new3 = (
        b"dnaR.length?'<table><tr><th>Regime</th><th>Trades</th><th>WR</th><th>Avg P&L</th></tr>'"
        b"+dnaR.map(v=>'<tr><td><strong>'+esc(v.regime||'')+'</strong></td>"
        b"<td>'+(v.total||v.trades||0)+'</td>"
        b"<td>'+((v.win_rate||0)*100).toFixed(0)+'%</td>"
        b"<td class=\\"mono '+cls(v.avg_pnl||0)+'\\">'+"
        b"fmt(v.avg_pnl||0)+'</td></tr>').join('')+'</table>'"
        b":'<div class=\\"dim\\">Keine Regime-Daten</div>'"
    )
    c = c[:idx3] + new3 + c[end3:]
    print('dnaR fixed:', b'Array.isArray(dna.regime_performance)' in c)

# ── 6. DNA profile: use dna.stats ────────────────────────────────────────
c = c.replace(
    b'const profile=dna.trader_profile||{};',
    b'const profile=dna.trader_profile||{};const dnaStats=dna.stats||{};',
    1
)
c = c.replace(
    b'{n:profile.total_trades||0,l:\'Total Trades\'},',
    b'{n:dnaStats.total||0,l:\'Total Trades\'},',
    1
)
idx4 = c.find(b'{n:((profile.win_rate||0)*100)')
if idx4 != -1:
    end4 = c.find(b"'green':'red'},", idx4) + len(b"'green':'red'},")
    new4 = b"{n:((dnaStats.win_rate||0)*100).toFixed(0)+'%',l:'Win Rate',c:(dnaStats.win_rate||0)>0.45?'green':'red'},"
    c = c[:idx4] + new4 + c[end4:]
    print('DNA profile stats fixed')

# ── Final check ──────────────────────────────────────────────────────────
import subprocess
result = subprocess.run(['node', '--check', 'api/dashboard.js'], capture_output=True, cwd='/data/.openclaw/workspace')
if result.returncode == 0:
    print('\nSYNTAX OK ✅')
    f = open('api/dashboard.js', 'wb')
    f.write(c)
    f.close()
    print('Saved. Size:', len(c))
else:
    print('\nSYNTAX ERROR ❌')
    print(result.stderr.decode()[:300])
    print('NOT saved - keeping original')
