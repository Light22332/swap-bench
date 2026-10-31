/* 渲染：把状态画到页面上。这个模块不发起请求，也不改状态（点击回调除外）。 */

import { $, S, lastStage } from './state.js';
import { srcset, thumb } from './img.js';

// 格子在 1440 宽屏上大约 390px，手机上占一列；给浏览器一份尺寸提示，
// 它才会挑 400/800/1200 里合适的那张，不至于把 3.6MB 原图拉下来
const CELL_SIZES = '(max-width: 640px) 92vw, (max-width: 1100px) 46vw, 28vw';
const CELL_WIDTHS = [400, 800, 1200];

export const STAMP = {
  pending: ['等待', 'is-live'],
  running: ['正在换', 'is-live'],
  passed: ['通过', 'is-pass'],
  // reworked = 试了不止一次、最后还是没过（选中的那张也没通过），别写成"返工通过"
  reworked: ['返工未过', 'is-rework'],
  rejected: ['没换成', 'is-rejected'],
  failed: ['失败', 'is-rejected'],
  cancelled: ['停下了', 'is-live'],
  // 进程被杀、没写出 job_end 的那单：不是 done，也不该写成"通过"
  interrupted: ['中断了', 'is-rejected'],
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
  $('stop').hidden = !S.running;

  if (S.running) return;
  if (!S.person && !S.garments.length) hint('先放一张人像，再放一张要换的衣服。');
  else if (!S.person) hint('还差一张人像。');
  else if (!S.garments.length) hint('还差一张要换的衣服。');
  else if (ready) hint(`两张都放好了，点「开始换」。要换 ${pending.length} 件。`);
  else hint('这批都换完了。想再换一件，继续往左边放图。');
}

export function render() {
  renderSheet();
  syncBatch();
  if (S.selected) {
    const c = S.cases.find((x) => x.index === S.selected);
    if (c) renderDocket(c);
  }
}

/** 关掉检验单。必须一起清 S.selected，否则下一次 render 又把它画回来。 */
export function closeDocket() {
  S.selected = null;
  $('docket').hidden = true;
}

function renderSheet() {
  const sheet = $('sheet');
  if (!S.cases.length) {
    if (!sheet.dataset.idle) {
      sheet.innerHTML = '<p class="sheet-empty">放好两张图，换好的样子会出现在这里。</p>';
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

    const frame = document.createElement('span');
    frame.className = 'cell-frame';

    let imgEl = null;
    if (gen && gen.image_url) {
      const img = document.createElement('img');
      img.className = 'cell-img';
      img.alt = `第 ${c.index} 件的换装结果`;
      img.loading = 'lazy';
      img.decoding = 'async';
      img.sizes = CELL_SIZES;
      img.srcset = srcset(gen.image_url, CELL_WIDTHS);
      img.src = thumb(gen.image_url, 800);
      frame.append(img);
      imgEl = img;
    } else {
      const v = document.createElement('span');
      v.className = 'cell-void';
      v.textContent = c.state === 'pending' ? '排队'
        : c.state === 'cancelled' ? '没跑'
        : c.state === 'interrupted' ? '中断了' : '正在换';
      frame.append(v);
    }

    const no = document.createElement('span');
    no.className = 'cell-no';
    no.textContent = String(c.index).padStart(2, '0');
    frame.append(no);

    const st = document.createElement('span');
    st.className = 'stamp ' + cls + (c.state === 'passed' ? ' landed' : '');
    st.textContent = text;
    st.setAttribute('aria-hidden', 'true');
    frame.append(st);

    const cap = document.createElement('span');
    cap.className = 'cell-cap';
    const nm = document.createElement('b');
    nm.textContent = c.garment || '';
    cap.append(nm);

    cell.append(frame, cap);

    if (imgEl && S.personUrl) {
      holdToCompare(cell, imgEl);
      cell.title = '点开看检验单；按住看原片';
      cell.setAttribute('aria-label', cell.getAttribute('aria-label') + '，空格键切换原片');
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
  const wasHidden = box.hidden;
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
  // 每 1.5 秒会重画一次，技术细节如果展开着，重画后要还是展开的
  const rawOpen = !!body.querySelector('details.raw')?.open;
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
  detail.open = rawOpen;
  const sum = document.createElement('summary');
  sum.textContent = '看每轮的技术细节';
  detail.append(sum);
  const ul = document.createElement('ul');
  ul.className = 'attempts';
  (c.attempts || []).forEach((a) => {
    const li = document.createElement('li');
    const tag = a.mode === 'escape' ? ' · 降级重跑' : '';
    if (a.stage === 'generate') {
      const spent = a.cost ? ` · ${money(a.cost, curOf())}` : '';
      li.textContent = a.ok
        ? `第 ${a.attempt} 次${tag} · 生成 ${a.latency_s.toFixed(1)}s · seed ${a.seed ?? '—'}${spent}`
        : `第 ${a.attempt} 次${tag} · 生成失败（${a.error_kind || '未知'}）`;
    } else {
      li.textContent = `第 ${a.attempt} 次${tag} · 检查${a.passed ? '通过' : '不过 ' + (a.failures || []).length + ' 项'} · ${a.latency_s.toFixed(1)}s`;
    }
    ul.append(li);
  });
  detail.append(ul);
  body.append(detail);

  // 一批的汇总收在这里：主界面上一个数字都不放，想看才点开
  const m = S.metrics || {};
  if (m.cases) {
    const pct = (v) => (v == null ? '—' : Math.round(v * 100) + '%');
    const line = document.createElement('p');
    line.className = 'docket-metrics';
    line.textContent = [
      `这批 ${m.cases} 件`,
      `合格 ${pct(m.final_pass_rate)}`,
      `首轮 ${pct(m.first_pass_rate)}`,
      `平均重试 ${m.avg_attempts}`,
      `平均生成 ${m.avg_generate_s}s`,
      m.total_cost ? `本次 ${money(m.total_cost, m.cost_currency)}` : '',
    ].filter(Boolean).join(' · ');
    body.append(line);
  }

  // 刚打开时把它滚进视野：手机上详情可能整整在下面一屏，不滚一下会以为点了没反应。
  // 用 nearest，桌面上本来就看得见时不乱跳。
  if (wasHidden) box.scrollIntoView({ block: 'nearest' });
}

/** 钱的写法：美元用 $，人民币用 ¥；不到 1 块留三位小数，免得每张都显示 0.04。 */
export function money(v, cur) {
  if (!v) return '';
  const sym = cur === 'CNY' ? '¥' : '$';
  return sym + (v >= 1 ? v.toFixed(2) : v.toFixed(3));
}

function curOf() {
  return (S.metrics && S.metrics.cost_currency) || 'USD';
}

/** 按住格子换成原片，松开换回来。按下先等 120ms，避免普通点击闪一下。 */
function holdToCompare(cell, img) {
  if (!img) return;
  let timer = null;
  let showing = false;
  let saved = null;        // [src, srcset]：srcset 也要存，不然换回来只剩一张小图

  const swapIn = () => {
    saved = [img.src, img.srcset];
    img.removeAttribute('srcset');
    img.removeAttribute('sizes');
    img.src = thumb(S.personUrl, 1200);
    cell.classList.add('tip-original');
    showing = true;
  };

  const swapOut = () => {
    if (!showing) return;
    img.src = saved ? saved[0] : '';
    if (saved && saved[1]) img.srcset = saved[1];
    img.sizes = CELL_SIZES;
    cell.classList.remove('tip-original');
    showing = false;
    saved = null;
  };

  const show = () => {
    timer = setTimeout(swapIn, 120);
  };

  const hide = () => {
    clearTimeout(timer);
    swapOut();
  };

  cell.addEventListener('pointerdown', show);
  cell.addEventListener('pointerup', hide);
  cell.addEventListener('pointerleave', hide);
  cell.addEventListener('pointercancel', hide);

  // 键盘等价物：空格切换。不拦的话空格会触发按钮点击、把检验单打开
  cell.addEventListener('keydown', (ev) => {
    if (ev.key !== ' ' && ev.key !== 'Spacebar') return;
    ev.preventDefault();
    clearTimeout(timer);
    if (showing) swapOut();
    else swapIn();
  });
  cell.addEventListener('blur', hide);
}

/** 整批下载：这一批跑完才出现，指向当前这次任务。 */
function syncBatch() {
  const a = $('batch');
  const has = S.cases.some((c) => c.final_image || c.final_url);
  // 还在跑的时候先别给下载：zip 里只会有一部分图，点进去容易以为缺了
  a.hidden = !(has && S.job && !S.running);
  if (!a.hidden) a.href = '/api/export?job=' + S.job;
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
    small.textContent = `${j.cases} 件 · ${duration(j.elapsed_s)}`
      + (j.cost ? ` · ${money(j.cost, (S.metrics && S.metrics.cost_currency) || 'USD')}` : '');
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
