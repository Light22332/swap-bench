/* 上传与选图：文件进来、传上去、把缩略图列出来。
   拖拽也在这里，因为它最终都落到 addPerson / addGarments 上。 */

import { uploadFile } from './api.js';
import { $, S } from './state.js';
import { hint, render, syncRun } from './render.js';
import { show as showViewer } from './viewer.js';

export const isImage = (f) => f && f.type && f.type.startsWith('image/');

export async function addPerson(file) {
  if (!isImage(file)) {
    hint('这个文件不是图片，换一张试试。', true);
    return;
  }
  try {
    const up = await uploadFile(file);
    S.person = { path: up.path, url: up.url, name: file.name };
    const img = $('preview-person');
    img.src = up.url;
    img.hidden = false;
    $('slot-person').querySelector('.slot-empty').hidden = true;
    $('zoom-person').hidden = false;
    // 换了人，之前的结果就不再对应，清掉
    S.cases = [];
    S.garments.forEach((g) => { g.state = 'pending'; });
    renderChips();
    syncRun();
  } catch (e) {
    hint('人像没传上去：' + e.message, true);
  }
}

export async function addGarments(files) {
  const list = files.filter(isImage);
  if (!list.length) {
    hint('这些文件不是图片，换几张试试。', true);
    return;
  }
  for (const f of list) {
    try {
      const up = await uploadFile(f);
      S.garments.push({ path: up.path, url: up.url, name: f.name, state: 'pending' });
    } catch (e) {
      hint('衣服没传上去：' + e.message, true);
    }
  }
  renderChips();
  syncRun();
}

export function renderChips() {
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

    // 缩略图和文件名一起当按钮：点一下看大图
    const open = document.createElement('button');
    open.className = 'chip-open';
    open.type = 'button';
    open.setAttribute('aria-label', '看大图：' + g.name);
    open.append(im, sp);
    open.addEventListener('click', () => showViewer(g.url, g.name));

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
      // 提示语里的件数要跟着变，不然删完还显示"要换 2 件"
      syncRun();
    });

    li.append(open, rm);
    ul.append(li);
  });
  if ($('garment-count')) $('garment-count').textContent = S.garments.length;
}

export function wireDrop(el, handler) {
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
