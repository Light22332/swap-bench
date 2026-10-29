/* 设置抽屉：改服务地址。主流程一个入口都不用碰这里。 */

import { getSettings, saveSettings } from './api.js';
import { $ } from './state.js';

function msg(text, isError) {
  const el = $('settings-msg');
  el.textContent = text;
  el.classList.toggle('is-error', !!isError);
}

async function open() {
  const panel = $('settings');
  panel.hidden = false;
  $('settings-close').focus();
  msg('读取中…');
  try {
    const s = await getSettings();
    panel.querySelectorAll('[data-key]').forEach((el) => {
      // 密钥不往回填：页面拿到的永远是空，留着空就是"不改"
      if (el.dataset.key === 'cloud.api_key') {
        el.value = '';
        el.placeholder = s._api_key_set ? '已存着，留空表示不改' : 'sk-…';
        return;
      }
      el.value = s[el.dataset.key] || '';
    });
    msg('');
  } catch (e) {
    msg('读设置失败：' + e.message, true);
  }
}

function close() {
  $('settings').hidden = true;
  $('settings-open').focus();
}

async function submit(ev) {
  ev.preventDefault();
  const payload = {};
  document.querySelectorAll('#settings [data-key]').forEach((el) => {
    if (el.dataset.key === 'cloud.api_key' && !el.value.trim()) return;  // 空着=不改
    payload[el.dataset.key] = el.value;
  });
  msg('保存中…');
  try {
    const r = await saveSettings(payload);
    $('backend-tag').textContent = r.backend === 'cloud' ? '云端' : '本地';
    if (r.changed.includes('cloud.api_key')) {
      const keyEl = document.querySelector('#settings [data-key="cloud.api_key"]');
      keyEl.value = '';
      keyEl.placeholder = '已存着，留空表示不改';
    }
    msg(r.changed.length ? `已保存 ${r.changed.length} 项，立刻生效` : '没有改动');
  } catch (e) {
    msg('没存上：' + e.message, true);
  }
}

export function initSettings() {
  $('settings-open').addEventListener('click', open);
  $('settings-close').addEventListener('click', close);
  $('settings-form').addEventListener('submit', submit);
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !$('settings').hidden) close();
  });
}
