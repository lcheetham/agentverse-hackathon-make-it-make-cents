import { get } from './api.js';
import { esc, $, fmtTs, skeleton, errorState, emptyState } from './util.js';

// "Activity record": the append-only, hash-chained log, in plain English. The server adds a one-line
// summary and a group to each entry; the raw entry (every field, the hash) shows with "Technical details".
const GROUP_TONE = { trading: 'good', safety: 'warn', agent: 'slate', analysis: 'slate', data: '', model: '', other: '' };

export const rowHtml = (e) => `<tr><td class="num tech-only">${e.seq}</td><td class="mono" style="white-space:nowrap">${esc(fmtTs(e.ts))}</td>
  <td><span class="chip ${GROUP_TONE[e.kind] || ''}">${esc(e.kind_label || e.kind)}</span><div class="note mono tech-only" style="margin:2px 0 0">${esc(e.event)}</div></td>
  <td>${esc(e.summary)}<details class="tech-only"><summary class="note">Raw entry</summary><pre class="log">${esc(JSON.stringify(Object.fromEntries(Object.entries(e).filter(([k]) => !['summary', 'kind', 'kind_label'].includes(k))), null, 2))}</pre></details></td></tr>`;
export const tableHtml = (rows, caption) => `<div class="table-wrap"><table><caption class="sr-only">${esc(caption)}</caption><thead><tr><th class="num tech-only" scope="col">Line</th><th scope="col">Time (UTC)</th><th scope="col">What</th><th scope="col">What happened</th></tr></thead><tbody>${rows.map(rowHtml).join('')}</tbody></table></div>`;

export async function render(root, api) {
  const kind = api.params.get('kind') || '';
  root.innerHTML = `<section class="panel" aria-labelledby="ar-h"><h2 id="ar-h">Activity record</h2>
    <p>Everything the app did, newest first: data downloads, verdicts, the agent's tool calls, proposals, approvals, blocks and kill-switch changes. Lines can only be added, never edited.</p>
    <div id="ar-chain"></div>
    <div class="row" id="ar-filter" role="group" aria-label="Show" style="gap:8px;margin-top:12px"></div></section>
    <div id="ar-body" style="margin-top:24px">${skeleton(5)}</div>`;
  const body = $('#ar-body', root);
  let log, chain = null, kinds = [];
  try {
    [log, chain, kinds] = await Promise.all([get(`/api/audit?limit=300${kind ? `&kind=${encodeURIComponent(kind)}` : ''}`),
      get('/api/audit/verify').catch(() => null), get('/api/audit/kinds').catch(() => [])]);
  } catch (e) {
    if (api.stale()) return; body.innerHTML = errorState(e.message); body.querySelector('[data-retry]').addEventListener('click', api.rerun); return;
  }
  if (api.stale()) return;
  $('#ar-chain', root).innerHTML = chain ? `<p style="margin:0">${chain.ok ? '<span class="chip good">Untouched: no line edited or deleted</span>' : `<span class="chip bad">Tampering detected at line ${chain.first_bad_line}</span>`} <span class="note tech-only">Each line stores the SHA-256 hash of the line before it, so changing or deleting any line breaks the chain from that point.</span></p>` : '';
  const opts = [['', 'Everything'], ...kinds];
  $('#ar-filter', root).innerHTML = opts.map(([k, label]) => `<a class="btn small" href="#/hood/record${k ? `?kind=${k}` : ''}" ${k === kind ? 'aria-current="page"' : ''}>${esc(label)}</a>`).join('');
  if (!log.length) { body.innerHTML = emptyState('Nothing here yet', kind ? 'No entries of this kind yet.' : 'Entries appear as soon as the app does something.'); return; }
  body.innerHTML = `<section class="panel">${tableHtml([...log].reverse(), 'Activity record, newest first')}<p class="note" style="margin:12px 0 0">Showing the latest ${log.length} entries. The full file is <span class="mono">logs/audit.jsonl</span>.</p></section>`;
}
