/* Upshift dashboard.
   Everything shown here comes from the agent's structured event log or a saved
   run record. Nothing is inferred: a stage is active because the agent said so,
   and "Verified complete" appears only when the final event says every module
   imports and every selected test passes. */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const S = {
  state: 'ready',       // ready|connecting|running|waiting|lost|reconnecting|done
  meta: null,           // /api/state
  runId: null,
  seq: 0,               // last event sequence applied
  stage: null,
  stagesDone: new Set(),
  files: new Map(),     // index -> timeline entry
  open: new Set(),      // expanded timeline rows
  metrics: {},
  termOffset: 0,
  es: null,
  retry: 0,
  startedAt: null,
  timer: null,
  final: null,
  cancelling: false,
};

const fmtDur = s => s == null ? '—'
  : s < 60 ? `${s.toFixed(0)}s` : `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, '0')}s`;
const fmtNum = n => n == null ? '—' : n.toLocaleString();
const splitPath = p => {
  const i = String(p).lastIndexOf('/');
  return i < 0 ? ['', p] : [p.slice(0, i + 1), p.slice(i + 1)];
};

/* ---------- plain-language explanations ---------- */
function explainError(text) {
  const t = String(text || '');
  if (/non-annotated attribute/i.test(t))
    return 'A class attribute has no type annotation. Pydantic v2 requires one, or ' +
           '`ClassVar[...]` if it is a constant rather than a field.';
  if (/Field required/i.test(t))
    return 'A field that was optional in v1 is required in v2, and existing callers ' +
           'do not pass it. It needs an explicit default.';
  if (/field_info|__fields__/i.test(t))
    return 'Code uses pydantic v1 internals. In v2 these live on `model_fields`.';
  if (/model-field-overridden|overridden/i.test(t))
    return 'A subclass overrides a parent field without re-declaring its annotation.';
  if (/cannot import name/i.test(t))
    return 'An import no longer exists under this name in pydantic v2.';
  if (/ValidationError/i.test(t))
    return 'A model rejected values a test supplies — the shape changed between versions.';
  return '';
}
const VERDICT = {
  accepted:      ['ok',   'Kept',            'The edit improved the numbers and was committed.'],
  rolled_back:   ['warn', 'Rolled back',     'The edit did not improve the numbers, so it was undone.'],
  redirect:      ['info', 'Redirected',      'The real cause is in another file; the agent went there instead.'],
  guard_rejected:['warn', 'Rejected by guard','The patch would have weakened the tests.'],
  truncated:     ['warn', 'Reply truncated', 'The model hit its output limit mid-file.'],
  self_redirect: ['warn', 'Retried',         'The model pointed at the file it was already editing.'],
  no_change:     ['flat', 'No change',       'The model returned the file unchanged.'],
};
const OUTCOME = {
  migrated:    ['ok',   '✓', 'Repaired'],
  redirect:    ['info', '→', 'Redirected'],
  quarantined: ['warn', '!', 'Gave up'],
  'no-change': ['flat', '·', 'No change'],
  active:      ['info', '•', 'Working'],
};

/* ---------- routing ---------- */
function go(page) {
  $$('.page').forEach(p => p.hidden = p.id !== `page-${page}`);
  $$('.nav-item').forEach(b => b.setAttribute('aria-current', b.dataset.page === page ? 'page' : 'false'));
  $('#page-title').textContent = { migration: 'Migration', history: 'Run history', evidence: 'Evidence' }[page];
  history.replaceState(null, '', `#${page}`);
  if (page === 'history') loadHistory();
  if (page === 'evidence') loadEvidence();
}

/* ---------- connection status ---------- */
function paintStatus(m) {
  const set = (id, cls, txt) => {
    const el = $(id); el.className = `led ${cls}`;
    if (txt) $(txt.id).textContent = txt.text;
  };
  set('#led-agent', m.agent.model_key ? 'on' : 'off',
      { id: '#txt-agent', text: m.agent.model_key ? m.agent.model : 'No model key' });
  $('#led-neatlogs').className = `led ${m.neatlogs.configured ? 'on' : 'warn'}`;
  $('#led-entire').className = `led ${m.entire.logged_in ? 'on' : 'warn'}`;
  $('#harness').textContent = m.harness || '—';
}

/* ---------- setup ---------- */
function paintSetup() {
  const m = S.meta;
  const sel = $('#sel-target');
  sel.innerHTML = Object.values(m.targets)
    .map(t => `<option value="${esc(t.name)}">${esc(t.name)}</option>`).join('');
  $('#configs').innerHTML = Object.entries(m.configs).map(([id, c], i) => `
    <label class="choice" data-on="${i === 0 ? 1 : 0}">
      <input type="radio" name="config" value="${esc(id)}" ${i === 0 ? 'checked' : ''}>
      <span><span class="name">${esc(c.label)}</span>
      <span class="blurb">${esc(c.blurb)}</span></span>
    </label>`).join('');
  $$('#configs input').forEach(r => r.addEventListener('change', () => {
    $$('#configs .choice').forEach(c => c.dataset.on = c.contains(r) && r.checked ? 1 : 0);
  }));
  sel.addEventListener('change', paintTargetFacts);
  paintTargetFacts();
}
function paintTargetFacts() {
  const t = S.meta.targets[$('#sel-target').value];
  if (!t) return;
  $('#target-facts').innerHTML = `
    <dt>Migration</dt><dd>${esc(t.migration)}</dd>
    <dt>Source commit</dt><dd>${esc((t.commit || '').slice(0, 10))}</dd>
    <dt>Dependency</dt><dd>${esc(t.dependency)} ${esc(t.current)} → <b>${esc(t.target)}</b></dd>
    <dt>Modules</dt><dd>${fmtNum(t.modules_total)} total · ${fmtNum(t.start_modules)} import today</dd>
    <dt>Selected tests</dt><dd>${fmtNum(t.green_tests)} offline regression tests</dd>
    <dt>Working copy</dt><dd>${t.cloned ? 'ready' : 'will be cloned on first run'}</dd>`;
}

/* ---------- banners ---------- */
function banner(kind, title, body = '', actions = '') {
  $('#banner-slot').innerHTML = `<div class="banner ${kind}">
    <span class="ico">${{ ok: '✓', warn: '!', bad: '✕', info: 'i' }[kind]}</span>
    <div><b>${esc(title)}</b>${body ? `<div class="small dim" style="margin-top:3px">${body}</div>` : ''}</div>
    ${actions}</div>`;
}
const clearBanner = () => $('#banner-slot').innerHTML = '';

/* ---------- stages ---------- */
function paintStages() {
  $('#stages').innerHTML = S.meta.stages.map(s => {
    const st = S.stage === s.id ? 'active' : S.stagesDone.has(s.id) ? 'done' : 'todo';
    return `<div class="stage" data-s="${st}">
      <span class="mark">${st === 'done' ? '✓' : st === 'active' ? '●' : ''}</span>
      <span>${esc(s.label)}</span><span class="meta"></span></div>`;
  }).join('');
}

/* ---------- metrics ---------- */
function paintMetrics() {
  const m = S.metrics;
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);
  const row = (label, val, of, cls, bar) => `
    <div class="metric ${cls}">
      <div class="label">${esc(label)}</div>
      <div class="value" data-k="${esc(label)}">${val}${of ? ` <span class="of">/ ${of}</span>` : ''}</div>
      ${bar !== null ? `<div class="bar"><i style="width:${bar}%"></i></div>` : ''}
    </div>`;
  const modOk = m.modules_ok ?? 0, modTot = m.modules_total ?? 0;
  const tOk = m.tests_passed ?? 0, tTot = m.tests_total ?? 0;
  $('#metrics').innerHTML = [
    row('Modules importing', fmtNum(modOk), modTot ? fmtNum(modTot) : '',
        modTot && modOk >= modTot ? 'ok' : 'busy', modTot ? pct(modOk, modTot) : null),
    row('Tests passing', fmtNum(tOk), tTot ? fmtNum(tTot) : '',
        tTot && tOk >= tTot ? 'ok' : 'busy', tTot ? pct(tOk, tTot) : null),
    row('Files repaired', fmtNum(m.repaired ?? 0), '', '', null),
    row('Retries', fmtNum(m.retries ?? 0), '', (m.retries ? 'warn' : ''), null),
    row('Rollbacks', fmtNum(m.rollbacks ?? 0), '', (m.rollbacks ? 'warn' : ''), null),
    row('Elapsed', S.startedAt ? fmtDur((Date.now() - S.startedAt) / 1000) : '—', '', '', null),
  ].join('');
  if (m.verified) $('#metrics').querySelectorAll('.value').forEach(v => v.classList.add('tick'));
}

/* ---------- timeline ---------- */
function paintTimeline() {
  const rows = [...S.files.values()].sort((a, b) => a.index - b.index);
  $('#tl-count').textContent = rows.length ? `${rows.length} file${rows.length > 1 ? 's' : ''}` : '';
  if (!rows.length) { $('#timeline').innerHTML = '<div class="tl-empty">No repairs yet.</div>'; return; }
  $('#timeline').innerHTML = rows.map(f => {
    const [kind, ico, word] = OUTCOME[f.outcome] || OUTCOME.active;
    const [dirs, base] = splitPath(f.path);
    const open = S.open.has(f.index);
    const expl = explainError(f.errors || f.error || '');
    return `<div class="tl" data-o="${esc(f.outcome)}">
      <button class="tl-head" data-i="${f.index}" aria-expanded="${open}">
        <span class="tl-ico">${ico}</span>
        <span class="path"><span class="dirs">${esc(dirs)}</span>${esc(base)}</span>
        <span class="tag ${kind}">${esc(word)}${f.attempts > 1 ? ` · ${f.attempts} tries` : ''}</span>
        <span class="when">${f.duration_s != null ? fmtDur(f.duration_s) : ''}</span>
      </button>
      <div class="tl-body" ${open ? '' : 'hidden'}>
        ${f.phase ? `<div class="small muted">Phase: ${f.phase === 'imports' ? 'repairing imports' : 'repairing tests'}${
          f.affected ? ` · explains ${f.affected} failure${f.affected > 1 ? 's' : ''}` : ''}</div>` : ''}
        ${expl ? `<div class="explain">${esc(expl)}</div>` : ''}
        ${f.outcome === 'redirect' && f.redirect_to
          ? `<div class="explain">Root cause is in <code>${esc(f.redirect_to)}</code>. This is a
             redirect, not a repair — nothing in this file changed.</div>` : ''}
        ${(f.attemptLog || []).map(a => {
          const [k, title, why] = VERDICT[a.verdict] || ['flat', a.verdict, ''];
          return `<div>
            <div class="row" style="gap:8px">
              <span class="tag ${k}">${esc(title)}</span>
              <span class="small muted">attempt ${a.attempt}</span>
              ${a.modules_before != null && a.modules_after != null
                ? `<span class="small muted mono">modules ${a.modules_before} → ${a.modules_after}</span>` : ''}
              ${a.tests_before != null && a.tests_after != null
                ? `<span class="small muted mono">tests ${a.tests_before} → ${a.tests_after}</span>` : ''}
            </div>
            ${why ? `<div class="small muted" style="margin-top:3px">${esc(why)}</div>` : ''}
            ${a.detail ? `<pre class="term" style="max-height:160px;margin-top:6px;border-radius:6px">${esc(a.detail)}</pre>` : ''}
          </div>`;
        }).join('')}
        ${f.errors ? `<details><summary class="small muted" style="cursor:pointer">Error the agent was given</summary>
          <pre class="term" style="max-height:200px;margin-top:6px;border-radius:6px">${esc(f.errors)}</pre></details>` : ''}
        ${f.commit ? `<div class="row"><button class="btn ghost sm" data-diff="${esc(f.commit)}">View diff</button>
          <span class="mono small muted">${esc(f.commit)}</span></div>` : ''}
      </div></div>`;
  }).join('');
}

$('#timeline').addEventListener('click', async e => {
  const head = e.target.closest('.tl-head');
  if (head) {
    const i = +head.dataset.i;
    S.open.has(i) ? S.open.delete(i) : S.open.add(i);
    paintTimeline();
    return;
  }
  const diff = e.target.closest('[data-diff]');
  if (diff) {
    const body = diff.closest('.tl-body');
    const sha = diff.dataset.diff;
    diff.disabled = true; diff.textContent = 'Loading…';
    const r = await fetch(`/api/runs/${encodeURIComponent(S.runId)}/diff?commit=${encodeURIComponent(sha)}`);
    const text = r.ok ? await r.text() : 'Not available';
    const pre = document.createElement('pre');
    pre.className = 'term'; pre.style.cssText = 'max-height:320px;margin-top:8px;border-radius:6px';
    pre.textContent = text;
    diff.replaceWith(pre);
  }
});

/* ---------- terminal ---------- */
async function pumpTerminal() {
  if (!S.runId) return;
  try {
    const r = await fetch(`/api/runs/${encodeURIComponent(S.runId)}/terminal?from=${S.termOffset}`);
    if (!r.ok) return;
    const d = await r.json();
    if (d.text) {
      S.termOffset = d.offset;
      const t = $('#term');
      const stick = $('#autoscroll').checked;
      t.insertAdjacentHTML('beforeend', d.text.split('\n').map(line => {
        const c = /INCOMPLETE|Traceback|Error|error:/i.test(line) ? 'err'
          : /COMPLETE|all regression tests pass|all modules import/.test(line) ? 'good'
          : /CANCELLED|QUAR|rolled back/i.test(line) ? 'warn'
          : /^\[\s*\d+\]|^final:|^start:|^codemod:/.test(line) ? 'acc' : '';
        return c ? `<span class="${c}">${esc(line)}</span>` : esc(line);
      }).join('\n'));
      if (stick) t.scrollTop = t.scrollHeight;
    }
  } catch { /* transient */ }
}

/* ---------- event application ---------- */
function applyEvent(ev) {
  S.seq = Math.max(S.seq, ev.seq || 0);
  switch (ev.type) {
    case 'run_started':
      S.startedAt = (ev.t * 1000) || Date.now();
      S.metrics.modules_ok = ev.modules_ok; S.metrics.modules_total = ev.modules_total;
      S.metrics.tests_total = ev.tests_total; S.metrics.tests_passed = 0;
      S.runFacts = ev; paintRunFacts(ev); break;
    case 'stage':
      if (S.stage) S.stagesDone.add(S.stage);
      S.stage = ev.stage; paintStages();
      setNow({ imports: 'Repairing imports', tests: 'Repairing tests',
               preparing: 'Preparing the working copy', codemod: 'Running bump-pydantic',
               dependencies: 'Updating dependency pins', final: 'Final verification' }[ev.stage] || ev.stage);
      break;
    case 'codemod':
      S.metrics.modules_ok = ev.modules_ok;
      setNow(`Codemod changed ${ev.files_changed} file${ev.files_changed === 1 ? '' : 's'}`);
      break;
    case 'metrics':
      if (ev.modules_ok != null) S.metrics.modules_ok = ev.modules_ok;
      if (ev.modules_total != null) S.metrics.modules_total = ev.modules_total;
      if (ev.tests_passed != null) S.metrics.tests_passed = ev.tests_passed;
      if (ev.tests_total != null) S.metrics.tests_total = ev.tests_total;
      break;
    case 'file_started':
      S.files.set(ev.index, { index: ev.index, path: ev.path, phase: ev.phase,
        affected: ev.affected, errors: ev.errors, outcome: 'active', attempts: 0, attemptLog: [] });
      setNow(S.state === 'running' ? 'Repairing' : 'Working', ev.path);
      break;
    case 'model_request':
      setState('waiting');
      setNow(ev.purpose === 'lesson' ? 'Recording what it learned' : 'Waiting for the model', ev.path);
      break;
    case 'model_response': setState('running'); break;
    case 'verifying': setNow('Verifying the edit', ev.path); break;
    case 'attempt': {
      const f = S.files.get(ev.index); if (!f) break;
      f.attempts = Math.max(f.attempts, ev.attempt);
      f.attemptLog.push(ev);
      if (ev.redirect_to) f.redirect_to = ev.redirect_to;
      break;
    }
    case 'file_result': {
      const f = S.files.get(ev.index) || { index: ev.index, path: ev.path, attemptLog: [] };
      Object.assign(f, { outcome: ev.outcome, attempts: ev.attempts, duration_s: ev.duration_s,
        commit: ev.commit || null, redirect_to: ev.redirect_to || f.redirect_to, error: ev.error });
      S.files.set(ev.index, f);
      S.metrics.repaired = [...S.files.values()].filter(x => x.outcome === 'migrated').length;
      S.metrics.rollbacks = [...S.files.values()].reduce((n, x) => n + (x.rollbacks || 0), 0) +
        [...S.files.values()].reduce((n, x) => n + (x.attemptLog || []).filter(a => a.verdict === 'rolled_back').length, 0);
      S.metrics.retries = [...S.files.values()].reduce((n, x) => n + Math.max(0, (x.attempts || 1) - 1), 0);
      break;
    }
    case 'pins': setNow(`Updated ${ev.files.length} dependency file${ev.files.length === 1 ? '' : 's'}`); break;
    case 'final':
    case 'cancelled':
      S.final = ev; S.stagesDone.add(S.stage); S.stage = null;
      if (ev.modules_ok != null) S.metrics.modules_ok = ev.modules_ok;
      if (ev.tests_passed != null) S.metrics.tests_passed = ev.tests_passed;
      if (ev.tests_total) S.metrics.tests_total = ev.tests_total;
      S.metrics.verified = ev.type === 'final' && ev.status === 'complete';
      break;
  }
}
const setNow = (action, file = '') => {
  $('#now-action').textContent = action;
  $('#now-file').textContent = file;
};
function paintRunFacts(ev) {
  $('#run-facts-card').hidden = false;
  $('#run-facts').innerHTML = `
    <dt>Run ID</dt><dd>${esc(ev.run_id)}</dd>
    <dt>Configuration</dt><dd>${esc(ev.config)}</dd>
    <dt>Model</dt><dd>${esc(ev.model)}</dd>
    <dt>Agent commit</dt><dd>${esc(ev.harness || '—')}</dd>
    <dt>Target commit</dt><dd>${esc((ev.target_commit || '').slice(0, 10))}</dd>
    <dt>Branch</dt><dd>${esc(ev.branch || '—')}</dd>`;
}

/* ---------- run state ---------- */
const STATE_TAG = {
  ready: ['flat', 'Ready'], connecting: ['info', 'Connecting'], running: ['info', 'Running'],
  waiting: ['info', 'Waiting for model'], lost: ['bad', 'Connection lost'],
  reconnecting: ['warn', 'Reconnecting'], done: ['flat', 'Finished'],
};
function setState(s) {
  if (S.state === s) return;
  S.state = s;
  const [k, label] = STATE_TAG[s] || STATE_TAG.ready;
  const tag = $('#run-state'); tag.className = `tag ${k}`; tag.textContent = label;
  $('#led-agent').className = `led ${s === 'waiting' || s === 'running' ? 'busy'
    : S.meta?.agent.model_key ? 'on' : 'off'}`;
}

/* ---------- SSE ---------- */
function connect(runId, { live }) {
  S.runId = runId;
  if (S.es) S.es.close();
  setState(live ? 'connecting' : 'running');
  const es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events?from=${S.seq}`);
  S.es = es;

  es.addEventListener('run', e => {
    S.retry = 0;
    if (S.state === 'connecting' || S.state === 'reconnecting') setState('running');
    applyEvent(JSON.parse(e.data));
    paintStages(); paintMetrics(); paintTimeline();
  });
  es.addEventListener('end', () => { es.close(); S.es = null; finish(); });
  es.onerror = () => {
    es.close(); S.es = null;
    if (S.final) return;                       // already finished
    setState(S.retry ? 'reconnecting' : 'lost');
    banner('warn', 'Connection lost', 'Reconnecting — the run keeps going on the server.');
    S.retry++;
    setTimeout(() => connect(runId, { live: true }), Math.min(1000 * 2 ** S.retry, 8000));
  };
}

async function finish() {
  clearInterval(S.timer); S.timer = null;
  clearBanner(); setState('done');
  $('#btn-cancel').hidden = true;
  $('#btn-start').disabled = false;
  $('#start-note').textContent = '';
  await pumpTerminal();
  paintStages(); paintMetrics(); paintTimeline();
  const rec = await (await fetch(`/api/runs/${encodeURIComponent(S.runId)}`)).json();
  paintResults(rec, S.final);
  loadHistory();
}

/* ---------- results ---------- */
function paintResults(rec, finalEv) {
  const status = rec.status || finalEv?.status || 'incomplete';
  const el = $('#results'); el.hidden = false;
  const t = S.meta.targets[rec.target] || {};
  const est = { 'claude-haiku-5.5': [0.10, 0.50], 'claude-sonnet-5.5': [2, 10], 'claude-opus-5.5': [4, 20] };
  const estRows = Object.entries(est).map(([m, [a, b]]) =>
    `<dt>${esc(m)}</dt><dd>$${((rec.input_tokens / 1e6) * a + (rec.output_tokens / 1e6) * b).toFixed(4)}</dd>`).join('');

  const head = status === 'complete'
    ? `<div class="banner ok verified-in"><span class="ico">✓</span><div>
        <b>Verified complete</b>
        <div class="small dim" style="margin-top:3px">Every required module imports and every
        selected regression test passes.</div></div></div>`
    : status === 'cancelled'
    ? `<div class="banner warn"><span class="ico">!</span><div><b>Cancelled</b>
        <div class="small dim" style="margin-top:3px">Stopped on request. Unverified edits were
        discarded; verified commits were kept.</div></div></div>`
    : `<div class="banner warn"><span class="ico">!</span><div><b>Incomplete</b>
        <div class="small dim" style="margin-top:3px">The run finished, but not everything passes.
        What remains is listed below.</div></div></div>`;

  const unresolved = [
    ...(finalEv?.import_failures || []).map(f => [`Module ${f.module}`, f.error]),
    ...(finalEv?.test_failures || []).map(f => [`Test ${f.test}`, f.error]),
  ];

  el.innerHTML = `<div class="stack">
    ${head}
    <section class="card">
      <div class="card-head"><h2>Result</h2><span class="spacer"></span>
        <a class="btn ghost sm" href="/api/runs/${encodeURIComponent(rec.run_id)}/report"
           download>Download report</a></div>
      <div class="card-body grid-setup">
        <div class="stack" style="gap:14px">
          <table>
            <thead><tr><th></th><th>Before</th><th>After</th></tr></thead>
            <tbody>
              <tr><td>Modules importing</td>
                  <td class="mono">${fmtNum(rec.started_modules)} / ${fmtNum(rec.modules_total)}</td>
                  <td class="mono"><b>${fmtNum(rec.modules_ok)} / ${fmtNum(rec.modules_total)}</b></td></tr>
              <tr><td>Selected tests passing</td>
                  <td class="mono">0 / ${fmtNum(rec.tests_total)}</td>
                  <td class="mono"><b>${fmtNum(rec.tests_passed)} / ${fmtNum(rec.tests_total)}</b></td></tr>
            </tbody>
          </table>
          <div class="banner info"><span class="ico">i</span><div class="small">
            <b>Test scope.</b> Only the selected offline regression suite ran
            (${fmtNum(rec.tests_total)} tests). Integration tests that need the hosted
            Steamship API were not executed — their status is unknown.</div></div>
          ${unresolved.length ? `<div class="stack" style="gap:8px">
            <h3>Unresolved (${unresolved.length})</h3>
            ${unresolved.map(([n, e]) => `<div class="explain bad">
              <div class="mono small">${esc(n)}</div>
              <div class="small" style="margin-top:4px">${esc(e.split('\n')[0].slice(0, 220))}</div>
              ${explainError(e) ? `<div class="small muted" style="margin-top:4px">${esc(explainError(e))}</div>` : ''}
            </div>`).join('')}</div>` : ''}
        </div>
        <div class="stack" style="gap:14px">
          <dl class="kv">
            <dt>Run ID</dt><dd>${esc(rec.run_id)}</dd>
            <dt>Agent commit</dt><dd>${esc(rec.harness || '—')}</dd>
            <dt>Target commit</dt><dd>${esc((rec.target_commit || '').slice(0, 10) || '—')}</dd>
            <dt>Result head</dt><dd>${esc(rec.result_head || '—')}</dd>
            <dt>Configuration</dt><dd>${esc(rec.config)}</dd>
            <dt>Model</dt><dd>${esc(rec.model || '—')}</dd>
            <dt>Duration</dt><dd>${fmtDur(rec.duration_s)}</dd>
            <dt>Files repaired</dt><dd>${fmtNum(rec.files_migrated)} of ${fmtNum(rec.files_worked)} worked on</dd>
            <dt>Rollbacks</dt><dd>${fmtNum(rec.rollbacks)}</dd>
            <dt>Tokens</dt><dd>${fmtNum(rec.input_tokens)} in · ${fmtNum(rec.output_tokens)} out</dd>
            <dt>Charged</dt><dd><b>$${(rec.charged_usd ?? 0).toFixed(4)}</b> recorded by the provider</dd>
          </dl>
          <details><summary class="small muted" style="cursor:pointer">Cost estimates at other models</summary>
            <dl class="kv" style="margin-top:8px">${estRows}</dl>
            <p class="small muted" style="margin-top:8px">Estimates only: the measured tokens
            priced at public list rates. Not invoices, and not what this run was charged.</p>
          </details>
          <dl class="kv">
            <dt>neatlogs</dt><dd>${rec.trace_id
              ? `trace <span class="mono">${esc(rec.trace_id.slice(0, 16))}…</span>`
              : 'Not available'}</dd>
            <dt>Entire</dt><dd><a href="https://entire.io/gh/romilp619/python-client/trails/1"
              target="_blank" rel="noopener">Trail #1</a></dd>
          </dl>
        </div>
      </div>
    </section>
  </div>`;
  el.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion:reduce)').matches ? 'auto' : 'smooth',
                      block: 'start' });
}

/* ---------- start / cancel ---------- */
$('#btn-start').addEventListener('click', async () => {
  const btn = $('#btn-start');
  btn.disabled = true; $('#start-note').textContent = 'Starting…';
  Object.assign(S, { seq: 0, stage: null, stagesDone: new Set(), files: new Map(),
                     open: new Set(), metrics: {}, termOffset: 0, final: null, retry: 0,
                     cancelling: false });
  $('#term').textContent = ''; $('#results').hidden = true; clearBanner();
  $('#workspace').hidden = false;
  paintStages(); paintMetrics(); paintTimeline();
  const body = { target: $('#sel-target').value, config: $('#configs input:checked').value };
  const r = await fetch('/api/runs', { method: 'POST', headers: { 'content-type': 'application/json' },
                                       body: JSON.stringify(body) });
  const d = await r.json();
  if (!r.ok) {
    btn.disabled = false; $('#start-note').textContent = '';
    banner('bad', 'Could not start', esc(d.error || 'Unknown error'));
    return;
  }
  $('#start-note').textContent = 'A run is active — starting another is disabled.';
  $('#btn-cancel').hidden = false;
  S.startedAt = Date.now();
  S.timer = setInterval(() => { paintMetrics(); pumpTerminal(); }, 1000);
  connect(d.run_id, { live: true });
});

$('#btn-cancel').addEventListener('click', async () => {
  if (!confirm('Cancel this run? Verified commits are kept; any unverified edit is discarded.')) return;
  S.cancelling = true;
  $('#btn-cancel').disabled = true;
  banner('warn', 'Cancelling', 'Waiting for the agent to stop safely.');
  await fetch(`/api/runs/${encodeURIComponent(S.runId)}/cancel`, { method: 'POST' });
});

$('#btn-term').addEventListener('click', e => {
  const t = $('#term'); t.hidden = !t.hidden; e.target.textContent = t.hidden ? 'Show' : 'Hide';
});
$('#btn-copy').addEventListener('click', async e => {
  await navigator.clipboard.writeText($('#term').textContent);
  e.target.textContent = 'Copied'; setTimeout(() => e.target.textContent = 'Copy', 1400);
});

/* ---------- history ---------- */
let HISTORY = [];
async function loadHistory() {
  const d = await (await fetch('/api/runs')).json();
  HISTORY = d.runs;
  const cfgs = [...new Set(HISTORY.map(r => r.config).filter(Boolean))];
  const sel = $('#filter-config');
  const cur = sel.value;
  sel.innerHTML = '<option value="">all</option>' +
    cfgs.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
  sel.value = cur;
  paintHistory();
}
function paintHistory() {
  const fs = $('#filter-status').value, fc = $('#filter-config').value;
  const rows = HISTORY.filter(r => (!fs || r.status === fs) && (!fc || r.config === fc));
  const tb = $('#history-rows');
  if (!rows.length) {
    tb.innerHTML = `<tr><td colspan="9" style="padding:28px;text-align:center" class="muted">
      ${HISTORY.length ? 'No runs match these filters.' : 'No runs yet. Start one from the Migration page.'}
    </td></tr>`;
    return;
  }
  const TAG = { complete: ['ok', 'Verified complete'], incomplete: ['warn', 'Incomplete'],
                cancelled: ['warn', 'Cancelled'], interrupted: ['bad', 'Interrupted'] };
  tb.innerHTML = rows.map(r => {
    const [k, label] = TAG[r.status] || ['flat', r.status || '—'];
    return `<tr data-run="${esc(r.run_id)}">
      <td><input type="checkbox" class="cmp" value="${esc(r.run_id)}" aria-label="Select ${esc(r.run_id)}"></td>
      <td><span class="tag ${k}">${esc(label)}</span>${r.saved
        ? ' <span class="tag flat" title="From the curated evidence set">Saved run</span>' : ''}</td>
      <td>${esc(r.target || '—')}</td>
      <td class="mono">${esc(r.config || '—')}</td>
      <td class="mono">${new Date(r.mtime * 1000).toLocaleString()}</td>
      <td class="mono">${fmtDur(r.duration_s)}</td>
      <td class="mono">${fmtNum(r.modules_ok)}/${fmtNum(r.modules_total)}</td>
      <td class="mono">${fmtNum(r.tests_passed)}/${fmtNum(r.tests_total)}</td>
      <td class="mono"><button class="btn ghost sm" data-open="${esc(r.run_id)}">${esc(r.run_id)}</button></td>
    </tr>`;
  }).join('');
}
$('#filter-status').addEventListener('change', paintHistory);
$('#filter-config').addEventListener('change', paintHistory);
$('#history-rows').addEventListener('change', () => {
  $('#btn-compare').disabled = $$('#history-rows .cmp:checked').length < 2;
});
$('#history-rows').addEventListener('click', async e => {
  const b = e.target.closest('[data-open]'); if (!b) return;
  const rec = await (await fetch(`/api/runs/${encodeURIComponent(b.dataset.open)}`)).json();
  S.runId = rec.run_id;
  S.files = new Map((rec.timeline || []).map(f => [f.index, { ...f, attemptLog: [] }]));
  S.metrics = { modules_ok: rec.modules_ok, modules_total: rec.modules_total,
                tests_passed: rec.tests_passed, tests_total: rec.tests_total,
                repaired: rec.files_migrated, rollbacks: rec.rollbacks };
  S.startedAt = null; S.final = rec.final_event || null; S.stage = null;
  S.stagesDone = new Set(S.meta.stages.map(s => s.id));
  go('migration');
  $('#workspace').hidden = false;
  banner('info', `Saved run — ${rec.run_id}`,
    'A record of an earlier run. Nothing is executing.');
  setState('done'); paintStages(); paintMetrics(); paintTimeline(); paintRunFacts(rec);
  $('#term').textContent = ''; S.termOffset = 0; pumpTerminal();
  paintResults(rec, rec.final_event);
});
$('#btn-compare').addEventListener('click', () => {
  const ids = $$('#history-rows .cmp:checked').map(c => c.value);
  const rs = ids.map(id => HISTORY.find(r => r.run_id === id)).filter(Boolean);
  const mixedCode = new Set(rs.map(r => r.harness || 'unknown')).size > 1;
  const mixedModel = new Set(rs.map(r => r.model || 'unknown')).size > 1;
  const cell = (r, f) => f(r);
  const rows = [
    ['Outcome', r => r.status], ['Repository', r => r.target], ['Configuration', r => r.config],
    ['Agent commit', r => r.harness || 'not recorded'], ['Model', r => r.model || 'not recorded'],
    ['Target commit', r => (r.target_commit || '').slice(0, 10) || '—'],
    ['Modules', r => `${r.modules_ok}/${r.modules_total}`],
    ['Tests', r => `${r.tests_passed}/${r.tests_total}`],
    ['Rollbacks', r => r.rollbacks], ['Duration', r => fmtDur(r.duration_s)],
    ['Input tokens', r => fmtNum(r.input_tokens)], ['Output tokens', r => fmtNum(r.output_tokens)],
  ];
  $('#compare-out').innerHTML = `<section class="card">
    <div class="card-head"><h2>Comparison</h2></div>
    <div class="card-body stack">
      ${(mixedCode || mixedModel) ? `<div class="banner warn"><span class="ico">!</span><div>
        <b>These runs are not directly comparable.</b>
        <div class="small dim" style="margin-top:3px">They differ in
        ${[mixedCode && 'agent code version', mixedModel && 'model'].filter(Boolean).join(' and ')}.
        A difference between them may be that, not the configuration.</div></div></div>` : ''}
      <div style="overflow:auto"><table>
        <thead><tr><th></th>${rs.map(r => `<th class="mono">${esc(r.run_id)}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(([label, f]) => `<tr><td>${esc(label)}</td>${
          rs.map(r => `<td class="mono">${esc(cell(r, f) ?? '—')}</td>`).join('')}</tr>`).join('')}</tbody>
      </table></div>
    </div></section>`;
  $('#compare-out').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
});

/* ---------- evidence ---------- */
async function loadEvidence() {
  const d = await (await fetch('/api/evidence')).json();
  const na = '<span class="tag flat">Not available</span>';
  const docs = list => list.map(x => `<tr>
      <td>${esc(x.title)}<div class="small muted">${esc(x.note)}</div></td>
      <td class="mono">${esc(x.path)}</td>
      <td>${x.available ? `<span class="tag ok">Present</span>` : na}</td></tr>`).join('');
  const ab = d.migration_records.ablation;
  $('#evidence-out').innerHTML = `
    <section class="card"><div class="card-head"><h2>Migration records</h2></div>
      <div class="card-body stack">
        <dl class="kv">
          <dt>Runs recorded</dt><dd>${d.migration_records.total}</dd>
          <dt>Verified complete</dt><dd>${d.migration_records.complete}</dd>
          <dt>Evidence directory</dt><dd>${esc(d.migration_records.evidence_dir)}</dd>
        </dl>
        ${ab ? `<div class="explain"><b>Final comparison</b> — pass
          <span class="mono">${esc(ab.pass)}</span>, agent <span class="mono">${esc(ab.commit)}</span>,
          model <span class="mono">${esc(ab.model)}</span>.
          <div class="small muted" style="margin-top:4px">${esc(ab.final_note || ab.note || '')}</div>
        </div>` : `<div>${na}</div>`}
      </div></section>

    <section class="card"><div class="card-head"><h2>Test reports</h2></div>
      <table><thead><tr><th>Document</th><th>Path</th><th>Status</th></tr></thead>
      <tbody>${docs(d.test_reports)}</tbody></table></section>

    <section class="card"><div class="card-head"><h2>neatlogs traces</h2></div>
      <div class="card-body stack">
        <div class="row"><span class="tag ${d.neatlogs.configured ? 'ok' : 'warn'}">
          ${d.neatlogs.configured ? 'Configured' : 'Not configured'}</span>
          <a href="${esc(d.neatlogs.console)}" target="_blank" rel="noopener">Open console</a></div>
        <p class="small muted">${esc(d.neatlogs.note)}</p>
        ${d.neatlogs.runs_with_trace.length
          ? `<table><thead><tr><th>Run</th><th>Trace id</th></tr></thead><tbody>${
              d.neatlogs.runs_with_trace.map(r => `<tr><td class="mono">${esc(r.run_id)}</td>
                <td class="mono">${esc(r.trace_id)}</td></tr>`).join('')}</tbody></table>`
          : `<div>${na} — no run has recorded a trace id yet.</div>`}
      </div></section>

    <section class="card"><div class="card-head"><h2>Entire review</h2></div>
      <div class="card-body stack">
        <div><a href="${esc(d.entire.trail)}" target="_blank" rel="noopener">Trail #1</a></div>
        <div class="explain">${esc(d.entire.finding)}</div>
      </div></section>

    <section class="card"><div class="card-head"><h2>Business analysis</h2></div>
      <table><thead><tr><th>Document</th><th>Path</th><th>Status</th></tr></thead>
      <tbody>${docs([d.business])}</tbody></table></section>`;
}

/* ---------- boot ---------- */
$$('.nav-item').forEach(b => b.addEventListener('click', () => go(b.dataset.page)));
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && S.es) return;
  if (e.altKey && ['1', '2', '3'].includes(e.key)) {
    go({ 1: 'migration', 2: 'history', 3: 'evidence' }[e.key]); e.preventDefault();
  }
});

(async function boot() {
  try {
    S.meta = await (await fetch('/api/state')).json();
  } catch {
    banner('bad', 'Dashboard cannot reach its server', 'Is it still running?');
    return;
  }
  paintStatus(S.meta); paintSetup(); paintStages(); paintMetrics();
  if (!S.meta.agent.model_key)
    banner('bad', 'No model API key configured',
      'The server has no model credential, so a run cannot start. Set it in <code>.env</code>.');
  go(location.hash.slice(1) || 'migration');

  // A refresh during a run picks it back up from the event log.
  if (S.meta.active) {
    $('#workspace').hidden = false;
    $('#btn-start').disabled = true;
    $('#btn-cancel').hidden = false;
    $('#start-note').textContent = 'A run is active — starting another is disabled.';
    banner('info', 'Reattached to the run in progress', 'Replaying its events.');
    S.timer = setInterval(() => { paintMetrics(); pumpTerminal(); }, 1000);
    connect(S.meta.active, { live: true });
    setTimeout(clearBanner, 2500);
  }
})();
