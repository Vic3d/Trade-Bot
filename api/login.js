/**
 * login.js — TradeMind Login Page
 * GET  /api/login → zeigt Login-Form
 * POST /api/login → prüft Passwort → setzt Session-Cookie → redirect
 * GET  /api/logout → löscht Session-Cookie → redirect
 */
const { sign, checkPassword, makeSessionCookie, clearSessionCookie, requireAuth } = require('../lib/auth');

const LOGIN_HTML = (error = '') => `<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TradeMind — Login</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    min-height: 100vh;
    background: #0f0f1a;
    display: flex; align-items: center; justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  }
  .card {
    background: #1a1a2e;
    border: 1px solid #2d2d4e;
    border-radius: 16px;
    padding: 40px;
    width: 100%;
    max-width: 380px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  }
  .logo {
    text-align: center;
    margin-bottom: 32px;
  }
  .logo h1 {
    font-size: 24px;
    font-weight: 700;
    background: linear-gradient(135deg, #7c3aed, #a855f7);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  .logo p { color: #6b7280; font-size: 13px; margin-top: 4px; }
  label { display: block; color: #9ca3af; font-size: 12px; font-weight: 600;
          letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 8px; }
  input[type=password] {
    width: 100%;
    background: #0f0f1a;
    border: 1px solid #374151;
    border-radius: 8px;
    color: #f9fafb;
    font-size: 16px;
    padding: 12px 16px;
    outline: none;
    transition: border-color 0.15s;
  }
  input[type=password]:focus { border-color: #7c3aed; }
  .error {
    background: rgba(239,68,68,0.1);
    border: 1px solid rgba(239,68,68,0.3);
    border-radius: 8px;
    color: #f87171;
    font-size: 13px;
    padding: 10px 14px;
    margin-bottom: 16px;
  }
  button {
    width: 100%;
    background: linear-gradient(135deg, #7c3aed, #6d28d9);
    border: none;
    border-radius: 8px;
    color: #fff;
    cursor: pointer;
    font-size: 15px;
    font-weight: 600;
    margin-top: 20px;
    padding: 13px;
    transition: opacity 0.15s;
  }
  button:hover { opacity: 0.9; }
  .field { margin-bottom: 8px; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <h1>🎩 TradeMind</h1>
    <p>Private Trading Dashboard</p>
  </div>
  ${error ? `<div class="error">⚠️ ${error}</div>` : ''}
  <form method="POST" action="/api/login">
    <div class="field">
      <label>Passwort</label>
      <input type="password" name="password" autofocus autocomplete="current-password" placeholder="••••••••••••">
    </div>
    <button type="submit">Einloggen →</button>
  </form>
</div>
</body>
</html>`;

module.exports = async (req, res) => {
  // ── GET /api/logout ──
  if (req.url && req.url.includes('logout')) {
    res.writeHead(302, {
      'Set-Cookie': clearSessionCookie(),
      Location: '/api/login'
    });
    return res.end();
  }

  // ── GET /api/login → Form ──
  if (req.method === 'GET') {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store');
    return res.end(LOGIN_HTML());
  }

  // ── POST /api/login → Passwort prüfen ──
  if (req.method === 'POST') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      const params   = new URLSearchParams(body);
      const password = params.get('password') || '';

      if (!checkPassword(password)) {
        res.setHeader('Content-Type', 'text/html; charset=utf-8');
        return res.end(LOGIN_HTML('Falsches Passwort. Bitte erneut versuchen.'));
      }

      // Passwort korrekt → Session-Token erstellen
      const token = sign({ user: 'victor', role: 'admin' });
      res.writeHead(302, {
        'Set-Cookie': makeSessionCookie(token),
        Location: '/api/dashboard'
      });
      res.end();
    });
    return;
  }

  res.writeHead(405);
  res.end('Method not allowed');
};
