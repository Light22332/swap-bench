/* 看大图：点缩略图把图放到满屏。Esc、点背景、点右上角都能退出来。

   建一次反复用，不每次点击都往 DOM 里插节点。屏幕上的图走 1600 宽的
   缩略图，保存按钮仍然指向原图。 */

import { thumb } from './img.js';

let box = null;
let lastFocus = null;

function build() {
  box = document.createElement('div');
  box.className = 'viewer';
  box.hidden = true;
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-modal', 'true');
  box.setAttribute('aria-label', '看大图');

  const img = document.createElement('img');
  img.className = 'viewer-img';
  img.alt = '';

  const cap = document.createElement('p');
  cap.className = 'viewer-cap';

  const save = document.createElement('a');
  save.className = 'viewer-save';
  save.textContent = '保存这张图';
  save.setAttribute('download', '');

  const close = document.createElement('button');
  close.className = 'viewer-close';
  close.type = 'button';
  close.textContent = '×';
  close.setAttribute('aria-label', '关闭大图');
  close.addEventListener('click', hide);

  box.addEventListener('click', (ev) => {
    if (ev.target === box) hide();      // 点背景关掉，点图不关
  });

  box.append(img, cap, save, close);
  document.body.append(box);

  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && box && !box.hidden) hide();
  });
}

export function show(url, name) {
  if (!url) return;
  if (!box) build();
  lastFocus = document.activeElement;
  box.querySelector('.viewer-img').src = thumb(url, 1600);
  box.querySelector('.viewer-cap').textContent = name || '';
  const save = box.querySelector('.viewer-save');
  save.href = url;
  save.setAttribute('download', (name || 'image').replace(/\.[^.]+$/, '') + '.png');
  box.hidden = false;
  box.querySelector('.viewer-close').focus();
}

export function hide() {
  if (!box || box.hidden) return;
  box.hidden = true;
  box.querySelector('.viewer-img').removeAttribute('src');
  if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();
  lastFocus = null;
}
