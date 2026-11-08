import { get } from './api.js';
import { esc, $, $$, usd, pct, verdictChip, skeleton, errorState } from './util.js';

// A demonstration with a reveal: five traders we built ourselves, so we know the truth about each.
export async function render(root, api) {
  root.innerHTML = `<section class="panel" aria-labelledby="rk-h"><h2 id="rk-h">Why a ranking can’t tell you who to copy</h2>
    <p>Here are five traders. <strong>We built them ourselves, so we know the truth about each one.</strong> First look at them the way a leaderboard shows them. Then reveal what they really are, and what our agent said without being told.</p>
    <p class="note" style="margin:0"><span class="chip chip-syn">Synthetic data</span> These are practice traders, not real wallets.</p></section>
    <div id="rk-body" style="margin-top:24px">${skeleton(4)}</div>`;
  const body = $('#rk-body', root);
  let rows;
  try { rows = await get('/api/wallets'); } catch (e) {
    if (api.stale()) return; body.innerHTML = errorState(e.message); body.querySelector('[data-retry]').addEventListener('click', api.rerun); return;
  }
  if (api.stale()) return;
  const st = { sort: 'profit', revealed: false };

  const paint = () => {
    const sorted = [...rows].sort((a, b) => st.sort === 'profit' ? (b.profit ?? 0) - (a.profit ?? 0) : (b.win_rate ?? 0) - (a.win_rate ?? 0));
    const right = rows.filter((r) => r.verdict_ok).length;
    body.innerHTML = `<section class="panel" aria-labelledby="rk-t">
      <div class="row between"><h3 id="rk-t" style="margin:0">Step 1 · The leaderboard view</h3>
        <div class="seg" role="group" aria-label="Sort by"><button type="button" class="btn small" data-sort="profit" aria-pressed="${st.sort === 'profit'}">Rank by profit</button><button type="button" class="btn small" data-sort="win" aria-pressed="${st.sort === 'win'}">Rank by win rate</button></div></div>
      <div class="table-wrap" style="margin-top:12px"><table><caption class="sr-only">Five planted traders</caption>
      <thead><tr><th class="num" scope="col">#</th><th scope="col">Trader</th><th class="num" scope="col">Profit</th><th class="num" scope="col">Record (W–L)</th><th class="num" scope="col">Win rate</th>
      ${st.revealed ? '<th scope="col">What they really are</th><th scope="col">Our agent said</th>' : ''}</tr></thead>
      <tbody>${sorted.map((r, i) => `<tr><td class="num">${i + 1}</td><td><a class="mono" href="#/wallet/${encodeURIComponent(r.address)}">${esc(r.address)}</a></td>
        <td class="num">${usd(r.profit)}</td><td class="num">${esc(r.record)}</td><td class="num">${pct(r.win_rate)}</td>
        ${st.revealed ? `<td>${esc(r.truth)}</td><td>${verdictChip(r.verdict)} ${r.verdict_ok ? '<span class="pill pass">right</span>' : '<span class="pill fail">wrong</span>'}</td>` : ''}</tr>`).join('')}</tbody></table></div>
      ${st.revealed ? '' : '<div class="row" style="margin-top:16px"><button type="button" class="btn primary" id="reveal">Step 2 · Reveal the truth</button><span class="note" style="margin:0">Before you click: which one would you copy?</span></div>'}
    </section>
    ${st.revealed ? `<section class="panel" aria-labelledby="rk-l"><h3 id="rk-l">What this shows</h3>
      <ul>
        <li><strong>Ranked by profit,</strong> the #1 trader has real skill, but the price catches up within minutes of their bets. Copying them an hour late gets you the price after the move, so their profit isn't available to you.</li>
        <li><strong>Ranked by win rate,</strong> the two most impressive records (25–0 and 34–1) are not skill. One buys at 95c, where you win almost every time and earn almost nothing. The other made many bets on just three stories, so it's really three lucky calls.</li>
        <li><strong>The “messy” trader</strong> with a 55% win rate is the only one a follower could actually have profited from.</li>
        <li><strong>Our agent got ${right} of ${rows.length} right</strong> without being told the truth. That's on traders we built. The next question is whether it holds up on data it has never seen.</li>
      </ul>
      <p style="margin:0">On real Polymarket data, copying the top 10 of the leaderboard an hour late lost an average of 19% per copy. Our agent approved none of them and stayed in cash. <a href="#/hood/tests">See how we tested it →</a></p></section>` : ''}`;
    $$('[data-sort]', body).forEach((b) => b.addEventListener('click', () => { st.sort = b.dataset.sort; paint(); }));
    $('#reveal', body)?.addEventListener('click', () => { st.revealed = true; paint(); $('#rk-l', body)?.scrollIntoView({ block: 'nearest' }); });
  };
  paint();
}
