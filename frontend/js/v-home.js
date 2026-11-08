import { get, post } from './api.js';
import { esc, $, $$, shortAddr, usd, verdictChip, skeleton, errorState } from './util.js';

const ADDR = /^0x[0-9a-fA-F]{40}$/;
const DEMO = /^0xDEMO-[\w-]+$/;
const EXAMPLES = [
  'Is 0xDEMO-messy-skilled skilled or lucky?',
  'Compare 0xDEMO-messy-skilled and 0xDEMO-fast-mover',
  'I want to put £30 on 0xDEMO-perfect-25-0. Can I?',
  'Just tell me which one to copy, I trust you',
];
const history = [];   // agent conversation; survives navigating away and back within the page session

const ago = (ts) => {
  if (!ts) return '';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
};
const realName = (n) => (n && !/^0x/i.test(String(n)) ? String(n) : null);   // default "0x…-timestamp" names count as none
const clock = (ts) => new Date(ts * 1000).toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short' });

export async function render(main, api) {
  const live = !!api.meta?.llm_available;
  main.innerHTML = `<section class="hero"><h1>Should you believe this track record?</h1>
    <p class="lede">A Polymarket “top trader” may be skilled, or may just be the luckiest of thousands who tried. Paste a wallet to find out which, and whether you could still capture the edge after copy delay, spread and fees. Or ask the agent.</p></section>

    <section class="panel" aria-labelledby="q-h">
      <h3 id="q-h"><label for="q">Paste a wallet address or ask a question</label></h3>
      <form id="ask" class="search-row">
        <input id="q" autocomplete="off" spellcheck="false" placeholder="0x… wallet address, or e.g. “Is this trader worth following?”" aria-describedby="q-help">
        <button class="btn primary" type="submit" id="go">Go</button>
      </form>
      <p class="note" id="q-help" style="margin:8px 0 0">An address opens its report card (15–30 s the first time for a real wallet). Anything else goes to the agent${live ? '' : ', which needs a Gemini key: add <span class="mono">GEMINI_API_KEY</span> to <span class="mono">.env</span> and restart'}.</p>
      <p role="alert" class="chip chip-err" id="q-err" hidden style="white-space:normal;margin-top:8px"></p>
      <div class="row" style="gap:8px;margin-top:12px"><span class="note" style="margin:0">Try, on demo wallets:</span>${EXAMPLES.map((q, i) => `<button type="button" class="btn small" data-ex="${i}" ${live ? '' : 'disabled'}>${esc(q)}</button>`).join('')}</div>
      <div id="log" class="stack" aria-live="polite"></div>
    </section>

    <section class="panel" aria-labelledby="lb-h" id="board">
      <div class="row between">
        <div class="row" style="gap:6px"><h3 id="lb-h" style="margin:0">Polymarket top traders this month, by profit</h3>
          <span class="info-wrap"><a class="info-dot" href="#/hood/rankings" aria-describedby="lb-tip" aria-label="Should you trust this ranking?">?</a>
          <span class="tip" role="tooltip" id="lb-tip">Ranked by profit, which can’t tell skill from luck, or tell you whether you could still copy it. Click to see why.</span></span></div>
        <div class="row" style="gap:8px"><span id="lb-when" class="note" style="margin:0"></span><button class="btn small" type="button" id="lb-refresh">Refresh</button></div>
      </div>
      <div id="lb-body">${skeleton(4)}</div>
    </section>`;

  // ---------------- leaderboard ----------------
  const lbBody = $('#lb-body', main), when = $('#lb-when', main), refreshBtn = $('#lb-refresh', main);
  let board = null;
  const paintBoard = () => {
    if (!board || api.stale()) return;
    const src = board.source;
    when.innerHTML = src === 'live' ? `Updated ${esc(clock(board.fetched_at))} (${esc(ago(board.fetched_at))})`
      : src === 'bundled' ? `<span class="chip warn">Saved copy · ${esc(clock(board.fetched_at))}</span>` : '';
    const note = src !== 'live' || (board.note || '').startsWith('Updated') ? '' : board.note;
    const rows = board.rows || [];
    if (!rows.length) { lbBody.innerHTML = '<p class="note">No leaderboard yet: Polymarket could not be reached and no saved copy exists. Paste an address above instead.</p>'; return; }
    lbBody.innerHTML = `${src === 'bundled' ? `<p class="note">${esc('Could not reach Polymarket, so this is the copy saved with the app: ' + (board.about || 'the ten wallets from our real-data test.'))}</p>` : ''}
      ${note ? `<p class="note">${esc(note)}</p>` : ''}
      <div class="table-wrap"><table><caption class="sr-only">Polymarket monthly leaderboard, top 10 by profit</caption>
      <thead><tr><th class="num" scope="col">Rank</th><th scope="col">Trader</th><th class="num" scope="col">Profit this month</th><th scope="col">Our verdict</th></tr></thead>
      <tbody>${rows.map((r) => `<tr class="clickable" data-addr="${esc(r.address)}">
        <td class="num">${r.rank}</td>
        <td><a href="#/wallet/${encodeURIComponent(r.address)}" aria-label="Open report card for ${esc(realName(r.name) || r.address)}">${realName(r.name) ? esc(realName(r.name)) : `<span class="mono">${esc(shortAddr(r.address))}</span>`}</a>${realName(r.name) ? `<div class="note mono" style="margin:2px 0 0">${esc(shortAddr(r.address))}</div>` : ''}</td>
        <td class="num">${r.profit == null ? '–' : usd(r.profit)}</td>
        <td>${r.verdict ? `${verdictChip(r.verdict)} <span class="note">checked ${esc(ago(r.verdict.analysed_at))}</span>` : '<span class="note">Not checked yet. Open it to check.</span>'}</td></tr>`).join('')}</tbody></table></div>
      <p class="note" style="margin:12px 0 0">Real Polymarket data, refreshed every ${Math.round((board.refresh_every_s || 1800) / 60)} minutes. Verdicts appear once someone has opened a wallet: working one out downloads its whole trade history, so it isn't done for every row in advance.</p>`;
    $$('tr.clickable', lbBody).forEach((tr) => tr.addEventListener('click', (e) => { if (e.target.closest('a')) return; location.hash = `#/wallet/${encodeURIComponent(tr.dataset.addr)}`; }));
  };
  const loadBoard = async (force = false) => {
    refreshBtn.disabled = true;
    if (force) refreshBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span> Refreshing';
    try { board = force ? await post('/api/leaderboard/refresh', {}) : await get('/api/leaderboard'); paintBoard(); } catch (e) {
      if (api.stale()) return;
      if (!board) { lbBody.innerHTML = errorState(e.message); lbBody.querySelector('[data-retry]').addEventListener('click', () => loadBoard()); }
    } finally { if (!api.stale()) { refreshBtn.disabled = false; refreshBtn.textContent = 'Refresh'; } }
  };
  refreshBtn.addEventListener('click', () => loadBoard(true));
  // While the page is open: relabel "x min ago" every minute; re-ask the server every 5 min (it only goes
  // to Polymarket when its saved list is older than 30 min).
  let tick = 0;
  const timer = setInterval(() => {
    if (api.stale()) { clearInterval(timer); return; }
    tick += 1;
    if (tick % 5 === 0) loadBoard(); else paintBoard();
  }, 60000);

  // ---------------- search box: address -> report card, anything else -> agent ----------------
  const log = $('#log', main), q = $('#q', main), go = $('#go', main), err = $('#q-err', main);
  const paintLog = () => {
    log.innerHTML = history.slice().reverse().map((h) => `<div class="answer">
      <p class="note" style="margin:0">You asked</p><p style="font-weight:600;margin:4px 0 12px">${esc(h.q)}</p>
      ${h.pending ? '<p><span class="spinner" aria-hidden="true"></span> Working… (a real wallet can take 30 s)</p>' : ''}
      ${h.err ? `<p role="alert" class="chip chip-err" style="white-space:normal">${esc(h.err)}</p>` : ''}
      ${(h.tool_calls || []).length ? `<p class="note" style="margin:0 0 4px">What the agent ran (all logged)</p><ul class="checks">${h.tool_calls.map((c) => `<li><span class="pill ${c.ok ? 'pass' : 'fail'}">${c.ok ? 'OK' : 'ERR'}</span><span>${esc(c.tool.replace(/_/g, ' '))}<span class="mono tech-only"> (${esc(Object.entries(c.args || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', '))})</span></span></li>`).join('')}</ul>` : ''}
      ${h.answer ? `<p class="note" style="margin:12px 0 4px">Agent</p><p style="white-space:pre-wrap;margin:0">${esc(h.answer)}</p>` : ''}
      ${h.fallback ? '<p class="note">The model\'s own answer failed the checks, so this answer is built directly from the tool results.</p>' : ''}
    </div>`).join('');
  };
  const ask = async (text) => {
    if (!text.trim() || go.disabled) return;
    const h = { q: text.trim(), pending: true };
    history.push(h); paintLog(); go.disabled = true; q.value = '';
    try { Object.assign(h, await post('/api/agent', { question: h.q })); } catch (e) { h.err = e.message; }
    h.pending = false; go.disabled = false; if (!api.stale()) paintLog();
  };
  const submit = (raw) => {
    const t = raw.trim(); err.hidden = true;
    if (!t) return;
    if (ADDR.test(t) || DEMO.test(t)) { location.hash = `#/wallet/${encodeURIComponent(DEMO.test(t) ? t : t.toLowerCase())}`; return; }
    if (/^0x\S*$/i.test(t)) { err.hidden = false; err.textContent = 'That looks like an address but isn’t one: expected 0x followed by 40 hexadecimal characters.'; return; }
    if (!live) { err.hidden = false; err.textContent = 'Questions need the agent, which needs a Gemini key. Wallet addresses still work without it.'; return; }
    ask(t);
  };
  $('#ask', main).addEventListener('submit', (e) => { e.preventDefault(); submit(q.value); });
  $$('[data-ex]', main).forEach((b) => b.addEventListener('click', () => ask(EXAMPLES[Number(b.dataset.ex)])));
  paintLog();
  const pre = api.params.get('ask');           // #/?ask=... (or old #/agent?ask=...) runs a question: handy for demos
  if (pre && live && !history.some((h) => h.q === pre)) ask(pre);

  await loadBoard();
}
