#!/usr/bin/env python3
"""
E-Mail Monitor für Schutzeichel — prüft alle Postfächer auf Kundenanfragen
und aktualisiert das Dashboard.
"""

import re
import json
import urllib.parse
import urllib.request
import ssl
import http.cookiejar
import os
import hashlib
from datetime import datetime

# Zugangsdaten
ACCOUNTS = [
    {"name": "INFO2",    "user": r"phx-hosting\info2",    "pass": "*8166Belinea",  "relevant": True},
    {"name": "AUFTRAG",  "user": r"phx-hosting\auftrag",  "pass": "*8166*Belinea", "relevant": True},
    {"name": "RECHNUNG", "user": r"phx-hosting\rechnung", "pass": "*8166*Belinea", "relevant": False},
    {"name": "VICTOR",   "user": r"phx-hosting\victor",   "pass": "*8166Belinea",  "relevant": False},
]

OWA_BASE = "https://mail.phx-hosting.de"
OWA_LOGIN = f"{OWA_BASE}/owa/auth.owa"
OWA_INBOX = f"{OWA_BASE}/owa/"
DASHBOARD_FILE = "/data/.openclaw/workspace/dashboard/email-dashboard.html"
STATE_FILE  = "/data/.openclaw/workspace/memory/email-state.json"
LOG_FILE    = "/data/.openclaw/workspace/memory/email-log.md"

# Keywords für Kundenanfragen
INQUIRY_KEYWORDS = [
    'anfrage', 'auftrag', 'reparatur', 'installation', 'wartung',
    'heizung', 'sanitär', 'wasser', 'gas', 'rohr', 'bohandwerk', 'handwerker',
    'kopplung', 'buo_auftrag', 'störung', 'notfall', 'schaden', 'leck',
    'therme', 'boiler', 'heizkörper', 'termin', 'angebot', 'kostenvoranschlag',
    'gewähr', 'mangel', 'risadelli', 'pertec', 'tsp', 'b&o'
]

# Bekannte Spam/Irrelevant Absender+Betreff — MyHammer komplett ignorieren (Victor, 10.03.2026)
# Schadstoffhinweis ignorieren (Victor, 11.03.2026)
SKIP_SENDERS = [
    'qm - akademie', 'spam', 'instagram', 'viessmann.live',
    'fachverband shk', 'dortmund@info.vi',
    'myhammer', 'my-hammer', 'my hammer', 'noreply@info.my-hammer.de',
    'info@my-hammer.de', 'service@my-hammer.de',
    'schadstoffhinweis',
]

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


OWA_UA = "curl/7.88.1"  # Triggert OWA Basic Mode (kein JS, parseable HTML)


def owa_request(path, cookies=None, method="GET", body=None, extra_headers=None):
    """Generische HTTPS-Anfrage an den OWA-Server im Basic Mode."""
    import http.client
    headers = {
        "Content-Length": str(len(body)) if body else "0",
        "User-Agent": OWA_UA,
    }
    if body:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if cookies:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    if extra_headers:
        headers.update(extra_headers)
    conn = http.client.HTTPSConnection("mail.phx-hosting.de", timeout=15, context=ctx)
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    all_headers = resp.getheaders()
    status = resp.status
    conn.close()
    return status, dict(all_headers), data.decode('utf-8', errors='replace'), all_headers


def owa_login(username, password):
    """Loggt in OWA ein und gibt die Session-Cookies zurück."""
    body = urllib.parse.urlencode({
        "destination": f"{OWA_BASE}/owa/",
        "flags": "4", "forcedownlevel": "0", "isUtf8": "1",
        "username": username, "password": password
    }).encode()

    try:
        status, headers_dict, _, all_headers = owa_request(
            "/owa/auth.owa", method="POST", body=body)
        if status in (302, 301):
            cookies = {}
            for k, v in all_headers:
                if k.lower() == "set-cookie":
                    m = re.match(r'(\w+)=([^;]+)', v)
                    if m:
                        cookies[m.group(1)] = m.group(2)
            return cookies
    except Exception as ex:
        print(f"Login-Fehler: {ex}")
    return {}


def make_cookie_header(cookies):
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def get_inbox_html(cookies):
    """Lädt den Posteingang im Basic Mode."""
    try:
        status, _, html, _ = owa_request("/owa/", cookies=cookies)
        return html
    except Exception as ex:
        print(f"Inbox-Fehler: {ex}")
        return ""


def detect_type(text):
    """Kategorisiert eine E-Mail nach Typ."""
    t = text.lower()
    if 'myhammer' in t or 'my-hammer' in t:
        return 'myhammer'
    if 'bohandwerkerkopplung' in t or 'handwerkerkopplung' in t or 'noreply-bohandwe' in t:
        return 'bo_kopplung'
    if 'risadelli' in t or 'technikserviceplus' in t or 'buo_auftrag' in t or 'als anlage erhalten' in t:
        return 'tsp'
    if 'zahlungsavise' in t:
        return 'zahlung'
    return 'direkt'


def parse_emails(html):
    """Extrahiert E-Mails aus dem Inbox-HTML."""
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    emails = []

    id_pattern = r'name="chkmsg" value="(RgAAAA[A-Za-z0-9+/=]+AAAJ)"'
    all_ids = re.findall(id_pattern, html)

    email_rows = []
    raw_rows   = []
    for row in rows:
        clean = re.sub(r'<[^>]+>', ' ', row)
        clean = clean.replace('&nbsp;', ' ')
        clean = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))) if int(m.group(1)) < 65536 else '?', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        if re.search(r'\d{2}\.\d{2}\.\d{4}', clean) and len(clean) > 20:
            email_rows.append(clean)
            raw_rows.append(row)

    for i, row in enumerate(email_rows):
        date_m   = re.search(r'(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})', row)
        date_str = f"{date_m.group(1)} {date_m.group(2)}" if date_m else ""

        # Inhalt vor dem Datum = Absender + Betreff (nicht kürzen für volle Info)
        content  = row[:date_m.start()].strip() if date_m else row
        # Leerzeichen-Wiederholungen bereinigen
        content  = re.sub(r'\s+', ' ', content).strip()

        size_m   = re.search(r'(\d+(?:\.\d+)?\s*(?:KB|MB))', row)
        size     = size_m.group(1) if size_m else ""

        msg_id   = all_ids[i] if i < len(all_ids) else ""
        owa_link = f"https://mail.phx-hosting.de/owa/?ae=Item&t=IPM.Note&id={urllib.parse.quote(msg_id)}&a=Open" if msg_id else ""

        is_inquiry = any(kw in row.lower() for kw in INQUIRY_KEYWORDS)
        is_skip    = any(sk in row.lower() for sk in SKIP_SENDERS)
        is_unread  = '<b>' in (raw_rows[i] if i < len(raw_rows) else "")
        email_type = detect_type(row)

        emails.append({
            "content":    content,
            "date":       date_str,
            "size":       size,
            "id":         msg_id,
            "link":       owa_link,
            "is_inquiry": is_inquiry and not is_skip,
            "is_unread":  is_unread,
            "type":       email_type,
        })

    return emails


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"known_ids": [], "last_check": None, "inquiries": []}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


DASH_PASSWORD = "Schutzeichel2026"  # Passwort für Dashboard-Zugang

TYPE_META = {
    'myhammer':   {"label": "MyHammer",    "icon": "🔨", "color": "#f97316", "bg": "#431407", "border": "#c2410c"},
    'bo_kopplung':{"label": "B&O Auftrag", "icon": "🏢", "color": "#22d3ee", "bg": "#0c4a6e", "border": "#0891b2"},
    'tsp':        {"label": "TSP",         "icon": "📋", "color": "#a3e635", "bg": "#1a2e05", "border": "#4d7c0f"},
    'zahlung':    {"label": "Zahlung",     "icon": "💶", "color": "#facc15", "bg": "#422006", "border": "#a16207"},
    'direkt':     {"label": "Direktanfrage","icon":"👤", "color": "#c084fc", "bg": "#2e1065", "border": "#7c3aed"},
}

POSTFACH_META = {
    "INFO2":   {"label": "INFO2",   "color": "#bfdbfe", "bg": "#1e3a5f"},
    "AUFTRAG": {"label": "AUFTRAG", "color": "#a7f3d0", "bg": "#064e3b"},
}


def generate_dashboard(all_data, new_count):
    """Erstellt das HTML-Dashboard — gruppiert nach Typ, mit Passwortschutz."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    # Alle Anfragen sammeln und nach Typ sortieren
    all_inquiries = []
    for account_name, emails in all_data.items():
        for e in emails:
            if e['is_inquiry']:
                all_inquiries.append({**e, "account": account_name})

    # Gruppieren nach Typ
    groups = {}
    for e in all_inquiries:
        t = e.get('type', 'direkt')
        groups.setdefault(t, []).append(e)

    # Reihenfolge der Gruppen — myhammer komplett ausgeblendet (Victor, 10.03.2026)
    type_order = ['bo_kopplung', 'tsp', 'direkt', 'zahlung']

    sections_html = ""
    total_new = sum(1 for e in all_inquiries if e.get('is_new'))

    for typ in type_order:
        if typ not in groups:
            continue
        meta  = TYPE_META.get(typ, TYPE_META['direkt'])
        items = groups[typ]
        count = len(items)
        new_in_group = sum(1 for e in items if e.get('is_new'))

        rows = ""
        for e in items:
            pfach    = e.get('account', '?')
            pm       = POSTFACH_META.get(pfach, {"label": pfach, "color": "#94a3b8", "bg": "#1e293b"})
            is_new   = e.get('is_new', False)
            is_unread= e.get('is_unread', False)
            link     = e.get('link', '')
            content  = e.get('content', '')
            date     = e.get('date', '')
            size     = e.get('size', '')

            new_badge   = '<span class="badge-new">NEU</span>' if is_new else ''
            unread_style= 'font-weight:700;' if is_unread else 'font-weight:400;'
            link_open   = f'<a href="{link}" target="_blank" style="color:inherit;text-decoration:none;">' if link else ''
            link_close  = '</a>' if link else ''

            rows += f"""
              <tr class="email-row" style="{unread_style}">
                <td class="td-postfach">
                  <span class="badge-postfach" style="background:{pm['bg']};color:{pm['color']};">{pm['label']}</span>
                </td>
                <td class="td-content">
                  {new_badge}
                  {link_open}<span class="email-text">{content}</span>{link_close}
                </td>
                <td class="td-date">{date}</td>
                <td class="td-size">{size}</td>
              </tr>"""

        new_group_badge = f'<span class="group-new">{new_in_group} neu</span>' if new_in_group else ''
        sections_html += f"""
        <div class="group-section">
          <div class="group-header" style="border-left:4px solid {meta['border']};background:{meta['bg']}22;">
            <span class="group-icon">{meta['icon']}</span>
            <span class="group-label" style="color:{meta['color']};">{meta['label']}</span>
            <span class="group-count">{count}</span>
            {new_group_badge}
          </div>
          <table>
            <thead>
              <tr>
                <th style="width:90px">Postfach</th>
                <th>Absender / Betreff</th>
                <th style="width:130px">Datum</th>
                <th style="width:60px">Größe</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""

    if not sections_html:
        sections_html = '<div style="padding:40px;text-align:center;color:#64748b;font-size:14px;">✅ Keine offenen Anfragen</div>'

    total_inquiries = len(all_inquiries)
    info2_count  = len([e for e in all_inquiries if e['account'] == 'INFO2'])
    auftr_count  = len([e for e in all_inquiries if e['account'] == 'AUFTRAG'])

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="300">
<title>Schutzeichel — Kundenanfragen</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}}

  /* Login-Screen */
  #login-screen{{position:fixed;inset:0;background:#0f172a;display:flex;align-items:center;justify-content:center;z-index:9999}}
  #login-box{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:40px 36px;width:340px;text-align:center}}
  #login-box h2{{color:#fff;font-size:20px;margin-bottom:6px}}
  #login-box p{{color:#64748b;font-size:13px;margin-bottom:24px}}
  #login-box input{{width:100%;padding:10px 14px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;font-size:15px;margin-bottom:12px;outline:none}}
  #login-box input:focus{{border-color:#3b82f6}}
  #login-box button{{width:100%;padding:11px;border-radius:8px;background:#3b82f6;color:#fff;font-size:15px;font-weight:600;border:none;cursor:pointer}}
  #login-box button:hover{{background:#2563eb}}
  #login-error{{color:#f87171;font-size:13px;margin-top:10px;display:none}}

  /* App */
  #app{{display:none}}
  .topbar{{background:#1e293b;border-bottom:1px solid #334155;padding:14px 24px;display:flex;align-items:center;justify-content:space-between}}
  .topbar-title{{font-size:17px;font-weight:700;color:#fff}}
  .topbar-sub{{font-size:12px;color:#64748b;margin-top:2px}}
  .topbar-right{{display:flex;align-items:center;gap:12px}}
  .badge-total{{background:#ef4444;color:#fff;padding:3px 11px;border-radius:20px;font-size:12px;font-weight:700}}

  .stats-bar{{display:flex;gap:0;border-bottom:1px solid #1e293b}}
  .stat-box{{flex:1;padding:14px 20px;border-right:1px solid #1e293b;text-align:center}}
  .stat-box:last-child{{border-right:none}}
  .stat-num{{font-size:26px;font-weight:800;color:#fff}}
  .stat-label{{font-size:11px;color:#64748b;margin-top:2px;text-transform:uppercase;letter-spacing:.04em}}

  .group-section{{border-bottom:1px solid #1e293b}}
  .group-header{{display:flex;align-items:center;gap:10px;padding:12px 20px;cursor:pointer;user-select:none}}
  .group-header:hover{{background:#ffffff08}}
  .group-icon{{font-size:16px}}
  .group-label{{font-size:14px;font-weight:700;flex:1}}
  .group-count{{background:#334155;color:#94a3b8;padding:2px 9px;border-radius:12px;font-size:12px;font-weight:600}}
  .group-new{{background:#ef4444;color:#fff;padding:2px 9px;border-radius:12px;font-size:12px;font-weight:700}}

  table{{width:100%;border-collapse:collapse}}
  th{{text-align:left;padding:9px 12px;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#475569;border-bottom:1px solid #1e293b;background:#0d1b2a}}
  .email-row td{{padding:10px 12px;border-bottom:1px solid #0f172a;vertical-align:middle}}
  .email-row:hover td{{background:#1e293b55}}
  .email-row:last-child td{{border-bottom:none}}

  .td-postfach{{width:90px}}
  .td-content{{max-width:0;width:100%}}
  .td-date{{width:130px;white-space:nowrap;color:#64748b;font-size:12px}}
  .td-size{{width:60px;text-align:right;color:#475569;font-size:11px}}

  .badge-postfach{{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:700;white-space:nowrap}}
  .badge-new{{display:inline-block;background:#ef4444;color:#fff;padding:1px 6px;border-radius:5px;font-size:10px;font-weight:700;margin-right:6px;vertical-align:middle}}

  .email-text{{font-size:13px;color:#cbd5e1;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
  .email-text:hover{{color:#fff}}

  .logout-btn{{background:none;border:1px solid #334155;color:#94a3b8;padding:5px 12px;border-radius:6px;font-size:12px;cursor:pointer}}
  .logout-btn:hover{{border-color:#64748b;color:#e2e8f0}}
</style>
</head>
<body>

<!-- LOGIN -->
<div id="login-screen">
  <div id="login-box">
    <h2>🔐 Schutzeichel</h2>
    <p>Posteingang — Kundenanfragen</p>
    <input type="password" id="pw-input" placeholder="Passwort" onkeydown="if(event.key==='Enter')checkPw()">
    <button onclick="checkPw()">Anmelden</button>
    <div id="login-error">Falsches Passwort</div>
  </div>
</div>

<!-- APP -->
<div id="app">
  <div class="topbar">
    <div>
      <div class="topbar-title">📬 Schutzeichel — Kundenanfragen
        {"<span class='badge-total'>" + str(total_new) + " neu</span>" if total_new > 0 else ""}
      </div>
      <div class="topbar-sub">Zuletzt aktualisiert: {now} · automatisch alle 5 Min.</div>
    </div>
    <div class="topbar-right">
      <button class="logout-btn" onclick="logout()">Abmelden</button>
    </div>
  </div>

  <div class="stats-bar">
    <div class="stat-box">
      <div class="stat-num">{total_inquiries}</div>
      <div class="stat-label">Gesamt</div>
    </div>
    <div class="stat-box">
      <div class="stat-num" style="color:#bfdbfe">{info2_count}</div>
      <div class="stat-label">INFO2</div>
    </div>
    <div class="stat-box">
      <div class="stat-num" style="color:#a7f3d0">{auftr_count}</div>
      <div class="stat-label">AUFTRAG</div>
    </div>
    <div class="stat-box">
      <div class="stat-num" style="color:#fca5a5">{total_new}</div>
      <div class="stat-label">Neu erkannt</div>
    </div>
  </div>

  {sections_html}
</div>

<script>
const PASS = "{DASH_PASSWORD}";
function checkPw(){{
  const v = document.getElementById('pw-input').value;
  if(v === PASS){{
    sessionStorage.setItem('auth','1');
    document.getElementById('login-screen').style.display='none';
    document.getElementById('app').style.display='block';
    document.getElementById('login-error').style.display='none';
  }} else {{
    document.getElementById('login-error').style.display='block';
    document.getElementById('pw-input').value='';
    document.getElementById('pw-input').focus();
  }}
}}
function logout(){{
  sessionStorage.removeItem('auth');
  location.reload();
}}
// Auto-Login wenn Session noch aktiv
if(sessionStorage.getItem('auth')==='1'){{
  document.getElementById('login-screen').style.display='none';
  document.getElementById('app').style.display='block';
}}
// Collapsible groups
document.querySelectorAll('.group-header').forEach(h=>{{
  h.addEventListener('click',()=>{{
    const t=h.nextElementSibling;
    if(t)t.style.display=t.style.display==='none'?'':'none';
  }});
}});
</script>
</body>
</html>"""

    os.makedirs(os.path.dirname(DASHBOARD_FILE), exist_ok=True)
    with open(DASHBOARD_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    return DASHBOARD_FILE


def write_log(new_inquiries):
    """Hält jede neue Anfrage mit Postfach, Absender/Betreff und Datum im Log fest."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    # Datei anlegen falls nicht vorhanden
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("# E-Mail Log — Kundenanfragen Gebr. Schutzeichel\n\n")
            f.write("| Erkannt am | Postfach | Absender / Betreff | Mail-Datum |\n")
            f.write("|-----------|----------|-------------------|------------|\n")

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        for inq in new_inquiries:
            content = inq['content'].replace('|', '/').strip()
            date    = inq.get('date', '').strip()
            account = inq.get('account', '?')
            f.write(f"| {now} | **{account}** | {content[:80]} | {date} |\n")


def main():
    state = load_state()
    known_ids = set(state.get("known_ids", []))
    all_data = {}
    new_inquiries = []

    for acc in ACCOUNTS:
        print(f"  → {acc['name']} einloggen...", end=" ", flush=True)
        cookies = owa_login(acc['user'], acc['pass'])
        if not cookies:
            print("FEHLER")
            all_data[acc['name']] = []
            continue
        
        html = get_inbox_html(cookies)
        if not html:
            print("INBOX LEER/FEHLER")
            all_data[acc['name']] = []
            continue
        
        emails = parse_emails(html)
        
        # Bei nicht-relevanten Accounts: keine Kundenanfragen markieren
        if not acc['relevant']:
            for e in emails:
                e['is_inquiry'] = False

        # Neue IDs markieren
        for e in emails:
            e['is_new'] = e['id'] and e['id'] not in known_ids
            if e['is_new'] and e['is_inquiry']:
                new_inquiries.append({"account": acc['name'], **e})
                known_ids.add(e['id'])
        
        all_data[acc['name']] = emails
        total = len(emails)
        inquiries = len([e for e in emails if e['is_inquiry']])
        print(f"OK ({total} Mails, {inquiries} Anfragen)")

    # Dashboard generieren
    dashboard = generate_dashboard(all_data, len(new_inquiries))
    print(f"\n  ✅ Dashboard: {dashboard}")
    
    # State speichern
    state['known_ids'] = list(known_ids)
    state['last_check'] = datetime.now().isoformat()
    state['inquiries'] = new_inquiries
    save_state(state)

    # Log schreiben — jede neue Anfrage mit Postfach festhalten
    if new_inquiries:
        write_log(new_inquiries)
    
    # Neue Anfragen als JSON ausgeben (für Cron/Benachrichtigung)
    print(f"\n  📊 Neue Anfragen: {len(new_inquiries)}")
    for inq in new_inquiries:
        print(f"     [{inq['account']}] {inq['content'][:60]} — {inq['date']}")
    
    return new_inquiries


if __name__ == "__main__":
    print(f"\n🔍 E-Mail Check — {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    results = main()
    print("\nFertig.\n")
