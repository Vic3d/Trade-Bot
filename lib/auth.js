/**
 * auth.js — TradeMind Auth-Modul
 * JWT-basierte Session-Cookies ohne externe Dependencies.
 * Passwort-Hash + JWT-Secret kommen aus Vercel ENV vars.
 */
const crypto = require('crypto');

const JWT_SECRET    = process.env.JWT_SECRET    || 'fallback-secret-change-in-vercel';
const PASSWORD_HASH = process.env.PASSWORD_HASH || '1ef4b03ac582c0c1b03c8c569bb9e40eaae9959e8e62406d08b9fd90ad4522f6'; // SHA256("TradeMind2026")
const SESSION_DAYS  = 7;

// ── JWT (ohne externe Lib) ───────────────────────────────────

function sign(payload) {
  const h = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const b = b64url(JSON.stringify({ ...payload, iat: Date.now() }));
  const s = crypto.createHmac('sha256', JWT_SECRET).update(`${h}.${b}`).digest('base64url');
  return `${h}.${b}.${s}`;
}

function verify(token) {
  try {
    const [h, b, s] = token.split('.');
    const expected  = crypto.createHmac('sha256', JWT_SECRET).update(`${h}.${b}`).digest('base64url');
    if (s !== expected) return null;
    const payload = JSON.parse(Buffer.from(b, 'base64url').toString());
    if (Date.now() - payload.iat > SESSION_DAYS * 86400 * 1000) return null;
    return payload;
  } catch { return null; }
}

function b64url(str) {
  return Buffer.from(str).toString('base64url');
}

// ── Passwort-Prüfung ─────────────────────────────────────────

function checkPassword(input) {
  const hash = crypto.createHash('sha256').update(input).digest('hex');
  return hash === PASSWORD_HASH;
}

// ── Cookie-Handling ──────────────────────────────────────────

function getSessionCookie(req) {
  const cookies = req.headers.cookie || '';
  const match   = cookies.match(/tm_session=([^;]+)/);
  return match ? match[1] : null;
}

function makeSessionCookie(token) {
  return `tm_session=${token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${SESSION_DAYS * 86400}`;
}

function clearSessionCookie() {
  return 'tm_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0';
}

// ── Auth-Check (für jeden geschützten Endpoint) ──────────────

/**
 * Gibt true zurück wenn Session valid.
 * Gibt false zurück und sendet 302 → /api/login wenn nicht.
 */
function requireAuth(req, res) {
  const token = getSessionCookie(req);
  if (token && verify(token)) return true;
  res.writeHead(302, { Location: '/api/login' });
  res.end();
  return false;
}

module.exports = { sign, verify, checkPassword, getSessionCookie, makeSessionCookie, clearSessionCookie, requireAuth };
