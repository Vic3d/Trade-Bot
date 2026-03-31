#!/usr/bin/env python3
"""Fix render crashes: sResults, dna.strategies, dna.regime_performance, dna.profile"""

f = open('api/dashboard.js', 'rb')
c = f.read()
f.close()
changes = []

# ─── 1. MAIN CRASH: sResults (sentiment results is array, render expects dict) ───
# File has: const sResults=senti.results||{};
# Then: Object.entries(sResults).map(([k,v])=>...(v||0).toFixed(2)...)
# v is an object {ticker,score,...} → .toFixed() on object = TypeError

old1 = b"const sResults=senti.results||{};"
new1 = b"const sResults=Array.isArray(senti.results)?senti.results:[];"
if old1 in c:
    c = c.replace(old1, new1, 1)
    changes.append('sResults-declaration')

# Fix the map: Object.entries(sResults).map(([k,v])=>'...'+esc(k)+'...'+(v||0).toFixed(2)+'...')
# to: sResults.map(r=>'...'+esc(r.ticker||'')+'...'+((r.score||0))+'...')
old1b = (b"Object.entries(sResults).map(([k,v])=>"
         b"'<div style=\\"display:flex;justify-content:space-between;"
         b"padding:4px 0;border-bottom:1px solid rgba(30,41,59,0.3)\\">"
         b"<span class=\\"mono\\">'+esc(k)+'</span>"
         b"<span class=\\\"'+(v>0.3?'green':v<-0.3?'red':'amber')+'\\\">"
         b"'+(v||0).toFixed(2)+'</span></div>').join('')")
new1b = (b"sResults.map(r=>"
         b"'<div style=\\"display:flex;justify-content:space-between;"
         b"padding:4px 0;border-bottom:1px solid rgba(30,41,59,0.3)\\">"
         b"<span class=\\"mono\\">'+esc(r.ticker||'')+'</span>"
         b"<span class=\\\"'+((r.score||0)>3?'green':(r.score||0)<-3?'red':'amber')+'\\\">"
         b"'+((r.score||0))+'</span></div>').join('')")
if old1b in c:
    c = c.replace(old1b, new1b, 1)
    changes.append('sResults-map-fix')
else:
    print("WARN: sResults map pattern not found, trying simpler...")
    # Find and replace just the problematic .toFixed part
    idx = c.find(b"Object.entries(sResults)")
    if idx != -1:
        end = c.find(b").join('')", idx)
        if end != -1:
            old_block = c[idx:end+len(b").join('')")]
            new_block = (
                b"sResults.map(r=>"
                b"'<div style=\\"display:flex;justify-content:space-between;"
                b"padding:4px 0;border-bottom:1px solid rgba(30,41,59,0.3)\\">"
                b"<span class=\\"mono\\">'+esc(r.ticker||'')+'</span>"
                b"<span class=\\\"'+((r.score||0)>3?'green':(r.score||0)<-3?'red':'amber')+'\\\">"
                b"Score: '+((r.score||0))+'</span></div>').join('')"
            )
            c = c[:idx] + new_block + c[idx+len(old_block):]
            changes.append('sResults-block-replace')
            print("  Block replaced!")

# ─── 2. DNA strategies: array → .map() ───────────────────────────────
old2 = b"const dnaS=dna.strategies||{};"
new2 = b"const dnaS=Array.isArray(dna.strategies)?dna.strategies:Object.values(dna.strategies||{});"
if old2 in c:
    c = c.replace(old2, new2, 1)
    changes.append('dnaS-array')

old2b = b"Object.entries(dnaS).length?Object.entries(dnaS).map(([k,v])=>"
new2b = b"dnaS.length?dnaS.map(v=>"
if old2b in c:
    c = c.replace(old2b, new2b, 1)
    changes.append('dnaS-map')

# Fix: esc(k) -> esc(v.id||v.strategy||''), esc(v.name||'') -> esc(v.strategy_name||v.name||'')
old2c = b"'<div class=\\"dna-card\\"><strong>'+esc(k)+'</strong> \\u2014 '+esc(v.name||'')"
new2c = b"'<div class=\\"dna-card\\"><strong>'+esc(v.id||v.strategy||'')+'</strong> \\u2014 '+esc(v.strategy_name||v.name||'')"
if old2c in c:
    c = c.replace(old2c, new2c, 1)
    changes.append('dnaS-keys')

# ─── 3. DNA regime_performance: array → .map() ───────────────────────
old3 = b"const dnaR=dna.regime_performance||{};"
new3 = b"const dnaR=Array.isArray(dna.regime_performance)?dna.regime_performance:Object.values(dna.regime_performance||{});"
if old3 in c:
    c = c.replace(old3, new3, 1)
    changes.append('dnaR-array')

old3b = b"Object.entries(dnaR).length?'<table><tr><th>Regime</th><th>Trades</th><th>WR</th><th>Profit Factor</th></tr>'+Object.entries(dnaR).map(([k,v])=>'<tr><td><strong>'+esc(k)+'</strong></td><td>'+((v.trades||0))+'</td><td>'+((v.win_rate||0)*100).toFixed(0)+'%</td><td>'+(v.profit_factor||0).toFixed(2)+'</td></tr>').join('')+'</table>'"
new3b = b"dnaR.length?'<table><tr><th>Regime</th><th>Trades</th><th>WR</th><th>Avg P&L</th></tr>'+dnaR.map(v=>'<tr><td><strong>'+esc(v.regime||'')+'</strong></td><td>'+((v.total||v.trades||0))+'</td><td>'+((v.win_rate||0)*100).toFixed(0)+'%</td><td class=\"mono '+cls(v.avg_pnl||0)+'\">'+fmt(v.avg_pnl||0)+'</td></tr>').join('')+'</table>'"
if old3b in c:
    c = c.replace(old3b, new3b, 1)
    changes.append('dnaR-map+fields')
else:
    print("WARN: dnaR map pattern not found")
    idx3 = c.find(b"Object.entries(dnaR)")
    if idx3 != -1:
        print("  dnaR context:", repr(c[idx3:idx3+200]))

# ─── 4. DNA profile: use dna.stats for totals ────────────────────────
old4 = b"{n:profile.total_trades||0,l:'Total Trades'},"
new4 = b"{n:dnaStats.total||0,l:'Total Trades'},"
old4b = b"const profile=dna.trader_profile||{};"
new4b = b"const profile=dna.trader_profile||{};const dnaStats=dna.stats||{};"
if old4b in c:
    c = c.replace(old4b, new4b, 1)
    changes.append('dna-stats-def')
if old4 in c:
    c = c.replace(old4, new4, 1)
    changes.append('dna-total_trades')

old4c = b"{n:((profile.win_rate||0)*100).toFixed(0)+'%',l:'Win Rate',c:(profile.win_rate||0)>0.45?'green':'red'},"
new4c = b"{n:((dnaStats.win_rate||0)*100).toFixed(0)+'%',l:'Win Rate',c:(dnaStats.win_rate||0)>0.45?'green':'red'},"
if old4c in c:
    c = c.replace(old4c, new4c, 1)
    changes.append('dna-win_rate')

# ─── 5. Risk exposure: by_sector missing → show only what we have ────
old5 = b"$('risk-stress').innerHTML="
idx5 = c.find(old5)
if idx5 != -1:
    # Find the full stress render
    end5 = c.find(b"\\n\\n  // ", idx5)
    block5 = c[idx5:end5]
    # Replace empty array guard
    old_stress = b"stress.length?stress.map("
    new_stress = b"(Array.isArray(stress)&&stress.length)?stress.map("
    if old_stress in block5:
        block5 = block5.replace(old_stress, new_stress, 1)
        c = c[:idx5] + block5 + c[idx5+len(c[idx5:end5]):]
        changes.append('risk-stress-guard')

print()
print("Changes:", changes)
print("sResults array fix:", b"Array.isArray(senti.results)" in c)
print("(v||0).toFixed crash gone:", b"(v||0).toFixed(2)" not in c)
print("dnaS array:", b"Array.isArray(dna.strategies)" in c)
print("dnaR array:", b"Array.isArray(dna.regime_performance)" in c)
print("File size:", len(c))

f = open('api/dashboard.js', 'wb')
f.write(c)
f.close()
print("Saved.")
