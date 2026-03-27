#!/usr/bin/env python3
"""Patch dashboard.js - clean approach using bytes for safe replacement."""
import re

f = open('api/dashboard.js', 'r')
c = f.read()
f.close()
print(f"File size: {len(c)} chars")

changes = []

# ============================================================
# 1. Modal CSS — insert before \n</style>\n</head>
# In the JS file, the HTML string has literal \n as \\n
# ============================================================
css = (
    ".modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.7);"
    "z-index:1000;display:none;align-items:center;justify-content:center}"
    ".modal-bg.open{display:flex}"
    ".modal{background:var(--card);border:1px solid var(--border);"
    "border-radius:14px;padding:24px;min-width:320px;max-width:500px;width:90vw}"
    ".modal h3{font-size:1rem;margin-bottom:14px;color:var(--cyan)}"
    ".modal label{font-size:.75rem;color:var(--dim);display:block;"
    "margin-top:10px;margin-bottom:3px}"
    ".modal input{width:100%;background:#0a0e17;border:1px solid var(--border);"
    "color:var(--text);border-radius:6px;padding:8px 10px;font-size:.88rem}"
    ".modal .btns{display:flex;gap:8px;margin-top:14px}"
    ".btn-save{background:var(--cyan);color:#000;border:none;"
    "padding:8px 18px;border-radius:6px;cursor:pointer;font-weight:600}"
    ".btn-cancel{background:var(--border);color:var(--text);border:none;"
    "padding:8px 18px;border-radius:6px;cursor:pointer}"
    ".edit-btn{background:none;border:1px solid var(--border);"
    "color:var(--dim);padding:3px 8px;border-radius:5px;cursor:pointer;font-size:.7rem}"
    ".edit-btn:hover{border-color:var(--cyan);color:var(--cyan)}"
    ".strat-detail{display:none;margin-top:10px;padding-top:10px;"
    "border-top:1px solid var(--border);font-size:.8rem;line-height:1.6}"
    ".strat-card.open .strat-detail{display:block}"
    ".strat-card{cursor:pointer}"
)

n1 = '\\n</style>\\n</head>'
if n1 in c:
    c = c.replace(n1, css + n1, 1)
    changes.append('CSS')
else:
    print("WARN: style needle not found")

# ============================================================
# 2. Modal HTML + Edit JS + togS — before load()
# ============================================================
# The modal HTML will be embedded in the HTML string
# JS functions will be in a new <script> block

modal = (
    '<div class=\\"modal-bg\\" id=\\"editModal\\">'
    '<div class=\\"modal\\">'
    '<h3>&#9999; <span id=\\"eticker\\"></span></h3>'
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

# JS: use simple variable names, no complex quoting
# The JS is stored in a JS string, so " must be \" (\\" in Python)
# Single quotes don't need escaping inside the HTML string (the outer string uses \" for delimiting)
js = (
    'var _et="";'
    'function openEdit(t,s,tg){'
    '_et=t;'
    '$(\'eticker\').textContent=t;'
    '$(\'estop\').value=s||"";'
    '$(\'etarget\').value=tg||"";'
    '$(\'emsg\').textContent="";'
    '$(\'editModal\').classList.add(\'open\');'
    '}'
    'function closeEM(){$(\'editModal\').classList.remove(\'open\');}'
    '$(\'editModal\').addEventListener(\'click\',function(e){'
    'if(e.target===$(\'editModal\'))closeEM();});'
    'async function savePos(){'
    'var s=$(\'estop\').value,t=$(\'etarget\').value,m=$(\'emsg\');'
    'm.textContent=\'Speichere...\';m.style.color=\'var(--dim)\';'
    'try{'
    'var r=await fetch(\'/api/config\',{method:\'POST\','
    'headers:{\'Content-Type\':\'application/json\'},'
    'body:JSON.stringify({ticker:_et,'
    'stop_eur:s?parseFloat(s):undefined,'
    'target_eur:t?parseFloat(t):undefined})});'
    'var d=await r.json();'
    'if(r.ok){m.textContent=\'OK: \'+(d.changes||[]).join(\', \');'
    'm.style.color=\'var(--green)\';setTimeout(closeEM,2000);}'
    'else{m.textContent=\'Fehler: \'+d.error;m.style.color=\'var(--red)\';}'
    '}catch(e){m.textContent=\'Fehler: \'+e.message;m.style.color=\'var(--red)\';}'
    '}'
    'function togS(el){el.closest(\'.strat-card\').classList.toggle(\'open\');}'
    'document.addEventListener(\'click\',function(e){'
    'var b=e.target.closest(\'.edit-btn\');'
    'if(b)openEdit(b.dataset.ticker,b.dataset.stop,b.dataset.target);'
    '});'
)

n2 = 'load();\\n</script>\\n</body>\\n</html>'
if n2 in c:
    inject = modal + '\\n<script>\\n' + js + '\\n</script>\\n'
    c = c.replace(n2, inject + n2, 1)
    changes.append('Modal+JS')
else:
    print("WARN: load() needle not found")
    print("Last 100:", repr(c[-150:]))

# ============================================================
# 3. Position row — edit button using data attributes
# Actual string in file: '+esc(p.notes)+'</td></tr>').join
# ============================================================
n3 = "'+esc(p.notes)+'</td></tr>').join"
# New: add edit button td with data attributes (no onclick attr)
n3_new = (
    "'+esc(p.notes)+"
    "'</td>"
    "<td>"
    "<button class=\\"edit-btn\\" "
    "data-ticker=\\"'+esc(p.ticker||'')+'\\""
    " data-stop=\\"'+(p.stop||0)+'\\""
    " data-target=\\"'+((p.targets&&p.targets[0])||0)+'\\">"
    "&#9999;</button>"
    "</td>"
    "</tr>').join"
)
if n3 in c:
    c = c.replace(n3, n3_new, 1)
    changes.append('Edit btn (data-attr)')
else:
    print("WARN: row needle not found")
    idx = c.find('max-width:200px')
    print("  Sample:", repr(c[max(0,idx-5):idx+120]))

# 4. Position table header: add column
n4 = '<th>Notiz</th></tr>'
if n4 in c:
    c = c.replace(n4, '<th>Notiz</th><th style=\\"width:36px\\"></th></tr>', 1)
    changes.append('Header col')

# ============================================================
# 5. Strategy card — add onclick + detail section
# Actual: '<div class=\"strat-card\" style=\"border-left-color:'+(s.color||'var(--cyan)')+'"><h4>'
# ============================================================
n5 = "'<div class=\\"strat-card\\" style=\\"border-left-color:'+(s.color||'var(--cyan)')+'\\"><h4>'"
n5_new = "'<div class=\\"strat-card\\" style=\\"border-left-color:'+(s.color||'var(--cyan)')+'; cursor:pointer\\" onclick=\\"togS(this)\\"><h4>'"
if n5 in c:
    c = c.replace(n5, n5_new, 1)
    changes.append('Strat onclick')
else:
    print("WARN: strat card needle not found")
    idx = c.find('strat-card')
    while idx != -1:
        ctx = c[idx:idx+60]
        if 'color' in ctx:
            print("  Found:", repr(ctx))
        idx = c.find('strat-card', idx+1)

# ============================================================
# 6. Strategy detail section — inject before closing '</div></div>'
# ============================================================
n6 = "+'</div></div>';\n  }).join('');"
n6_new = (
    "+'<div class=\\"strat-detail\\">'"
    "+(full.thesis?'<p><strong style=\\"color:var(--cyan)\\">These:</strong> '"
    "+esc(full.thesis)+'</p>':'')"
    "+(full.entry_trigger?'<p><strong style=\\"color:var(--green)\\">Entry:</strong> '"
    "+esc(full.entry_trigger)+'</p>':'')"
    "+(full.kill_trigger?'<p><strong style=\\"color:var(--red)\\">Kill:</strong> '"
    "+esc(full.kill_trigger)+'</p>':'')"
    "+'</div></div></div>';\n  }).join('');"
)
if n6 in c:
    c = c.replace(n6, n6_new, 1)
    changes.append('Strat detail')
else:
    print("WARN: strat detail needle not found")
    idx = c.find("}).join('')")
    print("  Found at:", idx, repr(c[max(0,idx-60):idx+20]))

# ============================================================
print()
print("Changes:", changes)
print("editModal:", 'editModal' in c)
print("_et=:", '_et=' in c)
print("strat-detail:", 'strat-detail' in c)
print("load() count:", c.count('load()'))
print("File size:", len(c))

f = open('api/dashboard.js', 'w')
f.write(c)
f.close()
print("Saved.")
