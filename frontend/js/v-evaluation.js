import { get } from './api.js';
import { esc, pct, spct, fmtTs, delayLabel, skeleton, errorState, emptyState } from './util.js';
import { powerChart } from './charts.js';

const rate = (m) => (m ? `<strong>${pct(m.rate, 1)}</strong> <span class="muted">(95% CI ${pct(m.ci_low, 1)}–${pct(m.ci_high, 1)}; ${m.k}/${m.n})</span>` : '–');
const CODES = ['SKILLED_COPYABLE', 'SKILLED_NOT_COPYABLE', 'CANT_TELL', 'PROBABLY_LUCK'];
const CODE_LABEL = { SKILLED_COPYABLE: 'Skilled and copyable', SKILLED_NOT_COPYABLE: 'Skilled but not copyable', CANT_TELL: "Can't tell yet", PROBABLY_LUCK: 'Probably luck' };
const TYPE_LABEL = { skilled_slow: 'Skilled (copyable)', skilled_fast: 'Skilled, price moves in minutes', lucky: '#1–10 of 1,000 coin-flippers', farmer95: '95c farmer', clustered: 'Cluster trap' };
const GOOD = { skilled_slow: ['SKILLED_COPYABLE'], skilled_fast: ['SKILLED_NOT_COPYABLE'], lucky: ['PROBABLY_LUCK', 'CANT_TELL'], farmer95: ['PROBABLY_LUCK', 'CANT_TELL'], clustered: ['CANT_TELL', 'PROBABLY_LUCK'] };

export async function render(main, api) {   // rendered inside Under the hood
  main.innerHTML = `<section class="panel" aria-labelledby="ht-h"><h2 id="ht-h">How we tested it</h2>
    <p>Three tests. Think of each as an exam: someone writes it (makes the data) and the judges sit it. Our agent never saw any of this data while it was being built, and its rules were frozen before the tests ran. Every number has a 95% interval.</p>
    <div class="table-wrap"><table><caption class="sr-only">The three tests</caption><thead><tr><th scope="col">Test</th><th scope="col">Who made the data</th><th scope="col">Who was judged</th><th scope="col">What it shows</th></tr></thead><tbody>
      <tr><td><a href="#/hood/tests" data-jump="t1">1 · Planted traders</a></td><td>Diego's generator: fake traders with known skill or luck</td><td>Our agent and two naive rules</td><td>Can it tell skill from luck when we know the answer?</td></tr>
      <tr><td><a href="#/hood/tests" data-jump="t2">2 · A second, independent batch</a></td><td>Joyce's generator: 1,003 fake traders, built separately</td><td>Our agent, Joyce's earlier engine, naive rules</td><td>Does it still work on someone else's fake data?</td></tr>
      <tr><td><a href="#/hood/tests" data-jump="t3">3 · Real Polymarket</a></td><td>Real wallets and real prices</td><td>Copying the top 10 vs copying only what our agent approves</td><td>Would it have helped with real money?</td></tr>
    </tbody></table></div>
    <p class="note" style="margin:8px 0 0"><strong>Edge</strong> means how much more often a trader wins than the price implies. A 10c edge: buying at 40c and winning 50% of the time instead of 40%.</p></section>
    <div id="ev-body" style="margin-top:24px">${skeleton(6)}</div>`;
  let ev;
  try { ev = await get('/api/evaluation'); } catch (e) {
    if (api.stale()) return; main.querySelector('.panel').outerHTML = errorState(e.message); main.querySelector('[data-retry]').addEventListener('click', api.rerun); return;
  }
  if (api.stale()) return;
  const p = main.querySelector('#ev-body .panel');
  const pl = ev?.planted, wf = ev?.walkforward, big = ev?.planted_large;
  if (!pl && !wf && !big) { p.outerHTML = emptyState('No evaluation results', 'The backend has not produced data/evaluation.json yet.'); return; }
  let html = '';
  if (pl) {
    const agent = Object.fromEntries((pl.metrics || []).map((m) => [m.key, m]));
    html += `<section class="panel" aria-labelledby="pm-h" id="t1"><div class="row between"><h3 id="pm-h">Test 1 · Planted traders: how the agent did</h3><span class="chip chip-syn">${esc(pl.label || 'Synthetic')}</span></div>
      <p class="note">${pl.n_wallets} wallets, ${esc(pl.batch || '')} batch (seed ${esc((pl.test_seeds || []).join(', '))}). Thresholds were set on dev seed ${esc((pl.dev_seeds || []).join(', '))}, then frozen.</p>
      <div class="table-wrap"><table><caption class="sr-only">Agent metrics with Wilson 95% intervals</caption><thead><tr><th scope="col">Metric</th><th scope="col">Rate (95% CI)</th></tr></thead><tbody>${(pl.metrics || []).map((m) => `<tr><td>${esc(m.name)}</td><td>${rate(m)}</td></tr>`).join('')}</tbody></table></div></section>`;
    if ((pl.baselines || []).length) {
      html += `<section class="panel" aria-labelledby="bl-h"><h3 id="bl-h">Test 1 · Versus naive rules, same wallets</h3><p class="note">The naive rules pick the lucky wallets; our agent picked none of them.</p>
      <div class="table-wrap"><table><caption class="sr-only">Agent versus baselines</caption><thead><tr><th scope="col">Judge</th><th scope="col">False alarms (no-skill called skilled; lower is better)</th><th scope="col">Detection (skilled found; higher is better)</th></tr></thead><tbody>
      <tr><td><strong>This agent</strong></td><td>${rate(agent.false_alarm)}</td><td>${rate(agent.detection)}</td></tr>
      ${pl.baselines.map((b) => `<tr><td>${esc(b.name)}</td><td>${rate(b.false_alarm)}</td><td>${rate(b.detection)}</td></tr>`).join('')}</tbody></table></div></section>`;
    }
    html += `<section class="panel" aria-labelledby="pw-h"><div class="row between"><h3 id="pw-h">Test 1 · How big an edge it needs to notice</h3><span class="chip chip-syn">Synthetic data</span></div><p class="note">How often a planted skilled trader was found, by the size of their true edge. Small edges are hard to separate from the luckiest of 1,000 no-skill traders: we would rather miss a skilled trader than tell a student to copy a lucky one.</p>${powerChart(pl.power_curve)}</section>`;
    const conf = pl.confusion || {};
    const types = Object.keys(conf);
    html += `<section class="panel" aria-labelledby="cf-h"><div class="row between"><h3 id="cf-h">Test 1 · Every verdict, by planted type</h3><span class="chip chip-syn">Synthetic data</span></div><p class="note">Rows: planted type. Columns: verdict given. Outlined cells are the acceptable verdicts.</p>
      <div class="table-wrap"><table><caption class="sr-only">Planted type by verdict</caption><thead><tr><th scope="col">Planted type</th>${CODES.map((c) => `<th class="num" scope="col">${esc(CODE_LABEL[c])}</th>`).join('')}</tr></thead><tbody>
      ${types.map((t) => { const tot = CODES.reduce((a, c) => a + (conf[t][c] || 0), 0) || 1; return `<tr><th scope="row" style="text-transform:none;letter-spacing:0;font-size:14px;color:var(--ink)">${esc(TYPE_LABEL[t] || t)}</th>${CODES.map((c) => { const v = conf[t][c] || 0, good = (GOOD[t] || []).includes(c); return `<td class="num" style="background:rgba(62,108,158,${(v / tot * 0.5).toFixed(2)});${good ? 'outline:2px solid #0F766E;outline-offset:-2px;' : ''}font-weight:${good ? 700 : 500}">${v}</td>`; }).join('')}</tr>`; }).join('')}</tbody></table></div></section>`;
    if (pl.errors) html += `<section class="panel" aria-labelledby="er-h"><div class="row between"><h3 id="er-h">Test 1 · Every error, shown as plainly as the wins (${pl.errors.length} of ${pl.n_wallets} wallets)</h3><span class="chip chip-syn">Synthetic data</span></div>
      ${pl.errors.length ? `<div class="table-wrap"><table><thead><tr><th scope="col">Wallet</th><th scope="col">Planted type</th><th class="num" scope="col">True edge</th><th scope="col">Agent said</th><th class="num" scope="col">Win rate</th></tr></thead><tbody>${pl.errors.map((e) => `<tr><td class="mono">${esc(e.wallet)}</td><td>${esc(TYPE_LABEL[e.planted] || e.planted)}</td><td class="num">${e.true_edge ? spct(e.true_edge, 0) : '–'}</td><td>${esc(e.verdict)}</td><td class="num">${pct(e.win_rate)}</td></tr>`).join('')}</tbody></table></div>` : '<p>No errors.</p>'}</section>`;
    if ((pl.notes || []).length) html += `<section class="panel"><h3>Stated limits</h3><ul>${pl.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul></section>`;
  }
  if (big) {
    const types = Object.entries(big.types || {}).map(([t, n]) => `${esc(t)} ${n}`).join(', ');
    const eng = (big.judges || []).find((j) => j.key === 'engine'), proto = (big.judges || []).find((j) => j.key === 'prototype');
    html += `<section class="panel" aria-labelledby="lg-h" id="t2"><div class="row between"><h3 id="lg-h">Test 2 · ${big.n_wallets.toLocaleString('en-GB')} wallets from Joyce's independent generator</h3><span class="chip chip-syn">${esc(big.label)}</span></div>
      <p>Our engine never saw this data and wasn't tuned on it. Joyce's earlier prototype engine was built alongside this generator, so it has home advantage, like a student sitting an exam they wrote. Its results are shown for comparison, not as a target.</p>
      <p class="note">Planted types: ${types}. Same frozen engine<span class="tech-only"> (freeze hash <span class="mono">${esc(big.freeze_hash)}</span>)</span>.</p>
      ${eng ? `<div class="metric-grid"><div class="metric"><span>No-skill wallets recommended for copying</span><b>${eng.no_skill_copied.k} of ${eng.no_skill_copied.n}</b><span>95% CI ${pct(eng.no_skill_copied.ci_low, 1)}–${pct(eng.no_skill_copied.ci_high, 1)}</span></div><div class="metric"><span>Of its 'copy' calls, truly skilled &amp; copyable</span><b>${pct(eng.precision.rate)}</b><span>${eng.precision.k}/${eng.precision.n}</span></div>${proto ? `<div class="metric"><span>Prototype engine, same measure</span><b>${pct(proto.precision.rate)}</b><span>${proto.precision.k}/${proto.precision.n}</span></div>` : ''}</div>` : ''}
      <div class="table-wrap"><table><caption class="sr-only">Judges on the large batch</caption><thead><tr><th scope="col">Judge</th><th scope="col">Recommends copying a no-skill wallet (lower is better)</th><th scope="col">Of its 'copy' calls, truly skilled &amp; copyable (higher is better)</th><th class="num" scope="col">'Copy' calls</th></tr></thead><tbody>
      ${(big.judges || []).map((j) => `<tr><td>${j.key === 'engine' ? '<strong>' + esc(j.name) + '</strong>' : esc(j.name)}</td><td>${rate(j.no_skill_copied)}</td><td>${rate(j.precision)}</td><td class="num">${j.copy_calls}</td></tr>`).join('')}</tbody></table></div>
      ${Object.keys(big.detail || {}).length ? `<div class="table-wrap"><table><caption class="sr-only">Engine detail</caption><thead><tr><th scope="col">Metric</th>${Object.keys(big.detail).map((k) => `<th scope="col">${esc(k === 'engine' ? 'This engine' : 'Prototype engine')}</th>`).join('')}</tr></thead><tbody>
      ${(big.detail.engine || []).map((m, i) => `<tr><td>${esc(m.name)}</td>${Object.keys(big.detail).map((k) => `<td>${rate(big.detail[k][i])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : ''}
      ${big.power_curve?.engine ? `<div class="table-wrap"><table><caption class="sr-only">Detection by true edge</caption><thead><tr><th scope="col">True edge</th>${Object.keys(big.power_curve).map((k) => `<th scope="col">${esc(k === 'engine' ? 'This engine' : 'Prototype engine')}: called 'Skilled and copyable'</th>`).join('')}</tr></thead><tbody>
      ${big.power_curve.engine.map((b, i) => `<tr><td>${esc(b.edge_bin)}</td>${Object.keys(big.power_curve).map((k) => { const x = big.power_curve[k][i]; return `<td>${rate({ rate: x.rate, ci_low: x.lo, ci_high: x.hi, k: x.k, n: x.n })}</td>`; }).join('')}</tr>`).join('')}</tbody></table></div>` : ''}
      <ul>${(big.notes || []).map((n) => `<li>${esc(n)}</li>`).join('')}</ul></section>`;
  }
  if (wf) {
    const d = wf.diff || {};
    html += `<section class="panel" aria-labelledby="wf-h" id="t3"><div class="row between"><h3 id="wf-h">Test 3 · Real Polymarket: copy the top 10, or copy only what our agent approves?</h3><span class="chip ${wf.real ? 'good' : 'warn'}">${wf.real ? 'Real data' : 'Synthetic'}</span></div>
      <p><strong>${esc(wf.label)}</strong></p>
      <p>We rewound to the cut-off date and judged each leaderboard wallet using only its history before then. Then two pretend followers copied forward, each £10 copy placed an hour after the leader at the real price, paying spread and fees. <strong>Follower A</strong> copied the top 10. <strong>Follower B</strong> copied only wallets our agent approved.</p>
      <div class="metric-grid"><div class="metric"><span>Follower A: average return per copy</span><b>${spct(wf.top10?.return)}</b><span>${wf.top10?.n_positions} copies${wf.top10?.ci_low != null ? ` · 95% CI ${spct(wf.top10.ci_low)} to ${spct(wf.top10.ci_high)}` : ''}</span></div><div class="metric"><span>Follower B: agent-approved only</span><b>${wf.agent?.holds_cash ? 'held cash' : spct(wf.agent?.return)}</b><span>${wf.agent?.n_positions} copies</span></div><div class="metric"><span>B minus A, per copy</span><b>${spct(d.mean)}</b><span>95% CI ${spct(d.ci_low)} to ${spct(d.ci_high)}</span></div></div>
      <p class="note">Cut-off ${esc(fmtTs(wf.cutoff_ts))} · ${wf.n_wallets} wallets · ${wf.n_positions_after} positions after the cut-off · ${wf.n_agent_approved} agent-approved wallets · copy delay ${esc(delayLabel(wf.copy_delay_s))}, with spread and fees.</p>
      ${d.ci_low <= 0 && d.ci_high >= 0 ? '<p class="chip warn" style="white-space:normal">The interval includes zero: this is not evidence of an advantage.</p>' : ''}
      <ul>${(wf.notes || []).map((n) => `<li>${esc(n)}</li>`).join('')}</ul></section>`;
  }
  p.outerHTML = html;
  main.querySelectorAll('[data-jump]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); main.querySelector(`#${a.dataset.jump}`)?.scrollIntoView({ block: 'start' }); }));
}
