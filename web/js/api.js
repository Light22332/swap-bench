/* 所有网络请求收在这里。页面代码不直接写 fetch，出错处理也就只有一处。 */

async function json(res) {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || res.statusText);
  return body;
}

export function getConfig() {
  return fetch('/api/config').then(json);
}

export function getJob(id) {
  return fetch('/api/job/' + id).then(json);
}

export function getHistory() {
  return fetch('/api/history').then(json);
}

export function loadSamples() {
  return fetch('/api/samples', { method: 'POST' }).then(json);
}

export function submitRun(payload) {
  return fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(json);
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
  return fetch('/api/upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: file.name, data }),
  }).then(json);
}
