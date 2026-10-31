/* 启动与事件绑定：这是唯一碰"页面怎么动起来"的文件。

启动顺序：读配置 → 有 ?job= 就还原历史，否则等用户放图 → ?demo 直接跑示例。 */

import { getConfig, getHistory, getJob, getMetrics, loadSamples, uploadFile, extractGarment } from './api.js';
import { $, S } from './state.js';
import { hint, money, render, renderLedger, syncRun } from './render.js';
import { addGarments, addPerson, isImage, renderChips, wireDrop } from './upload.js';
import { startRun, stopRun } from './run.js';
import { initSettings } from './settings.js';
import { refreshCostTag } from './cost.js';
import { thumb } from './img.js';
import { show as showViewer } from './viewer.js';

async function boot() {
  try {
    const cfg = await getConfig();
    $('backend-tag').textContent = cfg.backend === 'cloud' ? '云端' : '本地';
    $('backend-tag').title = cfg.backend === 'cloud'
      ? '用云端接口，按张计费' : '用本机的 ComfyUI，不花钱';
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

  // ?demo 只是把示例图放好，仍然要人自己点「开始换」
  if (new URLSearchParams(location.search).has('demo')) $('demo').click();

  refreshCostTag();
}

async function loadHistory(id) {
  try {
    const job = await getJob(id);
    if (!job || !job.cases) throw new Error('没有这次记录');
    S.cases = job.cases;
    S.metrics = job.metrics;
    S.judgeMode = job.metrics && job.metrics.judge_mode;
    S.elapsed = job.elapsed_s;
    S.job = job.id;
    S.personUrl = job.person_url || null;
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

/* ---------- 事件 ---------- */

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
$('stop').addEventListener('click', stopRun);

// 从一张人物照片里把衣服抠出来，抠好直接进衣服槽
$('extract').addEventListener('click', () => $('file-extract').click());
$('file-extract').addEventListener('change', async (ev) => {
  const f = ev.target.files[0];
  ev.target.value = '';
  if (!f) return;
  hint('正在从照片里找衣服…');
  try {
    const up = await uploadFile(f);
    const r = await extractGarment(up.path);
    // 用用户自己的文件名，别把上传时加的时间戳前缀带上去
    const label = f.name.replace(/\.[^.]+$/, '') + ' 提取的衣服';
    S.garments.push({ path: r.path, url: r.url, name: label, state: 'pending' });
    renderChips();
    syncRun();
    showViewer(r.url, label);
    hint('抠出来了，已经放进衣服那边。要换就点「开始换」。');
  } catch (e) {
    hint('没提取出来：' + e.message, true);
  }
});

// 人像格右上角的"看大图"：别让 label 顺手唤起文件选择
$('zoom-person').addEventListener('click', (ev) => {
  ev.preventDefault();
  ev.stopPropagation();
  if (S.person) showViewer(S.person.url, S.person.name);
});

$('demo').addEventListener('click', async () => {
  try {
    const d = await loadSamples();
    S.person = { path: d.person.path, url: d.person.url, name: d.person.name };
    S.cases = [];
    S.garments = d.garments.map((g) => ({ path: g.path, url: g.url, name: g.name, state: 'pending' }));
    const img = $('preview-person');
    img.src = thumb(S.person.url, 800);
    img.hidden = false;
    $('slot-person').querySelector('.slot-empty').hidden = true;
    $('zoom-person').hidden = false;
    renderChips();
    syncRun();
    // 只把图放好，不替人点「开始换」——自动开跑是明确不要的（见 ROADMAP 工作原则三）
  } catch (e) {
    hint('载入示例失败：' + e.message, true);
  }
});

/* 存档：打开时现拉一次列表，最近的在前 */
async function openLedger() {
  const panel = $('ledger');
  panel.hidden = false;
  $('ledger-close').focus();
  try {
    const [items, m] = await Promise.all([getHistory(), getMetrics()]);
    S.history = items;
    renderLedger(items);
    const note = $('ledger-note');
    note.textContent = m.total_cost
      ? `点一行，把那次的结果调出来。全部 ${m.jobs} 单，云端一共花了 ${money(m.total_cost, m.cost_currency)}。`
      : '点一行，把那次的结果调出来。';
  } catch (e) {
    renderLedger([]);
    hint('读存档失败：' + e.message, true);
  }
}

function closeLedger() {
  $('ledger').hidden = true;
  $('ledger-open').focus();
}

$('ledger-open').addEventListener('click', openLedger);
$('ledger-close').addEventListener('click', closeLedger);
initSettings();
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && !$('ledger').hidden) closeLedger();
});

$('rerun').addEventListener('click', () => {
  S.garments.forEach((g) => { g.state = 'pending'; });
  S.cases = [];
  renderChips();
  syncRun();
  startRun();
});

/* ---------- 拖拽：整页都能接，落到哪个槽都能用 ---------- */

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
