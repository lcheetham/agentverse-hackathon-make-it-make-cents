import { get } from './api.js';
import { esc, $, $$, errorState } from './util.js';
import { startBackground } from './bg.js';

export const ctx = { meta: null, refreshMeta: null };
let renderId = 0;
const routes = {
  home: () => import('./v-home.js'),
  wallet: () => import('./v-report.js'),
  paper: () => import('./v-live.js'),
  hood: () => import('./v-hood.js'),
};
// Old links (README, pitch notes, bookmarks) keep working.
const ALIASES = { '': 'home', leaderboard: 'home', agent: 'home', live: 'paper', evaluation: 'hood/tests', audit: 'hood/record' };
const NAV_OF = { home: 'home', wallet: 'home', paper: 'paper', hood: 'hood' };

// ---- "Technical details" switch: raw fields, hashes and engine diagnostics. Remembered per browser. ----
const TECH_KEY = 'ctdd.tech';
function setTech(on) {
  document.body.classList.toggle('tech', on);
  $('#tech').checked = on;
  try { localStorage.setItem(TECH_KEY, on ? '1' : '0'); } catch { /* storage unavailable: still works for this visit */ }
}
let techSaved = false;
try { techSaved = localStorage.getItem(TECH_KEY) === '1'; } catch { /* ignore */ }
setTech(techSaved);
$('#tech').addEventListener('change', (e) => setTech(e.target.checked));

function renderChrome(err) {
  const el = $('#chips'), ind = $('#ks-ind');
  if (err) {
    el.innerHTML = '<span class="chip chip-err">API unreachable</span>';
    ind.className = 'chip chip-err'; ind.textContent = 'Copying: unknown';
    return;
  }
  const m = ctx.meta, ks = m.kill_switch || {};
  el.innerHTML = `<span class="chip chip-dark" title="${esc(m.llm_available ? 'Gemini groups related bets, writes the report text (number-checked) and runs the agent' : 'No Gemini key: template text and heuristic clustering; the agent is off')}">LLM: ${esc(m.llm_available ? m.llm_mode : 'offline')}</span><span class="chip chip-dark">v${esc(m.version || '?')}</span>`;
  ind.className = `chip ${ks.on ? 'bad' : 'good'}`;
  ind.textContent = ks.on ? 'Copying: stopped' : 'Copying: allowed';
  ind.title = ks.on ? `Kill switch ON (${ks.reason || 'stopped'}). Only a human can turn it off, on the Paper trading page.` : 'Kill switch off. Click to manage it on the Paper trading page.';
  $('#foot-version').textContent = `Version ${m.version || '?'}`;
}

async function loadMeta() {
  try { ctx.meta = await get('/api/meta'); renderChrome(false); return true; } catch { renderChrome(true); return false; }
}
ctx.refreshMeta = loadMeta;

function parseHash() {
  let raw = location.hash.slice(1) || '/';
  let [path, q] = raw.split('?');
  let parts = path.split('/').filter(Boolean);
  const alias = ALIASES[parts[0] ?? ''];
  if (alias !== undefined) parts = [...alias.split('/'), ...parts.slice(1)];
  return { parts, q: new URLSearchParams(q || '') };
}

async function route() {
  const my = ++renderId;
  const main = $('#main');
  const { parts, q } = parseHash();
  const key = routes[parts[0]] ? parts[0] : null;
  $$('#nav a').forEach((a) => { const on = a.dataset.route === NAV_OF[key]; on ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'); });
  if (!key) { main.innerHTML = '<div class="panel state"><h2>Page not found</h2><p><a href="#/">Back to Home</a></p></div>'; return; }
  if (ctx.meta) loadMeta();          // keeps the kill-switch indicator current on every page change
  try {
    const mod = await routes[key]();
    if (my !== renderId) return;
    const api = { stale: () => my !== renderId, params: q, arg: parts[1] ? decodeURIComponent(parts[1]) : null, ctx, rerun: route, meta: ctx.meta };
    await mod.render(main, api);
  } catch (e) {
    if (my !== renderId) return;
    main.innerHTML = errorState(e.message);
    main.querySelector('[data-retry]')?.addEventListener('click', route);
  }
  if (my === renderId) {
    const h1 = main.querySelector('h1, h2'); if (h1) { h1.setAttribute('tabindex', '-1'); if (!main.dataset.first) { main.dataset.first = '1'; } else { h1.focus({ preventScroll: true }); window.scrollTo(0, 0); } }
    document.title = (main.querySelector('h1')?.textContent || 'Copy-Trader Due Diligence').slice(0, 70) + ' · Copy-Trader DD';
  }
}

startBackground($('#bg'));
window.addEventListener('hashchange', route);
loadMeta().then((ok) => {
  if (!ok) $('#chips').insertAdjacentHTML('beforeend', '<button class="btn small" type="button" id="meta-retry">Retry</button>');
  $('#meta-retry')?.addEventListener('click', async () => { if (await loadMeta()) route(); });
  route();
});
