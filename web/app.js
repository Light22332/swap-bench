/* 换衣服 · 前端
   设计目标：不需要指令、不需要点按钮。放两张图，自动出结果。
   实现上就是一个状态机：人像 + 待处理的衣服 → 自动提交 → 轮询 → 合并进结果墙。 */

const S = {
  person: null,
  garments: [],     // {path, url, name, state: 'pending'|'done'}
  cases: [],        // 累积的结果，跨多次提交
  job: null,
  timer: null,
  running: false,
  selected: null,
  metrics: null,
  judgeMode: null,
  elapsed: 0,
  live: null,
  jobStart: 0,
  defaultInstruction: '',
};

const $ = (id) => document.getElementById(id);

/* ---------- 启动 ---------- */

async function boot() {
  try {
    const cfg = await fetch('/api/config').then((r) => r.json());
    S.defaultInstruction = cfg.instruction || '';
    $('instruction').value = S.defaultInstruction;
    $('backend-tag').textContent = cfg.backend === 'cloud' ? '云端' : '本地';

    const tag = $('judge-tag');
    const j = cfg.judge || {};
    const names = [];
    if (j.face_models) names.push('脸没变');
    names.push('衣服换上了');
    if (j.hand_models) names.push('手还在');
    names.push('背景没动');
    if (j.face_models) names.push('没有多余的人');
    tag.textContent = `自动检查 ${names.length} 项`;
    tag.title = names.join('、') + '。文字水印需人看一眼';
    if (names.length < 5) tag.classList.add('is-warn');
  } catch (e) {
    hint('连不上服务：' + e.message, true);
    return;
  }

  const q = new URLSearchParams(location.search).get('job');
  if (q) {
    await loadHistory(q);
  } else {
    syncRun();
  }

  // ?demo 把示例图灌进去并直接开跑，给演示和截图用
  if (new URLSearchParams(location.search).has('demo')) $('demo').click();
}

async function loadHistory(id) {
  try {
    const job = await fetch('/api/job/' + id).then((r) => r.json());
    if (!job || !job.cases) throw new Error('没有这次记录');
    S.cases = job.cases;
    S.metrics = job.metrics;
    S.judgeMode = job.metrics && job.metrics.judge_mode;
    S.elapsed = job.elapsed_s;
    S.live = S.cases[S.cases.length - 1];
    const which = new URLSearchParams(location.search).get('case');
    if (which) S.selected = Number(which);
    render();
    syncRun();
    hint('这是一次已经跑完的记录。想自己试，就在左边放两张图，然后点「开始换」。');
  } catch (e) {
    hint('读取记录失败：' + e.message, true);
  }
}

/* ---------- 上传 ---------- */

function toDataURL(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
}

async function upload(file) {
  const data = await toDataURL(file);
  const res = await fetch('/api/upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: file.name, data }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || res.statusText);
  return body;
}

const isImage = (f) => f && f.type && f.type.startsWith('image/');

async function addPerson(file) {
  if (!isImage(file)) {
    hint('这个文件不是图片，换一张试试。', true);
    return;
  }
  try {
    const up = await upload(file);
    S.person = { path: up.path, url: up.url, name: file.name };
    const img = $('preview-person');
    img.src = up.url;
    img.hidden = false;
    $('slot-person').querySelector('.slot-empty').hidden = true;
    // 换了人，之前的结果就不再对应，清掉
    S.cases = [];
    S.garments.forEach((g) => { g.state = 'pending'; });
    renderChips();
    syncRun();
  } catch (e) {
    hint('人像没传上去：' + e.message, true);
  }
}

async function addGarments(files) {
  const list = files.filter(isImage);
  if (!list.length) {
    hint('这些文件不是图片，换几张试试。', true);
    return;
  }
  for (const f of list) {
    try {
      const up = await upload(f);
      S.garments.push({ path: up.path, url: up.url, name: f.name, state: 'pending' });
    } catch (e) {
      hint('衣服没传上去：' + e.message, true);
    }
  }
  renderChips();
  syncRun();
}

function renderChips() {
  const ul = $('garment-chips');
  ul.innerHTML = '';
  S.garments.forEach((g, i) => {
    const li = document.createElement('li');
    li.className = 'chip' + (g.state === 'done' ? ' is-done' : '');

    const im = document.createElement('img');
    im.className = 'chip-thumb';
    im.src = g.url;
    im.alt = '';
    im.width = 26;
    im.height = 34;

    const sp = document.createElement('span');
    sp.className = 'chip-name';
    sp.textContent = String(i + 1).padStart(2, '0') + ' ' + g.name;

    const rm = document.createElement('button');
    rm.className = 'close';
    rm.type = 'button';
    rm.textContent = '×';
    rm.setAttribute('aria-label', '去掉这件：' + g.name);
    rm.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      S.cases = S.cases.filter((c) => c._path !== g.path);
      S.cases.forEach((c, k) => { c.index = k + 1; });
      S.garments.splice(i, 1);
      renderChips();
      render();
    });

    li.append(im, sp, rm);
    ul.append(li);
  });
  $('garment-count') && ($('garment-count').textContent = S.garments.length);
}

/* ---------- 手动开始 ---------- */

function hint(text, isError) {
  const el = $('hint');
  el.textContent = text;
  el.classList.toggle('is-error', !!isError);
}

function pendingGarments() {
  return S.garments.filter((g) => g.state !== 'done');
}

function syncRun() {
  const pending = pendingGarments();
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

function startRun() {
  const pending = pendingGarments();
  if (!S.person || !pending.length || S.running) return;
  runPending(pending);
}

async function runPending(pending) {
  S.running = true;
  syncRun();
  $('rerun').hidden = true;
  $('docket').hidden = true;
  S.jobStart = S.cases.length;
  hint('开始换，第一张要等模型加载，大概一两分钟…');
  if (!S.cases.length) {
    $('sheet').innerHTML = '<p class="sheet-empty">正在换第一件…</p>';
    $('sheet').classList.add('is-empty');
  }

  const instruction = $('instruction').value.trim() || S.defaultInstruction;
  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        person: S.person.path,
        garments: pending.map((g) => ({ path: g.path, name: g.name })),
        instruction,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '提交失败');
    S.job = data.job_id;
    S.pendingPaths = pending.map((g) => g.path);
    poll();
  } catch (e) {
    hint('提交失败：' + e.message, true);
    finishRun();
  }
}

function poll() {
  clearTimeout(S.timer);
  S.timer = setTimeout(async () => {
    try {
      const job = await fetch('/api/job/' + S.job).then((r) => r.json());
      merge(job);
      render();
      if (job.state === 'running' || job.state === 'pending') {
        hint(progressText(job));
        poll();
      } else {
        finishRun(job);
      }
    } catch (e) {
      hint('连接断了：' + e.message, true);
      finishRun();
    }
  }, 1500);
}

function merge(job) {
  const mapped = job.cases.map((c, i) => ({
    ...c,
    index: S.jobStart + i + 1,
    _path: (S.pendingPaths && S.pendingPaths[i]) || null,
  }));
  S.cases = S.cases.slice(0, S.jobStart).concat(mapped);
  S.live = mapped.find((c) => c.state === 'running') || mapped[mapped.length - 1] || null;
  S.elapsed = job.elapsed_s;
  if (job.metrics && job.state === 'done') {
    S.metrics = job.metrics;
    S.judgeMode = job.metrics.judge_mode;
  }
}

function progressText(job) {
  const live = job.cases.find((c) => c.state === 'running') || job.cases[job.cases.length - 1];
  if (!live) return '准备中…';
  const gen = lastStage(live, 'generate');
  const jud = lastStage(live, 'judge');
  if (!gen) return `第 ${live.index} 件：正在生成…`;
  if (!jud) return `第 ${live.index} 件：正在检查…`;
  return `第 ${live.index} 件：${jud.passed ? '通过' : '在返工'}…`;
}

function finishRun(job) {
  S.running = false;
  if (job && job.state === 'done') {
    const ok = S.cases.filter((c) => c.passed).length;
    S.garments.forEach((g) => { g.state = 'done'; });
    renderChips();
    syncRun();
    hint(`换好了：${ok}/${S.cases.length} 张可用。点图看大图、保存。`);
  } else {
    syncRun();
    hint(job && job.error ? '出错了：' + job.error : '没跑完，可以点「重新跑一次」。', true);
  }
  $('rerun').hidden = S.cases.length === 0;
  render();
}

/* ---------- 渲染 ---------- */

function lastStage(c, stage) {
  for (let i = c.attempts.length - 1; i >= 0; i--) {
    if (c.attempts[i].stage === stage) return c.attempts[i];
  }
  return null;
}

function render() {
  renderRail();
  renderSheet();
  renderMetrics();
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

const STAMP = {
  pending: ['等待', 'is-live'],
  running: ['正在换', 'is-live'],
  passed: ['通过', 'is-pass'],
  // reworked = 试了不止一次、最后还是没过（选中的那张也没通过），别写成"返工通过"
  reworked: ['返工未过', 'is-rework'],
  rejected: ['没换成', 'is-rejected'],
  failed: ['失败', 'is-rejected'],
};

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

    if (gen && gen.image_url) {
      const img = document.createElement('img');
      img.className = 'cell-img';
      img.src = gen.image_url;
      img.alt = `第 ${c.index} 件的换装结果`;
      img.width = 768;
      img.height = 1344;
      cell.append(img);
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

    cell.addEventListener('click', () => {
      S.selected = c.index;
      renderDocket(c);
    });
    sheet.append(cell);
  });
}

const CHECK_LABELS = {
  face_preserved: '脸没变',
  garment_applied: '衣服换上了',
  hand_preserved: '手还在',
  background_preserved: '背景没动',
  no_extra_person: '没有多余的人',
};

const CHECK_ORDER = ['face_preserved', 'garment_applied', 'hand_preserved',
                     'background_preserved', 'no_extra_person'];

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
    if (a.stage === 'generate') {
      li.textContent = a.ok
        ? `第 ${a.attempt} 次 · 生成 ${a.latency_s.toFixed(1)}s · seed ${a.seed ?? '—'}`
        : `第 ${a.attempt} 次 · 生成失败（${a.error_kind || '未知'}）`;
    } else {
      li.textContent = `第 ${a.attempt} 次 · 检查${a.passed ? '通过' : '不过 ' + (a.failures || []).length + ' 项'} · ${a.latency_s.toFixed(1)}s`;
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
  $('m-att').textContent = m.avg_attempts != null ? m.avg_attempts : '—';
  $('m-lat').textContent = m.avg_generate_s ? m.avg_generate_s + 's' : '—';
  $('m-total').textContent = m.total_generate_s ? m.total_generate_s + 's' : '—';
}

/* ---------- 交互 ---------- */

/* label 里包着 input，点哪都会原生唤起文件选择，不用再手动 click() */

$('file-person').addEventListener('change', (ev) => {
  if (ev.target.files[0]) addPerson(ev.target.files[0]);
  ev.target.value = '';
});

$('file-garment').addEventListener('change', (ev) => {
  const files = [...ev.target.files];
  if (files.length) addGarments(files);
  ev.target.value = '';
});

$('docket-close').addEventListener('click', () => { $('docket').hidden = true; });

$('run').addEventListener('click', startRun);

$('demo').addEventListener('click', async () => {
  try {
    const d = await fetch('/api/samples', { method: 'POST' }).then((r) => r.json());
    if (!d.ok) throw new Error(d.error || '没有示例图');
    S.person = { path: d.person.path, url: d.person.url, name: d.person.name };
    S.cases = [];
    S.garments = d.garments.map((g) => ({ path: g.path, url: g.url, name: g.name, state: 'pending' }));
    const img = $('preview-person');
    img.src = S.person.url;
    img.hidden = false;
    $('slot-person').querySelector('.slot-empty').hidden = true;
    renderChips();
    syncRun();
    startRun();
  } catch (e) {
    hint('载入示例失败：' + e.message, true);
  }
});

$('rerun').addEventListener('click', () => {
  S.garments.forEach((g) => { g.state = 'pending'; });
  S.cases = [];
  renderChips();
  syncRun();
  startRun();
});

/* 拖拽：整页都能接，落到哪个槽都能用 */

function wireDrop(el, handler) {
  if (!el) return;
  el.addEventListener('dragover', (e) => {
    e.preventDefault();
    el.classList.add('is-over');
  });
  el.addEventListener('dragleave', () => el.classList.remove('is-over'));
  el.addEventListener('drop', (e) => {
    e.preventDefault();
    el.classList.remove('is-over');
    const files = [...(e.dataTransfer ? e.dataTransfer.files : [])].filter(isImage);
    if (files.length) handler(files);
  });
}

wireDrop($('slot-person'), (files) => addPerson(files[0]));
wireDrop($('slot-garment'), (files) => addGarments(files));
wireDrop(document.body, (files) => {
  // 落在空白处：先当人像，人像有了就当衣服
  const imgs = files.filter(isImage);
  if (!imgs.length) return;
  if (!S.person) addPerson(imgs[0]);
  else addGarments(imgs);
});

document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('drop', (e) => e.preventDefault());

boot();
