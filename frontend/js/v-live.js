import { get, post } from './api.js';
import { esc, $, $$, shortAddr, gbp, pct, cents, signedGbp, cls, fmtTs, verdictChip, verdictInfo, skeleton, errorState } from './util.js';
import { tableHtml } from './v-audit.js';
import { equityChart } from './charts.js';

const LIMIT_LABELS = {
  bankroll: (v) => `Paper bankroll: ${gbp(v)}`,
  per_trade_cap_frac: (v, s) => `Per-trade cap: ${pct(v)} of bankroll (${gbp(v * s.bankroll, 2)})`,
  cluster_cap_frac: (v, s) => `Exposure to one event cluster: ${pct(v)} of bankroll (${gbp(v * s.bankroll, 2)})`,
  drawdown_stop_frac: (v) => `Drawdown stop: copying a trader halts after a ${pct(v)} paper drawdown`,
  stale_price_max_move: (v) => `Stale-price limit: skip if price moved more than ${Math.round(v * 100)}c since the leader`,
};
const CONTROL_LABELS = { kill_switch: 'Kill switch', agent_hold: 'Proposer unsure (hold)', per_trade_cap: 'Per-trade cap', verdict_gate: 'Verdict gate', cluster_exposure: 'Event-cluster exposure', drawdown_stop: 'Drawdown stop', stale_price: 'Stale price', cash: 'Paper cash' };

// Module-level so state survives re-renders within a visit; reset on each navigation.
export async function render(main, api) {
  const L = { state: null, audit: [], wallet: api.params.get('wallet') || null, proposal: null, result: null, busy: false, stake: '', override: '', err: null };
  main.innerHTML = `<section class="hero" style="padding-bottom:8px"><div class="row"><h1>Paper trading</h1><span class="chip chip-replay">Practice data</span></div>
    <p class="lede">Practise copying with a pretend £200. The traders here are our planted practice traders, and their bets are replayed from history, not placed in a market. Fixed rules in code propose a copy (no language model is involved on this page), you approve or reject it, and eight risk controls written in code check every copy before it reaches the account.</p></section><div id="live-root">${skeleton(5)}</div>`;
  const root = $('#live-root', main);

  const pendingOf = (s) => (s?.pending || [])[0] || null;
  const loadAll = async () => {
    const [state, audit] = await Promise.all([get('/api/live/state'), get('/api/audit?limit=8&kind=live')]);
    L.state = state; L.audit = audit;
    if (!L.proposal) { const p = pendingOf(state); if (p) setProposal(p); }
    if (!L.wallet || !state.wallets_with_bets.some((w) => w.address === L.wallet)) {
      if (!(L.wallet && state.paused?.includes(L.wallet))) L.wallet = (state.wallets_with_bets.find((w) => w.remaining > 0) || state.wallets_with_bets[0])?.address || null;
    }
  };
  const setProposal = (p) => { L.proposal = p; L.stake = String(p.stake ?? ''); L.override = ''; };
  const refreshAudit = async () => { try { L.audit = await get('/api/audit?limit=8&kind=live'); } catch { /* strip is best-effort */ } };

  async function act(fn) {
    if (L.busy) return;
    const fk = document.activeElement?.dataset?.fk;
    L.busy = true; L.err = null; paint(fk);
    try { await fn(); } catch (e) { if (api.stale()) return; L.err = e.message; }
    if (api.stale()) return;
    await refreshAudit();
    L.busy = false; paint(fk, true);
  }

  function paint(focusKey, scrollResult) {
    if (api.stale()) return;
    const s = L.state, dis = L.busy ? 'disabled' : '';
    const open = (s.ledger || []).filter((l) => l.status !== 'settled'), settled = (s.ledger || []).filter((l) => l.status === 'settled');
    const openStake = open.reduce((a, l) => a + (Number(l.stake) || 0), 0);
    const equityGiven = typeof s.equity === 'number';
    const equity = equityGiven ? s.equity : s.cash + openStake + 0;
    const realised = settled.reduce((a, l) => a + (Number(l.pnl) || 0), 0);
    const pick = s.wallets_with_bets || [];
    const sel = pick.find((w) => w.address === L.wallet);
    const pending = L.proposal;
    const capGbp = s.limits.per_trade_cap_frac * s.bankroll;
    const canNext = !!sel && sel.remaining > 0 && !pending && !L.busy;
    const entryTitle = (l) => l.title || l.bet?.title || l.market || l.id || 'Copy';

    const ledgerRows = (arr, settledView) => arr.length ? `<div class="table-wrap"><table><thead><tr><th scope="col">Bet</th><th class="num" scope="col">Stake</th><th class="num" scope="col">${settledView ? 'P&amp;L' : 'Entry'}</th></tr></thead><tbody>${arr.map((l) => `<tr><td>${esc(entryTitle(l))}<div class="note mono">${esc(shortAddr(l.wallet || ''))}${l.token ? ' · ' + esc(l.token) : ''}</div></td><td class="num">${gbp(Number(l.stake), 2)}</td><td class="num ${settledView ? cls(l.pnl) : ''}">${settledView ? signedGbp(l.pnl) : cents(l.entry_price)}</td></tr>`).join('')}</tbody></table></div>` : `<p class="note">${settledView ? 'Nothing settled yet. Advance the clock after approving copies.' : 'No open copies.'}</p>`;

    const left = `<section class="panel col-portfolio" aria-labelledby="pf-h"><h3 id="pf-h">Paper portfolio</h3>
      <div class="metric-grid"><div class="metric"><span>Bankroll</span><b>${gbp(s.bankroll)}</b></div><div class="metric"><span>Cash</span><b>${gbp(s.cash, 2)}</b></div><div class="metric"><span>Equity</span><b title="${equityGiven ? '' : 'Cash plus open stakes at cost'}">${gbp(equity, 2)}</b></div><div class="metric"><span>Open copies</span><b>${open.length}</b></div><div class="metric"><span>Settled</span><b>${settled.length}</b></div></div>
      ${(s.history || []).length > 1 ? `<h3 style="margin-top:8px">Account value</h3>${equityChart({ start: s.bankroll, end: s.history[s.history.length - 1].value, n_copied: (s.ledger || []).length, curve: s.history }, 'Paper account value', 'Paper account value during this session')}<p class="note" style="margin-top:4px">The line moves when a copy settles. Placing a copy doesn't move it, because open copies count at what you paid.</p>` : ''}
      <p class="note">Replay clock: <strong>${esc(fmtTs(s.clock_ts, true))}</strong>${equityGiven ? '' : ' · equity counts open stakes at cost'}${settled.length ? ` · realised ${signedGbp(realised)}` : ''}</p>
      <h3>Open copies</h3>${ledgerRows(open, false)}<h3 style="margin-top:16px">Settled</h3>${ledgerRows(settled, true)}
      <h3 style="margin-top:16px">Paused traders</h3>${(s.paused || []).length ? `<ul class="list-plain">${s.paused.map((a) => `<li class="row between"><span><span class="mono">${esc(shortAddr(a))}</span> <span class="chip warn">paused: drawdown</span></span><button type="button" class="btn small" data-resume="${esc(a)}" data-fk="resume-${esc(a)}" ${dis}>Re-enable</button></li>`).join('')}</ul>` : '<p class="note">None. A trader is auto-paused after the drawdown stop; a human must re-enable.</p>'}
      <h3 style="margin-top:16px">Risk limits</h3><ul class="list-plain">${Object.entries(s.limits || {}).map(([k, v]) => `<li>${esc((LIMIT_LABELS[k] || ((x) => `${k}: ${x}`))(v, s.limits))}</li>`).join('')}</ul>
      <div class="row" style="margin-top:16px"><button type="button" class="btn" id="snext" data-fk="snext" ${dis || !open.length ? 'disabled' : ''}>Settle next${s.next_resolution_ts ? ` <span class="note" style="margin:0">(${esc(fmtTs(s.next_resolution_ts, true))})</span>` : ''}</button><button type="button" class="btn" id="adv" data-fk="adv" ${dis || !open.length ? 'disabled' : ''}>Settle all</button><button type="button" class="btn" id="rst" data-fk="rst" ${dis}>Reset session</button></div>
      <p class="note" style="margin:8px 0 0">Settle next jumps the replay clock to the next open copy's result; Settle all jumps to the last one.</p></section>`;

    const picker = pick.length ? `<div class="pick" role="group" aria-label="Choose a trader">${pick.map((w) => `<button type="button" class="btn" data-w="${esc(w.address)}" data-fk="w-${esc(w.address)}" aria-pressed="${w.address === L.wallet}" ${dis}><span>${esc(w.label || 'Trader')} <span class="mono">${esc(shortAddr(w.address))}</span></span><span>${w.remaining} bet${w.remaining === 1 ? '' : 's'} left</span></button>`).join('')}</div>` : '<p class="note">No traders with replay bets are available.</p>';

    let card = '';
    if (pending) {
      const b = pending.bet, V = verdictInfo(pending.verdict), gate = (pending.precheck || []).find((c) => c.control === 'verdict_gate');
      const needsOverride = gate ? !gate.passed : ['CANT_TELL', 'PROBABLY_LUCK'].includes(V.code);
      const act_ = String(pending.action || '').toLowerCase();
      card = `<div class="panel tight" style="margin-top:16px;background:var(--glass-strong)" aria-labelledby="pr-h"><div class="row between"><h3 id="pr-h" style="margin:0">Proposal</h3>${verdictChip(pending.verdict)}</div>
        <p class="bet-title" style="margin-top:8px">${esc(b.title)}</p>
        <div class="row"><span class="chip slate">${esc(b.category)}</span><span class="chip slate">Token ${esc(b.token)}</span><span class="note mono">${esc(shortAddr(b.wallet))}</span></div>
        <div class="price-row"><div><span class="note">Leader paid</span><br><strong style="font-size:20px">${cents(b.leader_price)}</strong></div><div><span class="note">Price now</span><br><strong style="font-size:20px">${cents(b.current_price)}</strong></div><div><span class="note">Spread</span><br><strong style="font-size:20px">${cents(b.spread)}</strong></div></div>
        <h3>Proposal <span class="note" style="text-transform:none;letter-spacing:0;font-weight:400">(fixed rules in code, not the language model)</span></h3><p><span class="chip ${act_ === 'copy' ? 'good' : act_ === 'hold' ? 'warn' : 'slate'}">${esc(act_ === 'hold' ? 'hold: unsure, asking you' : act_ || '?')}</span> ${act_ === 'copy' ? `suggested stake <strong>${gbp(Number(pending.stake), 2)}</strong>` : ''}</p>
        <ul>${(pending.reasons || []).map((r) => `<li>${esc(r)}</li>`).join('')}</ul>
        <h3>Controls pre-check</h3>${checksList(pending.precheck)}
        <h3 style="margin-top:16px">Your decision</h3>
        <div class="field"><label for="stake">Stake (£) <span class="note" style="font-weight:400">max ${gbp(capGbp, 2)} per copy (${pct(s.limits.per_trade_cap_frac)} of ${gbp(s.bankroll)}) · cash ${gbp(s.cash, 2)}</span></label><input id="stake" type="number" min="0" step="0.5" inputmode="decimal" value="${esc(L.stake)}" ${dis} aria-describedby="stake-warn"><small>Suggested ${gbp(Number(pending.stake), 2)}. A blocked proposal stays pending: change the stake and try again.</small><small id="stake-warn" class="stake-warn" role="status">${stakeWarn(L.stake)}</small></div>
        <div class="field"><label for="ovr">Override reason${needsOverride ? ' (required)' : ' (optional)'}</label><textarea id="ovr" ${dis} aria-describedby="ovr-h">${esc(L.override)}</textarea><small id="ovr-h">${needsOverride ? `The verdict gate fails for “${esc(V.label)}” traders: copying needs an explicit reason, which is logged.` : 'Logged with the decision if given.'}</small></div>
        <div class="row"><button type="button" class="btn primary" id="appr" data-fk="appr" ${dis}>Approve</button><button type="button" class="btn" id="rej" data-fk="rej" ${dis}>Reject</button></div></div>`;
    }

    let result = '';
    if (L.result) {
      const r = L.result, st = r.status, failed = (r.checks || []).filter((c) => !c.passed);
      const head = { executed: 'Executed: paper copy placed', blocked: 'Blocked by risk controls', rejected: 'Rejected by you' }[st] || st;
      result = `<div class="status-box ${esc(st)}" id="result" role="status" tabindex="-1"><h3>${esc(head)}</h3>
        ${st === 'blocked' ? `<p style="margin:0 0 8px">Nothing was executed. ${failed.length} control${failed.length === 1 ? '' : 's'} failed:</p><ul class="checks">${failed.map((c) => `<li><span class="pill fail">FAIL</span><span><strong>${esc(CONTROL_LABELS[c.control] || c.control)}</strong>: ${esc(c.reason)}</span></li>`).join('')}</ul><p class="note" style="margin:8px 0 0">The proposal is still pending. Lower the stake or add an override reason, then approve again.</p>` : ''}
        ${st === 'executed' ? '<p style="margin:0 0 8px">All controls passed. The copy is on the paper ledger.</p>' + checksList(r.checks) : ''}
        ${st === 'rejected' ? '<p style="margin:0">No trade was made.</p>' : ''}
        ${r.audit_entry ? `<p class="note" style="margin:12px 0 0">Recorded in the activity record: ${esc(r.audit_entry.summary || r.audit_entry.event)}</p><pre class="log tech-only">${esc(JSON.stringify(Object.fromEntries(Object.entries(r.audit_entry).filter(([k]) => !['summary', 'kind', 'kind_label'].includes(k))), null, 2))}</pre>` : ''}</div>`;
    }

    const ks = s.kill_switch || {};
    const kill = `<section class="panel ${ks.on ? 'status-box blocked' : ''}" aria-labelledby="ks-h" style="margin-bottom:16px"><div class="row between"><h3 id="ks-h" style="margin:0">Kill switch</h3><span class="chip ${ks.on ? 'bad' : 'good'}">${ks.on ? 'ON: all copying stopped' : 'off'}</span></div>
      ${ks.on ? `<p style="margin:8px 0">Turned on by <strong>${esc(ks.by || '?')}</strong>${ks.reason ? ` (${esc(ks.reason)})` : ''}${ks.since ? ` at ${esc(ks.since)}` : ''}. Every proposal fails the kill-switch control until a human turns it off. The agent can turn it on but never off.</p><button type="button" class="btn" id="ks-off" data-fk="ks-off" ${dis}>Turn off (human)</button>`
      : `<p style="margin:8px 0">One click stops every copy, from anywhere (web, agent, terminal). It is a file on disk, so it survives restarts.</p><button type="button" class="btn primary" id="ks-on" data-fk="ks-on" ${dis}>Stop all copying</button>`}</section>`;
    const right = `<div>${kill}<section class="panel" aria-labelledby="tr-h"><h3 id="tr-h">Pick a trader and take the next bet</h3>${picker}
      <button type="button" class="btn primary" id="next" data-fk="next" ${canNext ? '' : 'disabled'}>${L.busy ? '<span class="spinner" aria-hidden="true"></span> Working…' : 'Next bet'}</button>
      ${pending ? '<span class="note" style="margin-left:8px">Decide the pending proposal first.</span>' : ''}
      ${L.err ? `<p role="alert" class="chip chip-err" style="margin-top:12px;white-space:normal">${esc(L.err)}</p>` : ''}
      ${card}${result}</section></div>`;

    const strip = `<section class="panel" aria-labelledby="au-h"><div class="row between"><h3 id="au-h" style="margin:0">What just happened</h3><a href="#/hood/record">Full activity record</a></div>
      <p class="note">Paper trading and safety events only, newest first. Every line is permanent.</p>
      ${L.audit.length ? tableHtml([...L.audit].reverse(), 'Recent paper-trading and safety events, newest first') : '<p class="note">Nothing yet. Take the next bet to start.</p>'}</section>`;

    root.innerHTML = `<div class="live-grid">${right}${left}</div><div style="margin-top:24px">${strip}</div>`;
    wire();
    if (focusKey) { const el = root.querySelector(`[data-fk="${CSS.escape(focusKey)}"]`); if (el && !el.disabled) el.focus({ preventScroll: true }); }
    if (scrollResult && L.result) $('#result', root)?.scrollIntoView({ block: 'nearest', behavior: 'auto' });
  }

  // Warns while you type, before you press Approve (the controls still decide at approval).
  function stakeWarn(raw) {
    const s = L.state; if (!s) return '';
    const v = parseFloat(raw), cap = s.limits.per_trade_cap_frac * s.bankroll;
    if (raw === '' || Number.isNaN(v)) return '';
    if (v < 0) return '<span class="neg">A stake can’t be negative.</span>';
    const msgs = [];
    if (v > cap + 1e-9) msgs.push(`Over the ${gbp(cap, 2)} per-copy cap: this will be blocked.`);
    if (v > s.cash + 1e-9) msgs.push(`More than your ${gbp(s.cash, 2)} cash: this will be blocked.`);
    return msgs.length ? `<span class="neg">${msgs.join(' ')}</span>` : '';
  }

  function checksList(cs) {
    if (!cs?.length) return '<p class="note">No pre-check results.</p>';
    return `<ul class="checks">${cs.map((c) => `<li><span class="pill ${c.passed ? 'pass' : 'fail'}">${c.passed ? 'PASS' : 'FAIL'}</span><span><strong>${esc(CONTROL_LABELS[c.control] || c.control)}</strong>: ${esc(c.reason || '')}</span></li>`).join('')}</ul>`;
  }

  function wire() {
    $$('[data-w]', root).forEach((b) => b.addEventListener('click', () => { L.wallet = b.dataset.w; paint(b.dataset.fk); }));
    $$('[data-resume]', root).forEach((b) => b.addEventListener('click', () => act(async () => { const r = await post('/api/live/resume', { wallet: b.dataset.resume }); L.state = r.state; })));
    $('#next', root)?.addEventListener('click', () => act(async () => {
      L.result = null;
      const p = await post('/api/live/next', { wallet: L.wallet });
      setProposal(p); L.state = await get('/api/live/state');
    }));
    $('#stake', root)?.addEventListener('input', (e) => { L.stake = e.target.value; const w = $('#stake-warn', root); if (w) w.innerHTML = stakeWarn(L.stake); });
    $('#ovr', root)?.addEventListener('input', (e) => { L.override = e.target.value; });
    const decide = (decision) => act(async () => {
      const body = { proposal_id: L.proposal.proposal_id, decision };
      if (decision === 'approve') { const v = parseFloat(L.stake); if (!(v >= 0)) throw new Error('Enter a stake in pounds, e.g. 10.'); body.stake = v; }
      if (L.override.trim()) body.override_reason = L.override.trim();
      const r = await post('/api/live/decide', body);
      L.result = r; if (r.state) L.state = r.state; else L.state = await get('/api/live/state');
      if (r.status === 'blocked') { if (r.checks?.length) L.proposal = { ...L.proposal, precheck: r.checks }; }
      else L.proposal = null;
    });
    $('#appr', root)?.addEventListener('click', () => decide('approve'));
    $('#rej', root)?.addEventListener('click', () => decide('reject'));
    $('#ks-on', root)?.addEventListener('click', () => act(async () => { const r = await post('/api/killswitch', { on: true, reason: 'stopped from the Paper trading page' }); L.state = r.state; api.ctx.refreshMeta?.(); }));
    $('#ks-off', root)?.addEventListener('click', () => act(async () => { const r = await post('/api/killswitch', { on: false }); L.state = r.state; api.ctx.refreshMeta?.(); }));
    $('#snext', root)?.addEventListener('click', () => act(async () => { const r = await post('/api/live/settle-next', {}); L.state = r.state; }));
    $('#adv', root)?.addEventListener('click', () => act(async () => { const r = await post('/api/live/advance', {}); L.state = r.state; }));
    $('#rst', root)?.addEventListener('click', () => act(async () => { const r = await post('/api/live/reset', {}); L.state = r.state; L.proposal = null; L.result = null; await loadAll(); }));
  }

  try { await loadAll(); } catch (e) {
    if (api.stale()) return;
    root.innerHTML = errorState(e.message); root.querySelector('[data-retry]').addEventListener('click', api.rerun); return;
  }
  if (api.stale()) return;
  paint();
}
