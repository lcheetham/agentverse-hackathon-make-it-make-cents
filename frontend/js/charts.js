// Hand-rolled inline SVG charts. Each returns an HTML string: <figure> with svg[role=img][aria-label] + sr-only data table.
import { esc, spct, pct, gbp, usd, luckPct, fmtTs, cents } from './util.js';

const INK = '#162331', LINE = '#1F4E79', BAND = 'rgba(62,108,158,.20)', GRID = 'rgba(22,35,49,.12)';
const POS = '#0B5D56', NEG = '#8E2E4A';
const f1 = (n) => Number(n).toFixed(1);

function niceTicks(lo, hi, n = 5) {
  const span = hi - lo || 0.01, raw = span / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
  const out = []; for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9; v += step) out.push(Math.abs(v) < 1e-12 ? 0 : v);
  return out;
}
const sr = (caption, head, rows) => `<div class="sr-only"><table><caption>${esc(caption)}</caption><thead><tr>${head.map((h) => `<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
const fig = (svg, label, table, caption = '') => `<figure class="chart">${svg.replace('<svg ', `<svg role="img" aria-label="${esc(label)}" `)}${table}${caption ? `<figcaption>${caption}</figcaption>` : ''}</figure>`;

/** Edge with 95% CI: interval bar, mean dot, zero line. */
export function ciChart(edge) {
  const W = 640, H = 110, L = 24, R = 24;
  const lo0 = Math.min(edge.ci_low, 0), hi0 = Math.max(edge.ci_high, 0), pad = (hi0 - lo0) * 0.15 || 0.02;
  const lo = lo0 - pad, hi = hi0 + pad, X = (v) => L + ((v - lo) / (hi - lo)) * (W - L - R);
  const ticks = niceTicks(lo, hi, 6);
  const crosses = edge.ci_low <= 0 && edge.ci_high >= 0;
  const col = crosses ? '#64748B' : POS;
  let s = `<svg viewBox="0 0 ${W} ${H}">`;
  ticks.forEach((t) => { s += `<line x1="${f1(X(t))}" x2="${f1(X(t))}" y1="22" y2="76" stroke="${GRID}"/><text class="svg-text" x="${f1(X(t))}" y="94" text-anchor="middle">${spct(t, 0)}</text>`; });
  s += `<line x1="${f1(X(0))}" x2="${f1(X(0))}" y1="14" y2="82" stroke="${INK}" stroke-width="2" stroke-dasharray="4 3"/><text class="svg-text strong" x="${f1(X(0))}" y="10" text-anchor="middle">zero edge</text>`;
  s += `<line x1="${f1(X(edge.ci_low))}" x2="${f1(X(edge.ci_high))}" y1="49" y2="49" stroke="${col}" stroke-width="10" stroke-linecap="round" opacity=".35"/>`;
  s += `<line x1="${f1(X(edge.ci_low))}" x2="${f1(X(edge.ci_low))}" y1="39" y2="59" stroke="${col}" stroke-width="3"/><line x1="${f1(X(edge.ci_high))}" x2="${f1(X(edge.ci_high))}" y1="39" y2="59" stroke="${col}" stroke-width="3"/>`;
  s += `<circle cx="${f1(X(edge.mean))}" cy="49" r="8" fill="${col}" stroke="#fff" stroke-width="2"/></svg>`;
  const label = `Edge per position ${spct(edge.mean)} with 95% interval ${spct(edge.ci_low)} to ${spct(edge.ci_high)}, from ${edge.n_clusters} independent event clusters. The interval ${crosses ? 'includes' : 'excludes'} zero.`;
  return fig(s, label, sr('Edge with 95% confidence interval', ['Mean', 'CI low', 'CI high', 'Clusters'], [[spct(edge.mean), spct(edge.ci_low), spct(edge.ci_high), String(edge.n_clusters)]]));
}

/** Luck score bars by leaderboard size N. `custom` (optional) is the user's own N from the engine's /luck endpoint. */
export function luckBars(luck, verdictN, custom = null) {
  const rows = luck.by_n.map((r) => ({ ...r, tag: r.n === verdictN ? 'used for the verdict' : '' }));
  if (custom) {
    const same = rows.find((r) => r.n === custom.n);
    if (same) same.tag = same.tag ? `${same.tag}; your N` : 'your N'; else rows.push({ ...custom, tag: 'your N' });
    rows.sort((a, b) => a.n - b.n);
  }
  const html = rows.map((r) => {
    const w = Math.max(1, Math.min(100, (r.score ?? 0) * 100));
    return `<div class="bar-row${r.tag.includes('your N') ? ' mine' : ''}" ${r.tag ? 'style="font-weight:700"' : ''}><span>Picked from ${r.n.toLocaleString('en-GB')}${r.tag ? ` (${r.tag})` : ''}</span><div class="bar-track" aria-hidden="true"><div class="bar-fill" style="width:${w}%"></div></div><strong>${luckPct(r.score, r.upper_bound)}</strong></div>`;
  }).join('');
  const label = 'Luck score by leaderboard size: ' + rows.map((r) => `N=${r.n.toLocaleString('en-GB')}${r.tag ? ` (${r.tag})` : ''}: ${luckPct(r.score, r.upper_bound)}`).join('; ');
  return `<figure class="chart" role="group" aria-label="${esc(label)}">${html}${sr('Luck score by leaderboard size', ['N', 'Score', 'Upper bound'], rows.map((r) => [String(r.n), luckPct(r.score, r.upper_bound), r.upper_bound ? 'yes' : 'no']))}</figure>`;
}

/** Copy-delay decay: edge vs delay with CI band, zero line, n_copyable labels, chosen delay highlighted. */
export function delayChart(curve, chosenS) {
  const W = 640, H = 320, L = 56, R = 24, T = 20, B = 72;
  const lo0 = Math.min(0, ...curve.map((c) => c.ci_low)), hi0 = Math.max(0, ...curve.map((c) => c.ci_high)), pad = (hi0 - lo0) * 0.08 || .02;
  const lo = lo0 - pad, hi = hi0 + pad;
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const X = (i) => L + 50 + (curve.length === 1 ? 0.5 : i / (curve.length - 1)) * (W - L - R - 100);
  let s = `<svg viewBox="0 0 ${W} ${H}">`;
  niceTicks(lo, hi, 5).forEach((t) => { s += `<line x1="${L}" x2="${W - R}" y1="${f1(Y(t))}" y2="${f1(Y(t))}" stroke="${GRID}"/><text class="svg-text" x="${L - 8}" y="${f1(Y(t) + 4)}" text-anchor="end">${spct(t, 0)}</text>`; });
  const ci = curve.findIndex((c) => c.delay_s === chosenS);
  if (ci >= 0) s += `<rect x="${f1(X(ci) - 34)}" y="${T - 6}" width="68" height="${H - T - B + 12}" rx="12" fill="rgba(140,196,242,.28)" stroke="#5A8CC0"/>`;
  s += `<line x1="${L}" x2="${W - R}" y1="${f1(Y(0))}" y2="${f1(Y(0))}" stroke="${INK}" stroke-width="2" stroke-dasharray="5 4"/><text class="svg-text strong" x="${W - R}" y="${f1(Y(0) + 16)}" text-anchor="end">zero edge</text>`;
  const up = curve.map((c, i) => `${f1(X(i))},${f1(Y(c.ci_high))}`), dn = curve.map((c, i) => `${f1(X(i))},${f1(Y(c.ci_low))}`).reverse();
  s += `<polygon points="${up.concat(dn).join(' ')}" fill="${BAND}"/>`;
  s += `<polyline points="${curve.map((c, i) => `${f1(X(i))},${f1(Y(c.edge))}`).join(' ')}" fill="none" stroke="${LINE}" stroke-width="3" stroke-linejoin="round"/>`;
  curve.forEach((c, i) => {
    const on = c.delay_s === chosenS;
    s += `<circle cx="${f1(X(i))}" cy="${f1(Y(c.edge))}" r="${on ? 7 : 5}" fill="${on ? LINE : '#fff'}" stroke="${LINE}" stroke-width="2.5"/>`;
    s += `<text class="svg-text strong" x="${f1(X(i))}" y="${f1(Y(c.edge) - 13)}" text-anchor="middle">${spct(c.edge)}</text>`;
    s += `<text class="svg-text strong" x="${f1(X(i))}" y="${H - B + 28}" text-anchor="middle">${esc(c.delay_s === 0 ? 'No delay' : c.label)}</text>`;
    s += `<text class="svg-text" x="${f1(X(i))}" y="${H - B + 44}" text-anchor="middle">${c.n_copyable} of ${c.n_total} copyable</text>`;
  });
  s += `</svg>`;
  const label = 'Edge after copy delay, net of spread and fees: ' + curve.map((c) => `${c.delay_s === 0 ? 'no delay' : c.label}: ${spct(c.edge)} (95% interval ${spct(c.ci_low)} to ${spct(c.ci_high)}, ${c.n_copyable} of ${c.n_total} positions copyable)`).join('; ') + '.';
  return fig(s, label, sr('Copy-delay decay', ['Delay', 'Edge', 'CI low', 'CI high', 'Copyable', 'Total'], curve.map((c) => [c.label, spct(c.edge), spct(c.ci_low), spct(c.ci_high), c.n_copyable, c.n_total])));
}

/** Horizontal diverging bars: profit by category with edge. Zero sits in the middle of the plot area and both
 * halves share one scale, so the longest bar (gain or loss) fills its half and never runs into the labels. */
export function categoryChart(cats) {
  if (!cats.length) return '';
  const W = 640, rowH = 34, T = 8, H = cats.length * rowH + T + 22, L = 104, R = 156;
  const mx = Math.max(...cats.map((c) => Math.abs(c.profit))) || 1;
  const half = (W - L - R) / 2, zero = L + half, scale = half / mx;
  let s = `<svg viewBox="0 0 ${W} ${H}">`;
  s += `<rect x="${L}" y="${T - 2}" width="${f1(half)}" height="${cats.length * rowH}" fill="rgba(142,46,74,.05)"/><rect x="${f1(zero)}" y="${T - 2}" width="${f1(half)}" height="${cats.length * rowH}" fill="rgba(62,108,158,.06)"/>`;
  cats.forEach((c, i) => {
    const y = T + i * rowH, w = Math.abs(c.profit) * scale, x = c.profit >= 0 ? zero : zero - w;
    s += `<text class="svg-text strong" x="${L - 10}" y="${y + 17}" text-anchor="end">${esc(c.category)}</text>`;
    s += `<rect x="${f1(x)}" y="${y + 3}" width="${f1(Math.max(w, 2))}" height="18" rx="6" fill="${c.profit >= 0 ? '#3E6C9E' : NEG}"/>`;
    s += `<text class="svg-text" x="${W - R + 12}" y="${y + 12}">${usd(c.profit)}</text><text class="svg-text" x="${W - R + 12}" y="${y + 26}">edge ${spct(c.edge)} · ${c.n} pos.</text>`;
  });
  const yb = T + cats.length * rowH;
  s += `<line x1="${f1(zero)}" x2="${f1(zero)}" y1="${T - 4}" y2="${yb + 2}" stroke="${INK}" stroke-width="1.5"/>`;
  s += `<text class="svg-text" x="${L}" y="${yb + 16}" text-anchor="start">−${usd(mx)}</text><text class="svg-text strong" x="${f1(zero)}" y="${yb + 16}" text-anchor="middle">$0</text><text class="svg-text" x="${W - R}" y="${yb + 16}" text-anchor="end">+${usd(mx)}</text></svg>`;
  const label = 'Profit by category, losses left of zero and gains right: ' + cats.map((c) => `${c.category} ${usd(c.profit)}, edge ${spct(c.edge)}, ${c.n} positions`).join('; ') + '.';
  return fig(s, label, sr('Profit by category', ['Category', 'Positions', 'Profit', 'Edge'], cats.map((c) => [c.category, c.n, usd(c.profit), spct(c.edge)])));
}

/** Equity curve for the £200 historical simulation. */
export function equityChart(sim, title = 'Simulated account value', what = 'Simulated £200 account value over time') {
  const pts = sim.curve || [];
  if (pts.length < 2) return '';
  const W = 640, H = 280, L = 64, R = 24, T = 24, B = 40;
  const vs = pts.map((p) => p.value), lo0 = Math.min(sim.start, ...vs), hi0 = Math.max(sim.start, ...vs), pad = (hi0 - lo0) * 0.12 || 5;
  const lo = lo0 - pad, hi = hi0 + pad, t0 = pts[0].ts, t1 = pts[pts.length - 1].ts || t0 + 1;
  const X = (t) => L + ((t - t0) / (t1 - t0 || 1)) * (W - L - R), Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  let s = `<svg viewBox="0 0 ${W} ${H}">`;
  niceTicks(lo, hi, 5).forEach((t) => { s += `<line x1="${L}" x2="${W - R}" y1="${f1(Y(t))}" y2="${f1(Y(t))}" stroke="${GRID}"/><text class="svg-text" x="${L - 8}" y="${f1(Y(t) + 4)}" text-anchor="end">${gbp(t)}</text>`; });
  s += `<line x1="${L}" x2="${W - R}" y1="${f1(Y(sim.start))}" y2="${f1(Y(sim.start))}" stroke="${INK}" stroke-width="1.5" stroke-dasharray="5 4"/><text class="svg-text strong" x="${L + 4}" y="${f1(Y(sim.start) - 6)}">start ${gbp(sim.start)}</text>`;
  s += `<polyline points="${pts.map((p) => `${f1(X(p.ts))},${f1(Y(p.value))}`).join(' ')}" fill="none" stroke="${LINE}" stroke-width="3" stroke-linejoin="round"/>`;
  const last = pts[pts.length - 1];
  s += `<circle cx="${f1(X(last.ts))}" cy="${f1(Y(last.value))}" r="6" fill="${LINE}" stroke="#fff" stroke-width="2"/><text class="svg-text strong" x="${f1(X(last.ts))}" y="${f1(Y(last.value) - 12)}" text-anchor="end">${gbp(sim.end)}</text>`;
  s += `<text class="svg-text" x="${L}" y="${H - 12}">${fmtTs(t0)}</text><text class="svg-text" x="${W - R}" y="${H - 12}" text-anchor="end">${fmtTs(t1)}</text></svg>`;
  const label = `${what}: starts at ${gbp(sim.start)}, ends at ${gbp(sim.end)} after ${sim.n_copied} copied positions.`;
  return fig(s, label, sr(title, ['Date', 'Value'], pts.filter((_, i) => i % Math.ceil(pts.length / 12) === 0 || i === pts.length - 1).map((p) => [fmtTs(p.ts), gbp(p.value, 2)])));
}

/** Detection rate by planted edge size with Wilson CI whiskers. */
export function powerChart(pc) {
  if (!pc?.length) return '';
  const W = 640, H = 300, L = 56, R = 24, T = 20, B = 52;
  const X = (i) => L + 24 + (pc.length === 1 ? 0.5 : i / (pc.length - 1)) * (W - L - R - 48), Y = (v) => T + (1 - v) * (H - T - B);
  let s = `<svg viewBox="0 0 ${W} ${H}">`;
  [0, .25, .5, .75, 1].forEach((t) => { s += `<line x1="${L}" x2="${W - R}" y1="${f1(Y(t))}" y2="${f1(Y(t))}" stroke="${GRID}"/><text class="svg-text" x="${L - 8}" y="${f1(Y(t) + 4)}" text-anchor="end">${pct(t)}</text>`; });
  s += `<polyline points="${pc.map((p, i) => `${f1(X(i))},${f1(Y(p.rate))}`).join(' ')}" fill="none" stroke="${LINE}" stroke-width="2.5"/>`;
  pc.forEach((p, i) => {
    s += `<line x1="${f1(X(i))}" x2="${f1(X(i))}" y1="${f1(Y(p.ci_low))}" y2="${f1(Y(p.ci_high))}" stroke="${LINE}" stroke-width="2"/><line x1="${f1(X(i) - 6)}" x2="${f1(X(i) + 6)}" y1="${f1(Y(p.ci_low))}" y2="${f1(Y(p.ci_low))}" stroke="${LINE}" stroke-width="2"/><line x1="${f1(X(i) - 6)}" x2="${f1(X(i) + 6)}" y1="${f1(Y(p.ci_high))}" y2="${f1(Y(p.ci_high))}" stroke="${LINE}" stroke-width="2"/>`;
    s += `<circle cx="${f1(X(i))}" cy="${f1(Y(p.rate))}" r="5" fill="#fff" stroke="${LINE}" stroke-width="2.5"/>`;
    s += `<text class="svg-text strong" x="${f1(X(i))}" y="${H - B + 20}" text-anchor="middle">${spct(p.edge, 0)}</text><text class="svg-text" x="${f1(X(i))}" y="${H - B + 36}" text-anchor="middle">${p.k}/${p.n}</text>`;
  });
  s += `<text class="svg-text" x="${(L + W - R) / 2}" y="${H - 2}" text-anchor="middle">Planted edge per position (detected / wallets)</text></svg>`;
  const label = 'Detection rate by planted edge size with 95% Wilson intervals: ' + pc.map((p) => `edge ${spct(p.edge, 0)}: ${pct(p.rate)} (${pct(p.ci_low)} to ${pct(p.ci_high)}, ${p.k} of ${p.n})`).join('; ') + '.';
  return fig(s, label, sr('Power curve', ['Planted edge', 'Detected', 'Wallets', 'Rate', 'CI low', 'CI high'], pc.map((p) => [spct(p.edge, 0), p.k, p.n, pct(p.rate), pct(p.ci_low), pct(p.ci_high)])));
}
export const priceC = cents;
