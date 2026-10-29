/* 渲染：把状态画到页面上。这个模块不发起请求，也不改状态（点击回调除外）。 */

import { $, S, lastStage } from './state.js';

export const STAMP = {
  pending: ['等待', 'is-live'],
  running: ['正在换', 'is-live'],
  passed: ['通过', 'is-pass'],
  // reworked = 试了不止一次、最后还是没过（选中的那张也没通过），别写成"返工通过"
  reworked: ['返工未过', 'is-rework'],
  rejected: ['没换成', 'is-rejected'],
  failed: ['失败', 'is-rejected'],
};

const CHECK_LABELS = {
  face_preserved: '脸没变',
  garment_applied: '衣服换上了',
  hand_preserved: '手还在',
  background_preserved: '背景没动',
  no_extra_person: '没有多余的人',
};

const CHECK_ORDER = ['face_preserved', 'garment_applied', 'hand_preserved',
                     'background_preserved', 'no_extra_person'];

export function hint(text, isError) {
  const el = $('hint');
  el.textContent = text;
  el.classList.toggle('is-error', !!isError);
}

/** 开始按钮的可用状态 + 提示语。这是"能不能开跑"的唯一判断处。 */
export function syncRun() {
  const pending = S.garments.filter((g) => g.state !== 'done');
  const ready = !!S.person && pending.length > 0 && !S.running;
  const btn = $('run');
  btn.disabled = !ready;
  btn.textContent = S.running ? '换装中…' : '开始换';

  if (S.running) return;
  if (!S.person && !S.garments.length) hint('先放一张人像，再放一张要换的衣服。');
  else if (!S.person) hint('还差一张人像。');
  else if (!S.garments.length) hint('还差一张要换的衣服。');
  else if (ready) hint(`两张都放好了，点「开始换」。要换 ${pending.length} 件。`);
  else hint('这批都换完了。想再换一件，继续往左边放图。');
}

export function render() {
  renderRail();
  renderSheet();
  renderMetrics();
  syncBatch();
  if (S.selected) {
    const c = S.cases.find((x) => x.index === S.selected);
    if (c) renderDocket(c);
  }
}

function resetRailText() {
  document.querySelectorAll('.step').forEach((el) => {
    el.classList.remove('is-active', 'is-done');
    el.querySelector('.step-time').textContent = '—';
  });
}

function renderRail() {
  const live = S.live;
  if (!live) {
    resetRailText();
    $('rail-case').textContent = '还没开始';
    $('rail-num').textContent = '—';
    return;
  }

  $('rail-case').textContent =
    `第 ${live.index} / ${S.cases.length} 件 · ${live.garment || ''}`;
  $('rail-num').textContent = S.elapsed ? S.elapsed.toFixed(1) + 's' : '—';

  const gen = lastStage(live, 'generate');
  const jud = lastStage(live, 'judge');
  const running = S.running || live.state === 'running';

  const set = (name, state, time) => {
    const el = document.querySelector('.step[data-step="' + name + '"]');
    el.classList.toggle('is-active', state === 'active');
    el.classList.toggle('is-done', state === 'done');
    el.querySelector('.step-time').textContent = time || '—';
  };

  set('submit', gen ? 'done' : running ? 'active' : 'pending', gen ? '✓' : null);
  set('generate', gen ? 'done' : running ? 'active' : 'pending',
      gen && gen.ok ? gen.latency_s.toFixed(0) + 's' : null);
  set('judge', jud ? 'done' : gen ? 'active' : 'pending',
      jud ? jud.latency_s.toFixed(1) + 's' : null);
  set('accept',
      live.state !== 'running' && !running ? 'done' : jud ? 'active' : 'pending',
      jud ? (jud.passed ? '通过' : (jud.failures || []).length + ' 项不过') : null);
}

function renderSheet() {
  const sheet = $('sheet');
  if (!S.cases.length) {
    if (!sheet.dataset.idle) {
      sheet.innerHTML = '<p class="sheet-empty">把两张图放进左边，换好的样子会出现在这里。</p>';
      sheet.classList.add('is-empty');
      sheet.dataset.idle = '1';
    }
    return;
  }
  delete sheet.dataset.idle;
  sheet.innerHTML = '';
  sheet.classList.remove('is-empty');

  S.cases.forEach((c) => {
    const gen = lastStage(c, 'generate');
    const [text, cls] = STAMP[c.state] || STAMP.pending;

    const cell = document.createElement('button');
    cell.type = 'button';
    cell.className = 'cell';
    cell.setAttribute('aria-label',
      `第 ${c.index} 件 ${c.garment || ''}，${text}`);

    let thumb = null;
    if (gen && gen.image_url) {
      const img = document.createElement('img');
      img.className = 'cell-img';
      img.src = gen.image_url;
      img.alt = `第 ${c.index} 件的换装结果`;
      img.width = 768;
      img.height = 1344;
      cell.append(img);
      thumb = img;
    } else {
      const v = document.createElement('span');
      v.className = 'cell-void';
      v.textContent = c.state === 'pending' ? '排队' : '正在换';
      cell.append(v);
    }

    const cap = document.createElement('span');
    cap.className = 'cell-cap';
    const idx = document.createElement('b');
    idx.textContent = String(c.index).padStart(2, '0');
    const nm = document.createElement('span');
    nm.textContent = c.garment || '';
    cap.append(idx, nm);
    cell.append(cap);

    const st = document.createElement('span');
    st.className = 'stamp ' + cls + (c.state === 'passed' ? ' landed' : '');
    st.textContent = text;
    st.setAttribute('aria-hidden', 'true');
    cell.append(st);

    if (thumb && S.personUrl) {
      holdToCompare(cell, thumb);
      cell.title = '点开看检验单；按住看原片';
    }

    cell.addEventListener('click', () => {
      S.selected = c.index;
      renderDocket(c);
    });
    sheet.append(cell);
  });
}

function renderDocket(c) {
  const box = $('docket');
  box.hidden = false;
  $('docket-title').textContent = `第 ${String(c.index).padStart(2, '0')} 件`;

  const gen = lastStage(c, 'generate');
  const link = $('save-link');
  if (gen && gen.image_url) {
    link.href = gen.image_url;
    const base = (c.garment || 'result').replace(/\.[^.]+$/, '');
    link.setAttribute('download', `换装_${String(c.index).padStart(2, '0')}_${base}.png`);
    link.hidden = false;
  } else {
    link.hidden = true;
  }

  const body = $('docket-body');
  body.innerHTML = '';

  const jud = lastStage(c, 'judge');
  const grid = document.createElement('div');
  grid.className = 'check-grid';
  CHECK_ORDER.forEach((k) => {
    const r = (jud && jud.checks && jud.checks[k]) || {};
    const row = document.createElement('div');
    const state = r.pass === true ? 'is-pass' : r.pass === false ? 'is-fail' : 'is-none';
    row.className = 'check ' + state;
    const mark = document.createElement('span');
    mark.className = 'check-mark';
    mark.textContent = r.pass === true ? '✓' : r.pass === false ? '✕' : '—';
    const label = document.createElement('span');
    label.className = 'check-label';
    label.textContent = CHECK_LABELS[k];
    row.append(mark, label);
    row.title = r.reason || '';
    grid.append(row);
  });
  body.append(grid);

  if (jud && jud.note) {
    const n = document.createElement('p');
    n.className = 'docket-note';
    n.textContent = jud.note;
    body.append(n);
  }

  const detail = document.createElement('details');
  detail.className = 'raw';
  const sum = document.createElement('summary');
  sum.textContent = '看每轮的技术细节';
  detail.append(sum);
  const ul = document.createElement('ul');
  ul.className = 'attempts';
  (c.attempts || []).forEach((a) => {
    const li = document.createElement('li');
    const tag = a.mode === 'escape' ? ' · 降级重跑' : '';
    if (a.stage === 'generate') {
      li.textContent = a.ok
        ? `第 ${a.attempt} 次${tag} · 生成 ${a.latency_s.toFixed(1)}s · seed ${a.seed ?? '—'}`
        : `第 ${a.attempt} 次${tag} · 生成失败（${a.error_kind || '未知'}）`;
    } else {
      li.textContent = `第 ${a.attempt} 次${tag} · 检查${a.passed ? '通过' : '不过 ' + (a.failures || []).length + ' 项'} · ${a.latency_s.toFixed(1)}s`;
    }
    ul.append(li);
  });
  detail.append(ul);
  body.append(detail);
}

function renderMetrics() {
  const m = S.metrics || {};
  const pct = (v) => (v == null ? '—' : Math.round(v * 100) + '%');
  $('m-final').textContent = pct(m.final_pass_rate);
  $('m-first').textContent = pct(m.first_pass_rate);
  $('m-att').textContent = m.avg_attempts != null
    ? (m.escape_attempts ? `${m.avg_attempts}（降级 ${m.escape_attempts} 次）` : m.avg_attempts)
    : '—';
  $('m-lat').textContent = m.avg_generate_s ? m.avg_generate_s + 's' : '—';
  $('m-total').textContent = m.total_generate_s ? m.total_generate_s + 's' : '—';
}


/** 按住格子换成原片，松开换回来。按下先等 120ms，避免普通点击闪一下。 */
function holdToCompare(cell, img) {
  if (!img) return;
  let timer = null;
  let showing = false;
  let saved = '';

  const show = () => {
    timer = setTimeout(() => {
      saved = img.src;
      img.src = S.personUrl;
      cell.classList.add('tip-original');
      showing = true;
    }, 120);
  };

  const hide = () => {
    clearTimeout(timer);
    if (!showing) return;
    img.src = saved;
    cell.classList.remove('tip-original');
    showing = false;
  };

  cell.addEventListener('pointerdown', show);
  cell.addEventListener('pointerup', hide);
  cell.addEventListener('pointerleave', hide);
  cell.addEventListener('pointercancel', hide);
}

/** 整批下载：有图才出现，指向当前这次任务。 */
function syncBatch() {
  const a = $('batch');
  const has = S.cases.some((c) => c.final_image || c.final_url);
  a.hidden = !(has && S.job);
  if (has && S.job) a.href = '/api/export?job=' + S.job;
}

/** 存档列表：一行一次，日期在最左。 */
export function renderLedger(items) {
  const ul = $('ledger-list');
  ul.innerHTML = '';
  if (!items.length) {
    const li = document.createElement('li');
    li.className = 'ledger-empty';
    li.textContent = '还没有跑过的单子。左边放两张图，跑一次就有了。';
    ul.append(li);
    return;
  }
  items.forEach((j) => {
    const li = document.createElement('li');
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'ledger-row';

    const when = document.createElement('span');
    when.className = 'ledger-when';
    when.textContent = (j.ts || '').replace('T', ' ').slice(5, 16) || '—';

    const what = document.createElement('span');
    what.className = 'ledger-what';
    what.textContent = (j.garments || []).join('、') || '—';
    const small = document.createElement('small');
    small.textContent = `${j.cases} 件 · ${duration(j.elapsed_s)}`;
    what.append(small);

    const pass = document.createElement('span');
    const all = j.passed === j.cases;
    pass.className = 'ledger-pass' + (all ? ' is-all' : j.passed ? '' : ' is-none');
    pass.textContent = `通过 ${j.passed}/${j.cases}`;

    row.append(when, what, pass);
    row.addEventListener('click', () => { location.href = '/?job=' + j.id; });
    li.append(row);
    ul.append(li);
  });
}

function duration(seconds) {
  if (!seconds) return '—';
  if (seconds < 60) return Math.round(seconds) + ' 秒';
  return (seconds / 60).toFixed(1) + ' 分钟';
}
