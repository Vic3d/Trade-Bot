#!/usr/bin/env python3
"""Patch dashboard.js cleanly."""
f = open('api/dashboard.js', 'r')
c = f.read()
f.close()

changes = []

# 1. Modal CSS before </style>
css = (
    '.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:1000;display:none;align-items:center;justify-content:center}'
    '.modal-bg.open{display:flex}'
    '.modal{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:24px;min-width:320px;max-width:500px;width:90vw}'
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
)
needle1 = '\\n</style>\\n</head>'
if needle1 in c:
    c = c.replace(needle1, css + needle1, 1)
    changes.append('CSS')

# 2. Modal HTML + JS before load()
# Note: inside the JS string literal, \n appears as \\n
# The modal/JS will be injected OUTSIDE the HTML string, before module.exports
# Actually we need to inject inside the HTML string before </body>
modal_html = (
    '<div class=\\"modal-bg\\" id=\\"editModal\\">'
    '<div class=\\"modal\\">'
    '<h3>Edit: <span id=\\"eticker\\"></span></h3>'
    '<label>Stop (EUR)</label>'
    '<input type=\\"number\\" id=\\"estop\\" step=\\"0.01\\">'
    '<label>Ziel (EUR)</label>'
    '<input type=\\"number\\" id=\\"etarget\\" step=\\"0.01\\">'
    '<div class=\\"btns\\">'
    '<button class=\\"btn-save\\" onclick=\\"savePos()\\">Speichern</button>'
    '<button class=\\"btn-cancel\\" onclick=\\"closeEM()\\">Abbrechen</button>'
    '</div>'
    '<div id=\\"emsg\\" style=\\"font-size:.8rem;margin-top:8px\\"></div>'
    '</div></div>'
)
js_code = (
    'var _et="";'
    'function openEdit(t,s,tg){'
    '_et=t;'
    '$("eticker").textContent=t;'
    '$("estop").value=s||"";'
    '$("etarget").value=tg||"";'
    '$("emsg").textContent="";'
    '$("editModal").classList.add("open");'
    '}'
    'function closeEM(){$("editModal").classList.remove("open");}'
    '$("editModal").addEventListener("click",function(e){if(e.target===$("editModal"))closeEM();});'
    'async function savePos(){'
    'var s=$("estop").value,t=$("etarget").value,m=$("emsg");'
    'm.textContent="Speichere...";m.style.color="var(--dim)";'
    'try{'
    'var r=await fetch("/api/config",{method:"POST",'
    'headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({ticker:_et,'
    'stop_eur:s?parseFloat(s):undefined,'
    'target_eur:t?parseFloat(t):undefined})});'
    'var d=await r.json();'
    'if(r.ok){m.textContent="OK: "+(d.changes||[]).join(", ");'
    'm.style.color="var(--green)";setTimeout(closeEM,2000);}'
    'else{m.textContent="Fehler: "+d.error;m.style.color="var(--red)";}'
    '}catch(e){m.textContent="Fehler: "+e.message;m.style.color="var(--red)";}'
    '}'
    'function togS(el){el.closest(".strat-card").classList.toggle("open");}'
)

needle2 = 'load();\\n</script>\\n</body>\\n</html>'
if needle2 in c:
    inject = modal_html + '\\n<script>\\n' + js_code + '\\n</script>\\n'
    c = c.replace(needle2, inject + needle2, 1)
    changes.append('Modal+JS')

# 3. Position row: add edit button
# Exact: '+esc(p.notes)+'</td></tr>').join
needle3 = "'+esc(p.notes)+'</td></tr>').join"
new3 = "'+esc(p.notes)+'</td><td><button class=\\"edit-btn\\" onclick=\\"openEdit(\''+esc(p.ticker||'')+'\',' +(p.stop||0)+','  +((p.targets&&p.targets[0])||0)+')\\">&#9999;</button></td></tr>').join"
if needle3 in c:
    c = c.replace(needle3, new3, 1)
    changes.append('Edit btn')
else:
    print("WARN row end not found")
    idx = c.find('max-width:200px')
    print("  pos:", repr(c[idx-5:idx+140]))

# 4. Position table header
needle4 = '<th>Notiz</th></tr>'
if needle4 in c:
    c = c.replace(needle4, '<th>Notiz</th><th style=\\"width:40px\\"></th></tr>', 1)
    changes.append('Header')

# 5. Strategy card: add onclick
needle5 = "border-left-color:'+(s.color||'var(--cyan)')+'\\\\"><h4>'"
# Check what's actually there
idx5 = c.find("border-left-color:'+(s.color||'var(--cyan)")
if idx5 != -1:
    print("strat card at:", idx5, repr(c[idx5:idx5+80]))
    # Find the exact ending of the style attr
    chunk = c[idx5:idx5+120]
    print("chunk:", repr(chunk))

# 6. Strategy detail
needle6 = "+'</div></div>';\n  }).join('');"
new6 = (
    "+'<div class=\\"strat-detail\\">'"
    "+(full.thesis?'<p><strong style=\\"color:var(--cyan)\\">These:</strong> '+esc(full.thesis)+'</p>':'')"
    "+(full.entry_trigger?'<p><strong style=\\"color:var(--green)\\">Entry:</strong> '+esc(full.entry_trigger)+'</p>':'')"
    "+(full.kill_trigger?'<p><strong style=\\"color:var(--red)\\">Kill:</strong> '+esc(full.kill_trigger)+'</p>':'')"
    "+'</div></div></div>';\n  }).join('');"
)
if needle6 in c:
    c = c.replace(needle6, new6, 1)
    changes.append('Strat detail')

print()
print("Changes:", changes)
print("editModal present:", 'editModal' in c)
print("openEdit/openEdit:", 'openEdit' in c or '_et=' in c)
print("strat-detail:", 'strat-detail' in c)
print("load() count:", c.count('load()'))
print("File size:", len(c))

f = open('api/dashboard.js', 'w')
f.write(c)
f.close()
print("Saved.")
