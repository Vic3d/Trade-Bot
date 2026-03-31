#!/usr/bin/env python3
# Use single quotes throughout to avoid \" confusion

f = open('api/dashboard.js', 'r')
c = f.read()
f.close()
print('Start size:', len(c))
chg = []

Q = '\\"'  # \" as it appears in the file

# 1. Modal CSS
css = (
    '.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:1000;display:none;align-items:center;justify-content:center}'
    '.modal-bg.open{display:flex}'
    '.modal{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:24px;max-width:500px;width:90vw}'
    '.modal h3{font-size:1rem;margin-bottom:14px;color:var(--cyan)}'
    '.modal label{font-size:.75rem;color:var(--dim);display:block;margin-top:10px;margin-bottom:3px}'
    '.modal input{width:100%;background:#0a0e17;border:1px solid var(--border);color:var(--text);border-radius:6px;padding:8px 10px;font-size:.88rem}'
    '.modal .btns{display:flex;gap:8px;margin-top:14px}'
    '.btn-save{background:var(--cyan);color:#000;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-weight:600}'
    '.btn-cancel{background:var(--border);color:var(--text);border:none;padding:8px 18px;border-radius:6px;cursor:pointer}'
    '.edit-btn{background:none;border:1px solid var(--border);color:var(--dim);padding:3px 8px;border-radius:5px;cursor:pointer;font-size:.7rem}'
    '.edit-btn:hover{border-color:var(--cyan);color:var(--cyan)}'
    '.strat-detail{display:none;margin-top:10px;padding-top:10px;border-top:1px solid var(--border);font-size:.8rem;line-height:1.6}'
    '.strat-card.open .strat-detail{display:block}'
    '.strat-card{cursor:pointer}'
)
n = '\\n</style>\\n</head>'
if n in c:
    c = c.replace(n, css + n, 1); chg.append('css')

# 2. Modal HTML + JS before load()
modal = (
    '<div class=' + Q + 'modal-bg' + Q + ' id=' + Q + 'editModal' + Q + '>'
    '<div class=' + Q + 'modal' + Q + '>'
    '<h3>&#9999; <span id=' + Q + 'eticker' + Q + '></span></h3>'
    '<label>Stop (EUR)</label>'
    '<input type=' + Q + 'number' + Q + ' id=' + Q + 'estop' + Q + ' step=' + Q + '0.01' + Q + '>'
    '<label>Ziel (EUR)</label>'
    '<input type=' + Q + 'number' + Q + ' id=' + Q + 'etarget' + Q + ' step=' + Q + '0.01' + Q + '>'
    '<div class=' + Q + 'btns' + Q + '>'
    '<button class=' + Q + 'btn-save' + Q + ' onclick=' + Q + 'savePos()' + Q + '>Speichern</button>'
    '<button class=' + Q + 'btn-cancel' + Q + ' onclick=' + Q + 'closeEM()' + Q + '>Abbrechen</button>'
    '</div>'
    '<div id=' + Q + 'emsg' + Q + ' style=' + Q + 'font-size:.8rem;margin-top:8px' + Q + '></div>'
    '</div></div>'
)
js = (
    "var _et='';"
    "function openEdit(t,s,tg){"
    "_et=t;"
    "$('eticker').textContent=t;"
    "$('estop').value=s||'';"
    "$('etarget').value=tg||'';"
    "$('emsg').textContent='';"
    "$('editModal').classList.add('open');"
    "}"
    "function closeEM(){$('editModal').classList.remove('open');}"
    "$('editModal').addEventListener('click',function(e){if(e.target===$('editModal'))closeEM();});"
    "async function savePos(){"
    "var s=$('estop').value,t=$('etarget').value,m=$('emsg');"
    "m.textContent='Speichere...';m.style.color='var(--dim)';"
    "try{"
    "var r=await fetch('/api/config',{method:'POST',"
    "headers:{'Content-Type':'application/json'},"
    "body:JSON.stringify({ticker:_et,"
    "stop_eur:s?parseFloat(s):undefined,"
    "target_eur:t?parseFloat(t):undefined})});"
    "var d=await r.json();"
    "if(r.ok){m.textContent='OK: '+(d.changes||[]).join(', ');"
    "m.style.color='var(--green)';setTimeout(closeEM,2000);}"
    "else{m.textContent='Fehler: '+d.error;m.style.color='var(--red)';}"
    "}catch(e){m.textContent='Fehler: '+e.message;m.style.color='var(--red)';}"
    "}"
    "function togS(el){el.closest('.strat-card').classList.toggle('open');}"
    "document.addEventListener('click',function(e){"
    "var b=e.target.closest('.edit-btn');"
    "if(b)openEdit(b.dataset.ticker,b.dataset.stop,b.dataset.target);"
    "});"
)
n2 = 'load();\\n</script>\\n</body>\\n</html>'
if n2 in c:
    ins = modal + '\\n<script>\\n' + js + '\\n</script>\\n'
    c = c.replace(n2, ins + n2, 1); chg.append('modal+js')
else:
    print('WARN modal needle missing')

# 3. Position row: edit button with data attributes
# File has: '+esc(p.notes)+'</td></tr>').join
n3 = "'+esc(p.notes)+'</td></tr>').join"
n3new = (
    "'+esc(p.notes)+'</td>"
    "<td>"
    "<button class=" + Q + "edit-btn" + Q
    + " data-ticker=" + Q + "'+esc(p.ticker||'')+'\\\" data-stop=" + Q + "'+(p.stop||0)+'\\\" data-target=" + Q + "'+((p.targets&&p.targets[0])||0)+'\\\""
    + ">&#9999;</button>"
    "</td></tr>').join"
)
# Simpler approach for the button
btn = (
    "'+esc(p.notes)+"
    "'</td>"
    "<td><button class="
    + Q + "edit-btn" + Q
    + " data-ticker="
    + Q + "'+esc(p.ticker||'')+'\\\" data-stop="
    + Q + "'+(p.stop||0)+'\\\" data-target="
    + Q + "'+((p.targets&&p.targets[0])||0)+'\\\">&#9999;</button></td></tr>').join"
)
if n3 in c:
    c = c.replace(n3, btn, 1); chg.append('edit-btn')
else:
    print('WARN row needle missing')
    idx = c.find('max-width:200px')
    print('  sample:', repr(c[idx:idx+120]))

# 4. Header column
n4 = '<th>Notiz</th></tr>'
if n4 in c:
    c = c.replace(n4, '<th>Notiz</th><th></th></tr>', 1); chg.append('hdr')

# 5. Strategy card onclick
n5 = "'<div class=" + Q + "strat-card" + Q + " style=" + Q + "border-left-color:'+(s.color||'var(--cyan)')+'\\\\><h4>'"
# Check what's actually in the file
idx5 = c.find("border-left-color:'+(s.color||'var(--cyan)")
if idx5 != -1:
    chunk = c[idx5-20:idx5+100]
    print('strat chunk:', repr(chunk))
    # Find exact text
    old_sc = c[idx5-20:idx5+80]
    # Build new with onclick
    end_of_style = chunk.find('><h4>')
    if end_of_style != -1:
        old_needle = chunk[:end_of_style+5]
        new_needle = old_needle.replace('><h4>', '; cursor:pointer" onclick=\\"togS(this)\\"><h4>', 1)
        # Actually look for \\"><h4>
        alt1 = "+'\\\\><h4>'"
        alt2 = "'; cursor:pointer\\" + Q + " onclick=" + Q + "togS(this)" + Q + "><h4>'"
        if alt1 in c:
            c = c.replace(alt1, alt2, 1); chg.append('strat-onclick')
        else:
            # try another pattern
            alt3 = "+'\\\"><h4>'"
            if alt3 in c:
                # Find context
                i3 = c.find(alt3)
                print('alt3 found at:', i3, repr(c[i3-30:i3+50]))

# 6. Strategy detail
n6 = "+'</div></div>';\n  }).join('');"
n6new = (
    "+'<div class=" + Q + "strat-detail" + Q + ">'"
    "+(full.thesis?'<p><strong style=" + Q + "color:var(--cyan)" + Q + ">These:</strong> '+esc(full.thesis)+'</p>':'')"
    "+(full.entry_trigger?'<p><strong style=" + Q + "color:var(--green)" + Q + ">Entry:</strong> '+esc(full.entry_trigger)+'</p>':'')"
    "+(full.kill_trigger?'<p><strong style=" + Q + "color:var(--red)" + Q + ">Kill:</strong> '+esc(full.kill_trigger)+'</p>':'')"
    "+'</div></div></div>';\n  }).join('');"
)
if n6 in c:
    c = c.replace(n6, n6new, 1); chg.append('strat-detail')
else:
    print('WARN strat detail needle missing')
    idx = c.find("}).join('')")
    print('  found:', repr(c[max(0,idx-80):idx+20]))

print()
print('Changes:', chg)
print('editModal:', 'editModal' in c)
print('_et=:', "_et='" in c)
print('strat-detail:', 'strat-detail' in c)
print('load():', c.count('load()'), 'times')
print('File size:', len(c))

f = open('api/dashboard.js', 'w')
f.write(c)
f.close()
print('Saved.')
