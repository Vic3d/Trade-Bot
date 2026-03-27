#!/usr/bin/env python3
# Fix render crashes - using bytes directly to avoid escaping issues

f = open('api/dashboard.js', 'rb')
c = f.read()
f.close()

print("Start size:", len(c))

# ── 1. sResults crash fix ───────────────────────────────────────────
# senti.results is array but render calls (v||0).toFixed(2) where v=object → crash

# Step 1a: Fix declaration
c = c.replace(
    b"const sResults=senti.results||{};",
    b"const sResults=Array.isArray(senti.results)?senti.results:[];",
    1
)

# Step 1b: Replace the whole Object.entries(sResults) block
idx = c.find(b"Object.entries(sResults)")
if idx != -1:
    end = c.find(b".join('');", idx) + len(b".join('');")
    # Build replacement using single quotes for the JS strings
    repl = b"sResults.map(r=>('<div style=\"display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(30,41,59,0.3)\"><span class=\"mono\">')+esc(r.ticker||'')+('<span class=\"dim\" style=\"font-size:.75rem\"> '+( r.articles||0)+'art</span></span><span class=\"'+((r.score||0)>3?'green':(r.score||0)<-3?'red':'amber')+'\">'+((r.score||0))+'</span></div>').join('');"
    c = c[:idx] + repl + c[end:]
    print("Fix 1: sResults crash fixed")
else:
    print("WARN: Object.entries(sResults) not found")

# ── 2. dna.strategies: array → map ─────────────────────────────────
c = c.replace(
    b"const dnaS=dna.strategies||{};",
    b"const dnaS=Array.isArray(dna.strategies)?dna.strategies:[];",
    1
)
c = c.replace(
    b"Object.entries(dnaS).length?Object.entries(dnaS).map(([k,v])=>",
    b"dnaS.length?dnaS.map(v=>",
    1
)
# Fix key references: esc(k) → esc(v.id||v.strategy||'')
idx2 = c.find(b"'<div class=\"dna-card\"><strong>'+esc(k)+'</strong>")
if idx2 != -1:
    # Replace esc(k) and esc(v.name||'')
    old2 = b"'<div class=\"dna-card\"><strong>'+esc(k)+'</strong> \u2014 '+esc(v.name||'')"
    new2 = b"'<div class=\"dna-card\"><strong>'+esc(v.id||v.strategy||'')+'</strong> \u2014 '+esc(v.strategy_name||v.name||'')"
    if old2 in c:
        c = c.replace(old2, new2, 1)
        print("Fix 2: dna.strategies fixed")
    else:
        # Try finding by position
        snip = c[idx2:idx2+100]
        print("dna-card snippet:", snip)

# ── 3. dna.regime_performance: array → map ─────────────────────────
c = c.replace(
    b"const dnaR=dna.regime_performance||{};",
    b"const dnaR=Array.isArray(dna.regime_performance)?dna.regime_performance:[];",
    1
)

idx3 = c.find(b"Object.entries(dnaR).length?")
if idx3 != -1:
    end3 = c.find(b"Keine Regime-Daten</div>'", idx3)
    end3 += len(b"Keine Regime-Daten</div>'")
    repl3 = (
        b"dnaR.length?'<table><tr><th>Regime</th><th>Trades</th><th>WR</th><th>Avg P&L</th></tr>'"
        b"+dnaR.map(v=>'<tr><td><strong>'+esc(v.regime||'')+'</strong></td>"
        b"<td>'+(v.total||v.trades||0)+'</td>"
        b"<td>'+((v.win_rate||0)*100).toFixed(0)+'%</td>"
        b"<td class=\"mono \"+cls(v.avg_pnl||0)+'\">'+fmt(v.avg_pnl||0)+'</td></tr>').join('')+'</table>'"
        b":'<div class=\"dim\">Keine Regime-Daten</div>'"
    )
    c = c[:idx3] + repl3 + c[end3:]
    print("Fix 3: dna.regime_performance fixed")

# ── 4. DNA profile: use dna.stats ───────────────────────────────────
c = c.replace(
    b"const profile=dna.trader_profile||{};",
    b"const profile=dna.trader_profile||{};const dnaStats=dna.stats||{};",
    1
)
c = c.replace(
    b"{n:profile.total_trades||0,l:'Total Trades'},",
    b"{n:dnaStats.total||0,l:'Total Trades'},",
    1
)
# win_rate fix
idx4 = c.find(b"{n:((profile.win_rate||0)*100)")
if idx4 != -1:
    end4 = c.find(b"'green':'red'},", idx4) + len(b"'green':'red'},")
    old4 = c[idx4:end4]
    new4 = b"{n:((dnaStats.win_rate||0)*100).toFixed(0)+'%',l:'Win Rate',c:(dnaStats.win_rate||0)>0.45?'green':'red'},"
    c = c[:idx4] + new4 + c[end4:]
    print("Fix 4: DNA profile stats fixed")

# ── 5. Version ───────────────────────────────────────────────────────
# Already at v2.1.2 from earlier, but check
if b"TradeMind v2.1.1" in c:
    c = c.replace(b"TradeMind v2.1.1", b"TradeMind v2.1.2")
    print("Version bumped")

print()
print("(v||0).toFixed crash gone:", b"(v||0).toFixed" not in c)
print("sResults array:", b"Array.isArray(senti.results)" in c)
print("dnaS array:", b"Array.isArray(dna.strategies)" in c)
print("dnaR array:", b"Array.isArray(dna.regime_performance)" in c)
print("dnaStats:", b"const dnaStats=" in c)
print("File size:", len(c))

f = open('api/dashboard.js', 'wb')
f.write(c)
f.close()
print("Saved.")
