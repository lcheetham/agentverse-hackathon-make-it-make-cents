// Small helpers: escaping, formatting, DOM states.
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const MINUS = '−';
const isNum = (x) => typeof x === 'number' && Number.isFinite(x);
export const shortAddr = (a) => (a && a.length > 12 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a || '');
export const usd = (x) => (isNum(x) ? `${x < 0 ? MINUS : ''}$${Math.round(Math.abs(x)).toLocaleString('en-GB')}` : '–');
export const gbp = (x, dp = 0) => (isNum(x) ? `${x < 0 ? MINUS : ''}£${Math.abs(x).toLocaleString('en-GB', { minimumFractionDigits: dp, maximumFractionDigits: dp })}` : '–');
export const pct = (x, dp = 0) => (isNum(x) ? `${(x * 100).toFixed(dp)}%` : '–');
export const spct = (x, dp = 1) => (isNum(x) ? `${x >= 0 ? '+' : MINUS}${Math.abs(x * 100).toFixed(dp)}%` : '–');
export const cents = (p) => (isNum(p) ? `${Math.round(p * 100)}c` : '–');
export const signedUsd = (x) => (isNum(x) ? `${x >= 0 ? '+' : MINUS}$${Math.round(Math.abs(x)).toLocaleString('en-GB')}` : '–');
export const signedGbp = (x) => (isNum(x) ? `${x >= 0 ? '+' : MINUS}£${Math.abs(x).toFixed(2)}` : '–');
export const cls = (x) => (isNum(x) ? (x >= 0 ? 'pos' : 'neg') : '');
export function luckPct(score, upper) {
  if (!isNum(score)) return '–';
  const s = score >= 0.9995 ? '>99.9%' : score < 0.001 ? '<0.1%' : score < 0.01 ? `${(score * 100).toFixed(1)}%` : `${Math.round(score * 100)}%`;
  return upper && !s.startsWith('<') ? `<${s}` : s;
}
export function fmtTs(ts, withTime = false) {
  if (typeof ts === 'string') { const d = new Date(ts); return isNaN(d) ? ts : d.toISOString().replace('T', ' ').slice(0, 19) + 'Z'; }
  if (!isNum(ts)) return '–';
  const d = new Date(ts * 1000);
  const day = d.toISOString().slice(0, 10);
  return withTime ? `${day} ${d.toISOString().slice(11, 16)} UTC` : day;
}
export function delayLabel(s) { return { 0: 'no delay', 300: '5 min', 3600: '1 h', 86400: '1 day' }[s] ?? `${s}s`; }

export const VERDICTS = {
  SKILLED_COPYABLE: { label: 'Skilled and copyable', tone: 'good', v: 'v-good' },
  SKILLED_NOT_COPYABLE: { label: 'Skilled but not copyable', tone: 'warn', v: 'v-warn' },
  CANT_TELL: { label: "Can't tell yet", tone: 'slate', v: 'v-slate' },
  PROBABLY_LUCK: { label: 'Probably luck', tone: 'bad', v: 'v-bad' },
  HOLD: { label: 'Hold – human review', tone: 'warn', v: 'v-warn' },
};
// Accepts a code string or {code,label}
export function verdictInfo(v) {
  const code = typeof v === 'string' ? v : v?.code;
  const base = VERDICTS[code] || { label: (typeof v === 'object' && v?.label) || code || 'Unknown', tone: 'slate', v: 'v-slate' };
  return { code, ...base, label: (typeof v === 'object' && v?.label) || base.label };
}
export const verdictChip = (v) => { const i = verdictInfo(v); return `<span class="chip ${i.tone}">${esc(i.label)}</span>`; };
export const synTag = (mode = 'synthetic') => (mode === 'synthetic' ? '<span class="chip chip-syn">Synthetic data</span>' : '<span class="chip good">Real Polymarket data</span>');

export const skeleton = (n = 4) => `<div class="panel" aria-busy="true" aria-label="Loading">${Array.from({ length: n }, (_, i) => `<div class="skeleton" style="width:${90 - i * 12}%"></div>`).join('')}</div>`;
export const errorState = (msg) => `<div class="panel state err" role="alert"><h2>Something went wrong</h2><p>${esc(msg)}</p><button class="btn primary" data-retry type="button">Retry</button></div>`;
export const emptyState = (title, body) => `<div class="panel state"><h2>${esc(title)}</h2><p class="muted">${esc(body)}</p></div>`;
