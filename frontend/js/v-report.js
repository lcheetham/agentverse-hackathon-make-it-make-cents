import { get } from './api.js';
import { esc, $, $$, shortAddr, usd, gbp, pct, spct, cents, cls, signedUsd, signedGbp, verdictInfo, synTag, skeleton, errorState, delayLabel } from './util.js';
import { ciChart, luckBars, delayChart, categoryChart, equityChart } from './charts.js';

const FLAG_NAMES = { WELL_TIMED: 'Well-timed late entries', NEAR_CERTAIN: 'Near-certain buying', CONCENTRATION: 'Concentration', INPUT_CHECK: 'Input check', COARSE_GROUPING: 'Grouping' };
const PRACTICE = ['0xDEMO-messy-skilled', '0xDEMO-fast-mover', '0xDEMO-perfect-25-0']; // the traders Paper trading replays
const DEFAULT_DELAYS = [{ s: 0, label: '0' }, { s: 300, label: '5 min' }, { s: 3600, label: '1 h' }, { s: 86400, label: '1 day' }];
const frac = (x) => (typeof x === 'number' && x > 1 ? x / 100 : x); // tolerate percent-valued shares

export async function render(main, api) {
  const addr = api.arg;
  if (!addr) { location.hash = '#/'; return; }
  const delays = api.meta?.delays?.length ? api.meta.delays : DEFAULT_DELAYS;
  const nParam = Number(api.params.get('n'));
  const st = { delay: Number(api.params.get('delay') ?? 3600), n: 1000, nCustom: Number.isInteger(nParam) && nParam >= 1 ? nParam : null, luckCustom: null,
    busy: false, report: null, hl: new Set(), sentence: -1, only: false, open: new Set(['w', 'f', 'ww', 'l', 'd']) };
  if (!delays.some((d) => d.s === st.delay)) st.delay = 3600;

  main.innerHTML = `<section class="hero" style="padding-bottom:16px"><p><a href="#/">← Home</a></p><h1>Report card</h1><p class="mono" style="word-break:break-all;margin-top:8px">${esc(addr)}</p></section>
    <div class="panel tight controls" role="group" aria-label="Report settings">
      <div class="row between" style="align-items:flex-start;gap:24px">
        <div><h3 id="dl">Copy delay</h3><div class="seg" role="group" aria-labelledby="dl">${delays.map((d) => `<button type="button" class="btn small" data-delay="${d.s}">${esc(d.label === '0' ? 'No delay' : d.label)}</button>`).join('')}</div></div>
        <form id="nform" class="tech-only" novalidate><h3><label for="nval">Leaderboard size N</label></h3><div class="row" style="gap:8px;flex-wrap:nowrap">
          <input id="nval" type="number" min="1" max="1000000" step="1" inputmode="numeric" style="width:150px" placeholder="e.g. 5000" aria-describedby="nnote">
          <button class="btn small" type="submit">Apply</button></div></form>
      </div>
      <p class="note" style="margin:8px 0 0">Copy delay: how late you would have copied after the leader. It changes the copy-delay chart and the £200 simulation.</p>
      <p class="note tech-only" id="nnote" style="margin:4px 0 0">N: how many traders the leaderboard picked this one from. It changes the luck score.</p>
      <p class="note" style="margin:4px 0 0">The verdict always uses the frozen 1 h delay<span class="tech-only"> and its own N</span>.</p>
      <p role="alert" class="chip chip-err" id="n-err" style="display:none;white-space:normal;margin-top:8px"></p>
    </div>
    <div id="rc-body" class="stack" style="margin-top:24px" aria-live="polite">${skeleton(5)}</div>`;
  const body = $('#rc-body', main);
  const nErr = $('#n-err', main);
  if (st.nCustom) $('#nval', main).value = String(st.nCustom);

  const setUrl = () => history.replaceState(null, '', `${location.pathname}${location.search}#/wallet/${encodeURIComponent(addr)}?delay=${st.delay}${st.nCustom ? `&n=${st.nCustom}` : ''}`);
  const syncControls = () => {
    $$('[data-delay]', main).forEach((b) => { b.setAttribute('aria-pressed', String(Number(b.dataset.delay) === st.delay)); b.disabled = st.busy || !st.report; });
    $$('#nform input, #nform button', main).forEach((el) => { el.disabled = st.busy || !st.report; });
  };
  // The card is fetched once: it carries the £200 simulation for every delay, so switching delay needs no request.
  const load = async () => {
    st.busy = true; syncControls(); body.classList.add('busy'); body.setAttribute('aria-busy', 'true');
    if (!st.report) body.innerHTML = (addr.startsWith('0xDEMO') ? '' : '<p class="note"><span class="spinner" aria-hidden="true"></span> Downloading this wallet\'s trades from Polymarket and checking them. The first time takes 15–30 seconds; after that it\'s reused for 30 minutes.</p>') + skeleton(5);
    try {
      const r = await get(`/api/wallets/${encodeURIComponent(addr)}/report?delay=${st.delay}`);
      st.n = r.luck.verdict_n || 1000;
      if (api.stale()) return;
      st.report = r; st.hl = new Set(); st.sentence = -1; st.only = false;
      draw();
    } catch (e) {
      if (api.stale()) return;
      body.innerHTML = errorState(e.message);
      body.querySelector('[data-retry]').addEventListener('click', load);
    } finally { st.busy = false; body.classList.remove('busy'); body.removeAttribute('aria-busy'); syncControls(); }
    if (st.report && st.nCustom && !st.luckCustom) applyN(st.nCustom, false);
  };
  main.addEventListener('click', (e) => {
    const d = e.target.closest('[data-delay]');
    if (!d || !st.report) return;
    st.delay = Number(d.dataset.delay);
    st.report.sim_200 = st.report.sims?.[String(st.delay)] ?? st.report.sim_200;
    setUrl(); syncControls();
    repaint('d', delayBody); repaint('s', simBody);
  });

  // Luck(N) for the user's N comes from the engine (one small request, no re-simulation).
  async function applyN(n, open = true) {
    nErr.style.display = 'none';
    if (!Number.isInteger(n) || n < 1 || n > 1000000) { nErr.textContent = 'N must be a whole number from 1 to 1,000,000.'; nErr.style.display = 'inline-block'; return; }
    try {
      const res = await get(`/api/wallets/${encodeURIComponent(addr)}/luck?n=${n}`);
      if (api.stale()) return;
      st.nCustom = n; st.luckCustom = res; setUrl();
      repaint('l', luckBody);
      if (open) openFold('l');
    } catch (err) { if (api.stale()) return; nErr.textContent = err.message; nErr.style.display = 'inline-block'; }
  }
  $('#nform', main).addEventListener('submit', (e) => { e.preventDefault(); const v = $('#nval', main).value.trim(); applyN(v === '' ? NaN : Number(v)); });

  function repaint(id, fn) { const b = $(`[data-fold="${id}"] .fold-body`, body); if (b && st.report) b.innerHTML = fn(st.report); }
  const delayBody = (r) => `<p class="note">Edge a follower would have kept after spread and fees if they copied this much later. Shaded band: 95% interval. Highlighted: ${esc(st.delay === 0 ? 'no delay' : delayLabel(st.delay))}.</p>
      ${delayChart(r.delay_curve, st.delay)}`;
  const simBody = (r) => `<p style="font-size:32px;font-weight:600;margin:0">${gbp(r.sim_200.start)} → ${gbp(r.sim_200.end)}</p>
      ${equityChart(r.sim_200)}
      <p class="note" style="margin-top:8px"><strong>Historical simulation</strong> · ${esc(st.delay === 0 ? 'with no copy delay' : `after ${delayLabel(st.delay)} delay`)}, spread and fees · ${r.data_mode === 'synthetic' ? 'synthetic data' : esc(r.data_mode + ' data')}. Not a forecast. ${r.sim_200.n_copied} positions copied.</p>`;
  const oneIn = (q) => (q >= 0.5 ? 'more often than not' : `about 1 time in ${Math.max(2, Math.round(1 / q)).toLocaleString('en-GB')}`);
  const luckBody = (r) => `<p class="note">How easy this profit is to match by chance. Take N traders with no skill holding exactly these bets, each won or lost at the market's own odds: how likely is it that at least one does as well? <strong>High means the record is no evidence of skill; under 5% points to skill.</strong></p>
        ${typeof r.luck.q_single === 'number' && r.luck.q_single > 0 ? `<p style="margin:0 0 12px">One no-skill copy matched this profit <strong>${r.luck.q_single_upper ? 'at most ' : ''}${esc(oneIn(r.luck.q_single))}</strong> (${r.luck.q_single_upper ? '&lt;' : ''}${pct(r.luck.q_single, r.luck.q_single < 0.01 ? 2 : 1)}). The scores below ask the same question for the best of N such traders, which is why they climb so fast.</p>` : ''}
        ${luckBars(r.luck, st.n, st.luckCustom)}
        ${r.luck.coarse_grouping ? '<p class="chip warn" style="white-space:normal;margin-top:12px">Grouping may be too coarse for this wallet (see Flags): if so, this score is overstated.</p>' : ''}
        <p class="note" style="margin-top:8px">Most sceptical of the engine's no-skill twins (fair odds, related bets drawn together, multi-candidate markets with one winner). Covers ${pct(frac(r.luck.coverage))} of positions: held to resolution only; positions sold early are excluded.${(r.luck.by_n.concat(st.luckCustom || [])).some((x) => x.upper_bound) ? ' “<” marks an upper bound: too few twins beat this trader to estimate the score more precisely.' : ''}</p>`;

  function setHighlight(ids, sentenceIdx = -1, scroll = false) {
    st.hl = new Set(ids); st.sentence = sentenceIdx;
    paintHighlight();
    if (scroll) { openFold('t'); const first = $('tr.hl', body); first?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' }); }
  }
  function paintHighlight() {
    const r = st.report;
    $$('.sent', body).forEach((b) => b.setAttribute('aria-pressed', String(Number(b.dataset.i) === st.sentence)));
    $$('tr[data-pid]', body).forEach((tr) => { const on = st.hl.has(tr.dataset.pid); tr.classList.toggle('hl', on); tr.hidden = st.only && st.hl.size > 0 && !on; });
    const s = st.sentence >= 0 ? r.report.sentences[st.sentence] : null;
    const panel = $('#cite', body);
    if (!s) {
      panel.innerHTML = st.hl.size ? `<p class="note" style="margin:0">${st.hl.size} trade${st.hl.size === 1 ? '' : 's'} highlighted in the trades table.</p>` : '<p class="note" style="margin:0">Select a sentence to see the numbers and trades behind it.</p>';
    } else {
      const facts = (s.fact_ids || []).map((id) => r.facts?.[id]).filter(Boolean);
      const pids = (s.position_ids || []).filter((id) => r.positions.some((p) => p.id === id));
      panel.innerHTML = `<h3>Behind this sentence</h3>${facts.length ? `<ul>${facts.map((f) => `<li><span>${esc(f.label)}</span><strong>${esc(f.display)}</strong></li>`).join('')}</ul>` : '<p class="note">No headline numbers cited.</p>'}
        ${pids.length ? `<button class="btn small" type="button" data-jump>Show ${pids.length} cited trade${pids.length === 1 ? '' : 's'} in the table</button>` : '<p class="note" style="margin:0">No specific trades cited.</p>'}`;
      $('[data-jump]', panel)?.addEventListener('click', () => { setHighlight(pids, st.sentence, true); });
    }
    const cb = $('#only', body); if (cb) { cb.closest('label').hidden = st.hl.size === 0; cb.checked = st.only; }
  }

  // Collapsible panels: the written report starts open, everything else starts closed. Open/closed state survives redraws (delay changes).
  const fold = (id, title, inner, tag = '') => `<details class="panel fold" data-fold="${id}"${st.open.has(id) ? ' open' : ''}>
      <summary><h3 id="${id}-h">${title}</h3><span class="fold-tag">${tag}</span></summary><div class="fold-body">${inner}</div></details>`;
  const openFold = (id) => { const d = $(`[data-fold="${id}"]`, body); if (d && !d.open) d.open = true; };

  function draw() {
    const r = st.report, V = verdictInfo(r.verdict), sm = r.summary, mode = r.data_mode;
    const clusterLabel = Object.fromEntries((r.clusters || []).map((c) => [c.id, c.label]));
    const conc = r.concentration;
    const sentences = r.report.sentences.map((s, i) => `<button type="button" class="sent" data-i="${i}" aria-pressed="false">${esc(s.text)}</button>`).join(' ');
    const chk = r.report.check;
    const syn = synTag(mode);
    const nc = r.positions.length ? r.positions.filter((p) => p.avg_entry >= 0.93).length / r.positions.length : 0;
    body.innerHTML = `
    <section class="panel verdict ${V.v}" aria-labelledby="v-h">
      <h3 id="v-h">Verdict</h3><h2>${esc(V.label)}</h2>
      <ul class="deciding">${(r.verdict.deciding || []).map((d) => `<li>${esc(d.text)}</li>`).join('')}</ul>
      <dl class="kv"><div><dt>Profit</dt><dd>${usd(sm.profit)}</dd></div><div><dt>Record</dt><dd>${esc(sm.record)}</dd></div><div><dt>Win rate</dt><dd>${pct(sm.win_rate)}</dd></div><div><dt>Positions</dt><dd>${sm.n_positions}</dd></div><div><dt>Event clusters</dt><dd>${sm.n_clusters}</dd></div></dl>
      <p class="note" style="margin:16px 0 0">Set by explicit thresholds in code, never by the language model. ${syn}${r.demo_label ? ` · Demo wallet: ${esc(r.demo_label)}` : ''}${mode !== 'synthetic' && r.analysed_at ? ` · Analysed ${esc(new Date(r.analysed_at * 1000).toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short' }))}, reused for 30 min` : ''}</p>
      <p class="note tech-only mono" style="margin:4px 0 0">Freeze hash ${esc(r.freeze_hash || '?')} · verdict N ${esc(r.luck?.verdict_n ?? '?')}</p>
      ${r.data_note ? `<p class="note" style="margin:8px 0 0">${esc(r.data_note)}</p>` : ''}
    </section>

    ${(r.what_would_change || []).length ? fold('ww', 'What would change this verdict', `<ul>${r.what_would_change.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>
      <p class="note" style="margin:0">Computed by code from the same numbers as the verdict.</p>`) : ''}

    ${fold('w', 'Written report', `<p class="sentences">${sentences}</p>
      <div class="cite-panel" id="cite" aria-live="polite"></div>
      <div class="check-line"><span>Written by <strong>${esc(r.report.writer)}</strong></span><span class="chip ${chk.passed ? 'good' : 'bad'}">Number check: ${chk.passed ? 'passed' : 'failed'}</span>${chk.passed ? '' : `<span>Unmatched: ${esc((chk.unmatched || []).join(', '))}</span>`}</div>`)}

    ${fold('f', 'Flags needing human review', `<p><strong>${pct(nc)}</strong> of positions were bought at 93c or above.</p>
      ${(r.flags || []).length ? r.flags.map((f, i) => `<div class="flag ${f.severity === 'review' ? '' : 'info'}"><div class="flag-head">${f.severity === 'review' ? 'Needs human review' : 'Note'}${FLAG_NAMES[f.code] ? ` · ${FLAG_NAMES[f.code]}` : ''}<span class="tech-only mono" style="font-weight:400"> (${esc(f.code)})</span></div><p style="margin:6px 0 8px">${esc(f.text)}</p>${(f.position_ids || []).length ? `<button class="btn small" type="button" data-flag="${i}">Highlight ${f.position_ids.length} trade${f.position_ids.length === 1 ? '' : 's'}</button>` : ''}</div>`).join('') : '<p class="muted">No flags raised.</p>'}
      <p class="note" style="margin:0">Flags describe trading patterns in the data, worked out by code. They are not evidence of wrongdoing.</p>`,
      (r.flags || []).some((f) => f.severity === 'review') ? '<span class="chip warn">Needs review</span>' : (r.flags || []).length ? `<span class="chip">${r.flags.length}</span>` : '')}

    ${fold('k', 'Where the profit came from', categoryChart(r.categories || []) || '<p class="note" style="margin:0">No categories.</p>', syn)}

    ${fold('d', 'Copy-delay decay', delayBody(r), syn)}

    <div class="grid2 folds">
      ${fold('e', 'Edge per position', `<p style="font-size:32px;font-weight:600;margin:0">${spct(r.edge.mean)} <span style="font-size:16px;font-weight:500" class="muted">95% CI ${spct(r.edge.ci_low)} to ${spct(r.edge.ci_high)}</span></p>
        ${ciChart(r.edge)}
        <p class="note" style="margin-top:8px">From <strong>${r.edge.n_clusters}</strong> independent event clusters (${r.edge.n_positions} positions). Bets on the same event count as one draw.</p>`, syn)}
      ${fold('l', 'Luck score', luckBody(r), syn)}
    </div>

    ${fold('c', 'Concentration', `<div class="metric-grid"><div class="metric"><span>Profit, total</span><b>${usd(conc.profit_total)}</b></div><div class="metric"><span>Without biggest cluster</span><b>${usd(conc.profit_without_top)}</b></div></div>
        <p>Biggest event cluster: <strong>${esc(conc.top_cluster_label || conc.top_cluster_id)}</strong>, ${pct(conc.top_share_of_profit)} of profit. Edge without it: <strong>${spct(conc.edge_without_top)}</strong>.</p>`, syn)}

    ${fold('s', 'What £200 copying them would have become', simBody(r), syn)}

    ${(r.input_checks || []).length ? fold('i', 'Input checks (bad or manipulative data)', `<ul class="checks">${r.input_checks.map((c) => `<li><span class="pill ${c.ok ? 'pass' : 'fail'}">${c.ok ? 'PASS' : 'FAIL'}</span><span><strong>${esc(c.check)}</strong>: ${esc(c.detail)}${c.severe ? ' · severe: the agent holds for a human' : ''}</span></li>`).join('')}</ul>`,
      r.input_checks.some((c) => !c.ok) ? '<span class="chip bad">Failed</span>' : '') : ''}

    ${fold('t', `Trades (${r.positions.length})`, `<label class="row" hidden style="margin-bottom:8px"><input type="checkbox" id="only"> Show only highlighted trades</label>
      <div class="table-wrap"><table id="trades"><caption class="sr-only">Positions behind this report card</caption><thead><tr><th scope="col">Market</th><th scope="col">Event cluster</th><th scope="col">Category</th><th scope="col">Token</th><th class="num" scope="col">Entry → exit</th><th scope="col">Exit type</th><th class="num" scope="col">P&amp;L</th><th class="num" scope="col">Return</th></tr></thead>
      <tbody>${r.positions.map((p) => `<tr data-pid="${esc(p.id)}"><td>${esc(p.title)}${p.near_certain ? '<span class="tag">near-certain</span>' : ''}</td><td>${esc(clusterLabel[p.cluster_id] || p.cluster_id)}</td><td>${esc(p.category)}</td><td>${esc(p.token)}</td><td class="num">${cents(p.avg_entry)} → ${cents(p.exit_price)}</td><td>${p.held_to_resolution ? 'Held to resolution' : 'Sold early'}</td><td class="num ${cls(p.pnl)}">${signedUsd(p.pnl)}</td><td class="num ${cls(p.ret)}">${spct(p.ret)}</td></tr>`).join('')}</tbody></table></div>`)}

    <div class="row">${PRACTICE.includes(r.wallet) ? `<a class="btn primary" href="#/paper?wallet=${encodeURIComponent(r.wallet)}">Practise copying this trader in Paper trading</a>` : ''}<a class="btn" href="#/">Back to Home</a></div>`;
    $$('details[data-fold]', body).forEach((d) => d.addEventListener('toggle', () => { if (d.open) st.open.add(d.dataset.fold); else st.open.delete(d.dataset.fold); }));
    $$('.sent', body).forEach((b) => b.addEventListener('click', () => {
      const i = Number(b.dataset.i);
      if (st.sentence === i) { setHighlight([], -1); return; }
      setHighlight(r.report.sentences[i].position_ids || [], i);
    }));
    $$('[data-flag]', body).forEach((b) => b.addEventListener('click', () => setHighlight(r.flags[Number(b.dataset.flag)].position_ids, -1, true)));
    $('#only', body).addEventListener('change', (e) => { st.only = e.target.checked; paintHighlight(); });
    paintHighlight();
  }
  syncControls();
  await load();
}
