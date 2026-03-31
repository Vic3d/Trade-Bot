#!/usr/bin/env python3
"""Patch dashboard.js with modal, edit buttons, strategy detail."""

f = open('api/dashboard.js', 'r')
c = f.read()
f.close()

changes = []

# === 1. Modal CSS before </style> ===
modal_css = (
    '.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:1000;display:none;align-items:center;justify-content:center}'
    '.modal-bg.open{display:flex}'
    '.modal{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:24px;min-width:320px;max-width:500px;width:90vw}'
    '.modal h3{font-size:1rem;margin-bottom:14px;color:var(--cyan)}'
    '.modal label{font-size:.75rem;color:var(--dim);display:block;margin-top:10px;margin-bottom:3px}'
    '.modal input{width:100%;background:#0a0e17;border:1px solid var(--border);color:var(--text);border-radius:6px;padding:8px 10px;font-size:.88rem}'
    '.modal .btns{display:flex;gap:8px;margin-top:14px}'
    '.btn-save{background:var(--cyan);color:#000;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-weight:600;font-size:.85rem}'
    '.btn-cancel{background:var(--border);color:var(--text);border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-size:.85rem}'
    '.edit-btn{background:none;border:1px solid var(--border);color:var(--dim);padding:3px 8px;border-radius:5px;cursor:pointer;font-size:.7rem}'
    '.edit-btn:hover{border-color:var(--cyan);color:var(--cyan)}'
    '.strat-detail{display:none;margin-top:10px;padding-top:10px;border-top:1px solid var(--border);font-size:.8rem;line-height:1.6}'
    '.strat-card.open .strat-detail{display:block}'
)

# In the file the </style> appears as: \\n</style>\\n</head>
target_style = '\\n</style>\\n</head>'
if target_style in c:
    c = c.replace(target_style, modal_css + target_style, 1)
    changes.append('CSS')
else:
    print("WARN: style end not found")

# === 2. Modal HTML + JS before load() ===
# In the file: load();\\n</script>\\n</body>\\n</html>
modal_block = (
    '<div class=\\"modal-bg\\" id=\\"editModal\\"><div class=\\"modal\\">'
    '<h3>\\u270f\\ufe0f <span id=\\"eticker\\"></span></h3>'
    '<label>Stop (\\u20ac)</label><input type=\\"number\\" id=\\"estop\\" step=\\"0.01\\">'
    '<label>Ziel (\\u20ac)</label><input type=\\"number\\" id=\\"etarget\\" step=\\"0.01\\">'
    '<div class=\\"btns\\">'
    '<button class=\\"btn-save\\" onclick=\\"savePos()\\">Speichern</button>'
    '<button class=\\"btn-cancel\\" onclick=\\"closeEditModal()\\">Abbrechen</button>'
    '</div><div id=\\"emsg\\" style=\\"font-size:.8rem;margin-top:8px\\"></div>'
    '</div></div>'
)
js_block = (
    'var _et="";'
    'function openEdit(t,stop,tgt){'
    '_et=t;var m=$("editModal");'
    '$("eticker").textContent=t;'
    '$("estop").value=stop||"";'
    '$("etarget").value=tgt||"";'
    '$("emsg").textContent="";'
    'm.classList.add("open");}'
    'function closeEditModal(){$("editModal").classList.remove("open");}'
    '$("editModal").addEventListener("click",function(e){if(e.target===$("editModal"))closeEditModal();});'
    'async function savePos(){'
    'var stop=$("estop").value,tgt=$("etarget").value,msg=$("emsg");'
    'msg.textContent="\\u23f3...";msg.style.color="var(--dim)";'
    'try{'
    'var r=await fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({ticker:_et,stop_eur:stop?parseFloat(stop):undefined,target_eur:tgt?parseFloat(tgt):undefined})});'
    'var d=await r.json();'
    'if(r.ok){msg.textContent="\\u2705 "+(d.changes||[]).join(", ");msg.style.color="var(--green)";setTimeout(closeEditModal,2000);}'
    'else{msg.textContent="\\u274c "+d.error;msg.style.color="var(--red)";}'
    '}catch(e){msg.textContent="\\u274c "+e.message;msg.style.color="var(--red)";}'
    '}'
    'function togStrat(el){el.closest(".strat-card").classList.toggle("open");}'
)

target_load = 'load();\\n</script>\\n</body>\\n</html>'
if target_load in c:
    insert = modal_block + '\\n<script>\\n' + js_block + '\\n</script>\\n'
    c = c.replace(target_load, insert + target_load, 1)
    changes.append('Modal+JS')
else:
    print("WARN: load() end pattern not found")
    print("Last 200:", repr(c[-250:]))

# === 3. Position table header: add Edit column ===
target_hdr = '<th>Notiz</th></tr>'
if target_hdr in c:
    c = c.replace(target_hdr, '<th>Notiz</th><th></th></tr>', 1)
    changes.append('Header col')

# === 4. Position row: edit button ===
# In file: style=\\'max-width:200px\\'>"+esc(p.notes)+"</td></tr>
target_row_end = "style=\\'max-width:200px\\'>\\"+esc(p.notes)+\\"</td></tr>"
if target_row_end in c:
    new_row_end = (
        "style=\\'max-width:200px\\'>\"+esc(p.notes)+\"</td>"
        "<td><button class=\\'edit-btn\\' "
        "onclick=\\'openEdit(\"+JSON.stringify(p.ticker)+\",\"+(p.stop||0)+\",\"+((p.targets&&p.targets[0])||0)+\")\\'"
        ">\\u270f\\ufe0f</button></td></tr>"
    )
    c = c.replace(target_row_end, new_row_end, 1)
    changes.append('Edit btn')
else:
    print("WARN: position row end not found")
    idx = c.find('max-width:200px')
    if idx != -1:
        print("  Sample:", repr(c[idx:idx+120]))

# === 5. Strategy card: clickable + detail ===
# Find: '<div class=\\"strat-card\\" style=\\"border-left-color:'+(s.color||'var(--cyan)')+'\\"><h4>'
# Change to: add onclick + expand detail

target_strat_h4 = (
    "'<div class=\\"strat-card\\" style=\\"border-left-color:'+"
    "(s.color||'var(--cyan)')+'\\"><h4>'"
)
if target_strat_h4 in c:
    new_strat_h4 = (
        "'<div class=\\"strat-card\\" style=\\"border-left-color:'+"
        "(s.color||'var(--cyan)')+'; cursor:pointer\\" onclick=\\"togStrat(this)\\"><h4>'"
    )
    c = c.replace(target_strat_h4, new_strat_h4, 1)
    changes.append('Strat clickable')

# Now inject detail panel after the meta div, before </div></div>
target_strat_close = "+'</div></div>';\n  }).join('');"
new_strat_detail = (
    "+'<div class=\\"strat-detail\\">'"
    "+(full.thesis?'<p><strong style=\\"color:var(--cyan)\\">These:</strong><br>'+esc(full.thesis)+'</p>':'')"
    "+(full.entry_trigger?'<p><strong style=\\"color:var(--green)\\">Entry-Trigger:</strong><br>'+esc(full.entry_trigger)+'</p>':'')"
    "+(full.kill_trigger?'<p><strong style=\\"color:var(--red)\\">Kill-Switch:</strong><br>'+esc(full.kill_trigger)+'</p>':'')"
    "+'</div>"
    "</div></div>';\n  }).join('');"
)
if target_strat_close in c:
    c = c.replace(target_strat_close, new_strat_detail, 1)
    changes.append('Strat detail')
else:
    print("WARN: strategy close not found")
    idx = c.find("}).join('')")
    print("  }).join at:", idx, repr(c[max(0,idx-80):idx+20]))

print()
print("Changes applied:", changes)
print("editModal:", 'editModal' in c)
print("openEdit:", 'openEdit' in c)
print("strat-detail:", 'strat-detail' in c)
print("load() calls:", c.count('load()'))

f = open('api/dashboard.js','w')
f.write(c)
f.close()
print("Saved.")
