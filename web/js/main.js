/* 启动与事件绑定：这是唯一碰"页面怎么动起来"的文件。

启动顺序：读配置 → 有 ?job= 就还原历史，否则等用户放图 → ?demo 直接跑示例。 */

import { getConfig, getJob, loadSamples } from './api.js';
import { $, S } from './state.js';
import { hint, render, syncRun } from './render.js';
import { addGarments, addPerson, isImage, renderChips, wireDrop } from './upload.js';
import { startRun } from './run.js';

async function boot() {
  try {
    const cfg = await getConfig();
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
    const job = await getJob(id);
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

$('demo').addEventListener('click', async () => {
  try {
    const d = await loadSamples();
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
