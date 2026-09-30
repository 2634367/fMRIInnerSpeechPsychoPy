// The launcher: every config, local and from the planner, with a Demo button.
// Options persist in this browser; the stage (stage.js) plays the run, and the
// feed (feed.js) sends it to the debug popup and the JS console.

import { Feed, clock } from './feed.js';
import { Stage, SPEEDS } from './stage.js';

const DEFAULTS = {
  seed: '', blocks: '', scanner: 'simulate', speed: 1,
  auto: false, debug: true, fullscreen: false, popup: false, hud: false,
};
const PRESETS = {
  quick: { blocks: 2, scanner: 'none', auto: true, speed: 5, debug: true },
  full: { blocks: '', scanner: 'simulate', auto: false, speed: 1 },
};
const SCANNER_LABEL = { none: 'no scanner', simulate: 'simulated pulses', key: 'trigger key' };
const STORE = 'innerspeech-demo/options';
const THEME = 'innerspeech-demo/theme';

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

/** h('div', {class: 'x', onclick}, child, 'text', …) */
function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'style') el.style.cssText = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}

function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(key));
    localStorage.setItem(key, JSON.stringify(value));
  } catch { /* private window, blocked storage: fine */ }
  return undefined;
}

// ================================================================ state ===
const feed = new Feed();
const stageEl = $('#stage');
const stage = new Stage(stageEl, feed, { onBack: back, onReplay: replay, openDebug });
let opts = { ...DEFAULTS, ...(store(STORE) || {}) };
let catalog = null;
let remote = null;                       // the planner's own list, once asked for
const notes = {};                        // design key -> {kind, text} after a refresh
let current = null;                      // {target, options, plan} while on stage
let lastButton = null;
let debugWin = null;

feed.onCommand = (cmd, arg) => {
  if (stage.state === 'idle') return;
  switch (cmd) {
    case 'toggle-pause': stage.togglePause(); break;
    case 'skip': stage.skip(); break;
    case 'speed': stage.setSpeed(arg); break;
    case 'abort': stage.abort(); break;
    case 'hud': stage.toggleHud(); break;
    case 'jump': stage.jump(Number(arg)); break;
    case 'key': stage.key(arg); break;
    default: break;
  }
};

// ================================================================== API ===
async function api(path, body) {
  const init = body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  };
  const res = await fetch(path, init);
  let data;
  try { data = await res.json(); } catch { throw new Error(`${res.status} ${res.statusText}`); }
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

async function loadCatalog() {
  try {
    catalog = await api('/api/catalog');
  } catch (e) {
    $('#catalog').replaceChildren(h('div', { class: 'empty-state' }, `Could not load the configs: ${e.message}`));
    return;
  }
  render();
}

// ============================================================= targets ===
function targets() {
  if (!catalog) return [];
  const local = catalog.local.map((c) => ({ ...c, source: 'local' }));
  const planned = catalog.planner.designs.flatMap((d) =>
    d.configs.map((c) => ({ ...c, source: 'planner', design: d.key, designName: d.name, rev: d.rev })));
  return [...local, ...planned];
}

function findTarget(what) {
  const text = String(what).trim().toLowerCase();
  const all = targets();
  return all.find((t) => t.source === 'local' && t.name === text)
    || all.find((t) => [t.id, t.stem, t.run].some((x) => x && String(x).toLowerCase() === text))
    || all.find((t) => `${t.design}/${t.index}`.toLowerCase() === text);
}

function effectiveBlocks(t, o) {
  const b = parseInt(o.blocks, 10);
  if (!b || !t.n_blocks) return null;
  const n = Math.min(b, t.n_blocks);                     // a demo never lengthens a run
  return n === t.n_blocks ? null : n;
}

function quote(s) {
  s = String(s);
  return /^[\w./:=-]+$/.test(s) ? s : `'${s.replace(/'/g, "'\\''")}'`;
}

/** The PsychoPy command that runs the same config with the same options. */
function commandFor(t, o, seed) {
  const parts = ['./run.sh'];
  if (t.source === 'planner') parts.push('planner', '--design', quote(t.design), '--run', quote(t.id || t.stem));
  else if (t.name !== 'experiment') parts.push('--config', quote(t.name));
  if (seed !== '' && seed != null) parts.push('--seed', seed);
  const blocks = effectiveBlocks(t, o);
  if (blocks) parts.push('--blocks', blocks);
  if (o.scanner === 'none') parts.push('--no-scanner');
  if (o.auto) parts.push('--auto');
  if (o.debug) parts.push('--debug');
  if (!o.fullscreen) parts.push('--windowed');
  return parts.join(' ');
}

// ============================================================== render ===
function render() {
  const root = $('#catalog');
  root.replaceChildren();
  root.append(group({
    title: 'Local',
    meta: `config/ · ${catalog.local.length} configs`,
    overview: catalog.overview,
    cards: catalog.local.map((c) => card({ ...c, source: 'local' })),
  }));
  for (const d of catalog.planner.designs) root.append(designGroup(d));
  root.append(remoteGroup());
  applyFilter();
}

function group({ title, meta, overview, actions = [], note, cards }) {
  return h('section', { class: 'group' },
    h('div', { class: 'group-head' },
      h('h2', {}, title),
      h('span', { class: 'meta' }, meta),
      h('div', { class: 'actions' },
        overview && h('button', { class: 'small ghost', onclick: () => lightbox(overview) }, 'Overview image'),
        ...actions)),
    note && h('div', { class: `note ${note.kind}` }, note.text),
    cards && h('div', { class: 'grid' }, ...cards));
}

function designGroup(d) {
  const host = catalog.planner.host;
  const where = `config/planner/${d.key}/`;
  const meta = `rev ${d.rev ?? '?'} · ${d.live ? 'live - just fetched' : `mirror fetched ${d.fetched_label}`} · ${where}`;
  const refresh = h('button', {
    class: 'small', disabled: !host,
    title: host ? `Fetch ${d.name} again and mirror it to ${where}` : 'Set PLANNER_HOST (and PLANNER_KEY) in .env',
    onclick: (e) => refreshDesign(d.key, e.currentTarget),
  }, 'Refresh from planner');
  return group({
    title: `Planner · ${d.name}`, meta, overview: d.overview, actions: [refresh], note: notes[d.key],
    cards: d.configs.map((c) => card({ ...c, source: 'planner', design: d.key, designName: d.name, rev: d.rev })),
  });
}

function remoteGroup() {
  const host = catalog.planner.host;
  const mirrored = new Map(catalog.planner.designs.map((d) => [d.key, d]));
  const check = h('button', {
    class: 'small', disabled: !host,
    title: host ? 'List the designs on the planner (no key needed)' : 'Set PLANNER_HOST in .env',
    onclick: (e) => checkRemote(e.currentTarget),
  }, remote ? 'Check again' : 'Check the planner');
  let list = null;
  if (remote?.error) {
    list = h('div', { class: 'note error' }, remote.error);
  } else if (remote) {
    list = h('div', { class: 'remote' }, remote.designs.length ? remote.designs.map((d) => {
      const have = mirrored.get(d.name);
      const status = have
        ? (have.rev === d.rev ? `mirrored, up to date (rev ${d.rev})` : `mirrored at rev ${have.rev} · planner has ${d.rev}`)
        : `rev ${d.rev ?? '?'} · not mirrored`;
      return h('div', { class: 'item' },
        h('span', { class: 'name' }, d.name),
        h('span', { class: 'meta' }, `${d.title ? `${d.title} · ` : ''}${status}`),
        h('button', { class: 'small', onclick: (e) => refreshDesign(d.name, e.currentTarget) }, have ? 'Refresh' : 'Fetch'));
    }) : h('div', { class: 'item' }, h('span', { class: 'meta' }, 'The planner has no designs.')));
  }
  return h('section', { class: 'group' },
    h('div', { class: 'group-head' },
      h('h2', {}, 'On the planner'),
      h('span', { class: 'meta' }, host
        ? 'fetch a design to demo it; it is mirrored to config/planner/, as `planner --download` does'
        : 'PLANNER_HOST is not set in .env - only designs already mirrored are listed'),
      h('div', { class: 'actions' }, check)),
    list);
}

function card(t) {
  const planner = t.source === 'planner';
  const title = planner ? (t.run || t.name) : t.name;
  const search = [title, t.name, t.experiment, t.file, t.id, t.designName].filter(Boolean).join(' ').toLowerCase();
  const thumb = t.overview
    ? h('button', { class: 'thumb', title: 'Overview image', onclick: () => lightbox(t.overview) },
      h('img', { src: t.overview, alt: `Overview of ${title}`, loading: 'lazy' }))
    : h('div', { class: 'thumb none' }, 'no overview image yet');
  const head = [
    h('h3', {},
      planner && h('span', { class: 'pos' }, `#${t.index}`),
      h('span', {}, title),
      !planner && t.name === 'experiment' && h('span', { class: 'chip accent' }, 'default')),
    h('div', { class: 'file mono', title: t.file }, planner ? `${t.file} · ${t.id}` : t.file),
  ];
  if (t.error) {
    return h('article', { class: 'card', dataset: { search } }, thumb,
      h('div', { class: 'body' }, ...head, h('div', { class: 'error' }, t.error)));
  }

  const [lo, hi] = t.run_len;
  const length = lo === hi ? clock(lo) : `${clock(lo)}–${clock(hi)}`;
  const stats = h('div', { class: 'stats' },
    h('span', {}, 'TR ', h('b', {}, `${t.tr} s`)),
    h('span', {}, h('b', {}, t.n_trials), ` trials (${t.n_blocks}×${t.per_block})`),
    h('span', { title: 'run length, shortest to longest jitter draw (m:ss)' }, h('b', {}, length)),
    h('span', {}, `${t.dummies} dummies on `, h('code', {}, t.trigger_key)));
  const strip = h('div', { class: 'strip', title: 'one trial, phases at their mean length' },
    ...t.phases.map((p) => h('span', {
      style: `flex:${Math.max((p.lo + p.hi) / 2, 0.05)};background:var(--show-${p.show})`,
      title: `${p.name} · ${p.show} · ${p.lo === p.hi ? `${p.lo} s` : `${p.lo}–${p.hi} s ${p.jitter}`}`,
    })));
  const legend = h('div', { class: 'strip-legend' },
    ...t.phases.map((p) => h('span', {},
      h('i', { style: `background:var(--show-${p.show})` }),
      `${p.name} ${p.lo === p.hi ? p.lo : `${p.lo}–${p.hi}`} s`)));
  const conds = h('div', { class: 'conds' },
    ...Object.entries(t.conditions).filter(([, n]) => n > 0)
      .map(([k, n]) => h('span', { class: 'chip' }, `${k} `, h('b', {}, n))));
  const demo = h('button', { class: 'primary', onclick: (e) => { lastButton = e.currentTarget; startDemo(t); } }, '▶ Demo');
  const copy = h('button', {
    title: 'Copy the PsychoPy command with these options',
    onclick: () => copyText(commandFor(t, opts, opts.seed)),
  }, 'Command');

  return h('article', { class: 'card', dataset: { search } }, thumb,
    h('div', { class: 'body' }, ...head, stats, strip, legend, conds,
      t.ignored?.length ? h('div', { class: 'footnote' }, `Not implemented by the task, ignored: ${t.ignored.join(', ')}`) : null,
      h('div', { class: 'buttons' }, demo, copy)));
}

function applyFilter() {
  const text = $('#filter').value.trim().toLowerCase();
  for (const section of $$('#catalog section.group')) {
    const cards = $$('.card', section);
    if (!cards.length) continue;
    let shown = 0;
    for (const c of cards) {
      const hit = !text || c.dataset.search.includes(text);
      c.classList.toggle('filtered', !hit);
      shown += hit;
    }
    section.hidden = shown === 0;
  }
}

// ============================================================= planner ===
async function refreshDesign(design, button) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = 'Fetching…';
  try {
    const d = await api('/api/planner/refresh', { design });
    const list = catalog.planner.designs;
    const i = list.findIndex((x) => x.key === d.key);
    if (i >= 0) list[i] = d; else list.push(d);
    notes[d.key] = d.note ? { kind: 'warn', text: `Mirrored rev ${d.rev}. ${d.note}` }
      : { kind: 'ok', text: `Mirrored rev ${d.rev} to config/planner/${d.key}/ and redrew its overview images.` };
    if (remote) remote.designs = remote.designs.map((x) => (x.name === d.key ? { ...x, rev: d.rev } : x));
    render();
    toast(`${d.name} · rev ${d.rev} mirrored`);
  } catch (e) {
    notes[design] = { kind: 'error', text: e.message };
    if (catalog.planner.designs.some((x) => x.key === design)) render();
    else toast(e.message, true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

async function checkRemote(button) {
  button.disabled = true;
  button.textContent = 'Asking…';
  try {
    remote = await api('/api/planner/designs');
  } catch (e) {
    remote = { designs: [], error: e.message };
  }
  render();
}

// ================================================================ demo ===
async function startDemo(t, overrides = {}) {
  const o = { ...opts, ...overrides };
  // both need the click's user activation, so they come before any await
  if (o.popup) openDebug();
  if (o.fullscreen && !document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});

  let plan;
  try {
    plan = await api('/api/plan', {
      source: t.source, design: t.design,
      config: t.source === 'planner' ? (t.id || t.stem) : t.name,
      seed: o.seed === '' || o.seed == null ? null : Number(o.seed),
      blocks: effectiveBlocks(t, o),
    });
  } catch (e) {
    toast(e.message, true);
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    return;
  }
  const { cfg } = plan;
  const meta = {
    label: t.source === 'planner' ? `${t.designName} · ${t.run}` : t.name,
    seed: plan.seed, source: plan.source, file: plan.source.file, experiment: cfg.experiment,
    n_trials: plan.trials.length, n_blocks: cfg.run.n_blocks, per_block: cfg.run.trials_per_block,
    phases: cfg.trial.phases.map((p) => p.name), lead_in: cfg.run.lead_in.name, tr: cfg.scanner.tr,
    dummies: cfg.scanner.wait_for_triggers, trigger_key: String(cfg.scanner.trigger_key),
    total: plan.total, n_questions: plan.n_questions, reused: plan.reused,
    options: { scanner: o.scanner, speed: o.speed, auto: o.auto, debug: o.debug, fullscreen: o.fullscreen },
    command: commandFor(t, o, plan.seed),
  };
  current = { target: t, options: o, plan };
  $('#launcher').hidden = true;
  stageEl.hidden = false;
  document.body.classList.add('on-stage');
  stageEl.focus();
  stage.start(plan, o, meta);
}

function replay(sameSeed) {
  if (!current) return;
  const { target, options, plan } = current;
  startDemo(target, { ...options, seed: sameSeed ? plan.seed : '' });
}

function back() {
  stage.stop();
  current = null;
  stageEl.hidden = true;
  document.body.classList.remove('on-stage');
  $('#launcher').hidden = false;
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  lastButton?.focus();
}

function openDebug() {
  if (debugWin && !debugWin.closed) {
    debugWin.focus();
    return debugWin;
  }
  debugWin = window.open('debug.html', 'innerspeech-debug', 'popup=yes,width=660,height=900');
  if (!debugWin) toast('The browser blocked the debug window. Allow popups for this page; the JS console has everything too.', true);
  return debugWin;
}

// ============================================================= options ===
function syncOptions() {
  store(STORE, opts);
  const form = $('#options');
  form.seed.value = opts.seed;
  form.blocks.value = opts.blocks;
  for (const name of ['auto', 'debug', 'fullscreen', 'popup', 'hud']) form[name].checked = !!opts[name];
  for (const seg of $$('.seg[data-name]', form)) {
    for (const b of $$('button', seg)) b.setAttribute('aria-pressed', String(b.dataset.value === String(opts[seg.dataset.name])));
  }
  for (const b of $$('[data-preset]')) {
    const p = PRESETS[b.dataset.preset];
    b.setAttribute('aria-pressed', String(Object.entries(p).every(([k, v]) => String(opts[k]) === String(v))));
  }
  const chips = [
    opts.seed !== '' ? `seed ${opts.seed}` : 'random seed',
    opts.blocks ? `≤ ${opts.blocks} blocks` : 'all blocks',
    SCANNER_LABEL[opts.scanner], `×${opts.speed}`,
    opts.auto && 'auto', opts.debug && 'debug keys', opts.fullscreen && 'fullscreen',
    opts.popup && 'debug window', opts.hud && 'HUD',
  ].filter(Boolean);
  $('#opt-chips').replaceChildren(...chips.map((c) => h('span', { class: 'chip' }, c)));
}

function bindOptions() {
  const form = $('#options');
  form.addEventListener('submit', (e) => e.preventDefault());
  form.addEventListener('input', (e) => {
    const el = e.target;
    if (el.type === 'checkbox') opts[el.name] = el.checked;
    else if (el.name === 'seed' || el.name === 'blocks') opts[el.name] = el.value.trim();
    syncOptions();
  });
  for (const seg of $$('.seg[data-name]', form)) {
    seg.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      const name = seg.dataset.name;
      opts[name] = name === 'speed' ? Number(b.dataset.value) : b.dataset.value;
      syncOptions();
    });
  }
  for (const b of $$('[data-preset]')) {
    b.addEventListener('click', () => { Object.assign(opts, PRESETS[b.dataset.preset]); syncOptions(); });
  }
  $('#toggle-options').addEventListener('click', (e) => {
    form.hidden = !form.hidden;
    e.currentTarget.setAttribute('aria-expanded', String(!form.hidden));
  });
  if (!SPEEDS.includes(Number(opts.speed))) opts.speed = 1;
  syncOptions();
}

// ================================================================ bits ===
function lightbox(src) {
  const box = $('#lightbox');
  $('img', box).src = src;
  box.hidden = false;
}

let toastTimer = 0;
function toast(text, error = false) {
  const el = $('#toast');
  el.textContent = text;
  el.classList.toggle('error', error);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, error ? 6000 : 2200);
}

function copyText(text) {
  navigator.clipboard?.writeText(text).then(() => toast(`Copied: ${text}`), () => toast(text));
}

function theme(next) {
  const order = ['auto', 'light', 'dark'];
  const value = next ?? store(THEME) ?? 'auto';
  if (value === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = value;
  $('#theme').textContent = `Theme: ${value}`;
  store(THEME, value);
  return order[(order.indexOf(value) + 1) % order.length];
}

// ========================================================= console API ===
window.innerspeech = {
  get catalog() { return catalog; },
  get options() { return { ...opts }; },
  get state() { return stage.state; },
  get live() { return feed.live; },
  get plan() { return current?.plan ?? null; },
  get cfg() { return current?.plan.cfg ?? null; },
  get trials() { return current?.plan.trials ?? []; },
  get events() { return feed.events; },
  /** demo('glm'), demo('run-mtmfi9kd-4', {speed: 10}), demo('V2/0') */
  demo(what, overrides = {}) {
    const t = findTarget(what);
    if (!t) return console.warn(`no config ${JSON.stringify(what)}; try one of`, targets().map((x) => x.id || x.name));
    return startDemo(t, overrides);
  },
  pause: () => stage.pause(),
  resume: () => stage.resume(),
  skip: () => stage.skip(),
  jump: (n, phase) => stage.jump(n, phase),
  speed: (x) => stage.setSpeed(x),
  abort: () => stage.abort(),
  hud: () => stage.toggleHud(),
  debug: () => openDebug(),
  back: () => back(),
  help() {
    console.log([
      'innerspeech.demo(name | id | "V2/0", {speed, blocks, seed, scanner, auto, debug})',
      'innerspeech.pause() resume() skip() jump(trial, phase?) speed(1|2|5|10|30) abort() hud() debug() back()',
      'innerspeech.state · live · plan · cfg · trials · events · catalog · options',
    ].join('\n'));
  },
};

// ================================================================ boot ===
bindOptions();
let nextTheme = theme();
$('#theme').addEventListener('click', () => { nextTheme = theme(nextTheme); });
$('#open-debug').addEventListener('click', openDebug);
$('#filter').addEventListener('input', applyFilter);
$('#lightbox').addEventListener('click', (e) => { e.currentTarget.hidden = true; });
document.addEventListener('keydown', (e) => {
  if (!stageEl.hidden) return;
  if (e.key === 'Escape' && !$('#lightbox').hidden) { $('#lightbox').hidden = true; return; }
  if (e.key === '/' && !e.target.closest('input, textarea')) { e.preventDefault(); $('#filter').focus(); }
});
feed.idle();
loadCatalog();
