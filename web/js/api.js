/* 所有网络请求收在这里。页面代码不直接写 fetch，出错处理也就只有一处。

每个请求都带超时：服务真卡住时，页面要能说"等了 8 秒没回应"，
而不是永远转圈。 */

const TIMEOUT = 8000;
const UPLOAD_TIMEOUT = 30000;      // 30MB 的图传上去比普通请求慢

async function json(res) {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || res.statusText);
  return body;
}

/** fetch + 超时 + JSON。超时报的是人话，不把 AbortError 丢给页面。 */
async function call(url, opts = {}, timeout = TIMEOUT) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  try {
    const res = await fetch(url, { ...opts, signal: ctl.signal });
    return await json(res);
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error(`等了 ${Math.round(timeout / 1000)} 秒没回应`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

const post = (url, body, timeout) => call(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
}, timeout);

export function getConfig() {
  return call('/api/config');
}

export function getSettings() {
  return call('/api/settings');
}

export function saveSettings(payload) {
  return post('/api/settings', payload);
}

export function extractGarment(path) {
  return post('/api/extract', { path }, 60000);   // 模型推理要几十秒
}

export function getJob(id) {
  return call('/api/job/' + id);
}

export function getHistory() {
  return call('/api/history');
}

export function getMetrics() {
  return call('/api/metrics');
}

export function loadSamples() {
  return post('/api/samples', {});
}

export function submitRun(payload) {
  return post('/api/run', payload);
}

export function cancelJob(id) {
  return post('/api/cancel', { job_id: id });
}

function toDataURL(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
}

export async function uploadFile(file) {
  const data = await toDataURL(file);
  return post('/api/upload', { name: file.name, data }, UPLOAD_TIMEOUT);
}
