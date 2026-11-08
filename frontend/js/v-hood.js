import { $ } from './util.js';

// "Under the hood": how we know, in three sub-tabs. Each sub-tab is its own module, rendered into #hood-body.
const TABS = [
  { id: 'rankings', label: 'Why rankings mislead', load: () => import('./v-rankings.js') },
  { id: 'tests', label: 'How we tested it', load: () => import('./v-evaluation.js') },
  { id: 'record', label: 'Activity record', load: () => import('./v-audit.js') },
];

export async function render(main, api) {
  const tab = TABS.find((t) => t.id === api.arg) || TABS[0];
  main.innerHTML = `<section class="hero" style="padding-bottom:16px"><h1>Under the hood</h1>
    <p class="lede">How we know what we claim: why a profit ranking isn't enough, how the agent was tested on data it had never seen, and a tamper-evident record of everything it did.</p></section>
    <nav class="subnav" aria-label="Under the hood">${TABS.map((t) => `<a class="btn small" href="#/hood/${t.id}" ${t.id === tab.id ? 'aria-current="page"' : ''}>${t.label}</a>`).join('')}</nav>
    <div id="hood-body" style="margin-top:16px"></div>`;
  const mod = await tab.load();
  if (api.stale()) return;
  await mod.render($('#hood-body', main), api);
}
