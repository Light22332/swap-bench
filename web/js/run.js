/* 跑任务：提交、轮询、把进度并进结果墙。

轮询是 setTimeout 自调用，不用 setInterval——上一次请求回来之后再排下一次，
断网时不会堆一串请求。 */

import { cancelJob, getJob, submitRun } from './api.js';
import { refreshCostTag } from './cost.js';
import { $, S, lastStage } from './state.js';
import { hint, render, syncRun } from './render.js';
import { renderChips } from './upload.js';

export function startRun() {
  const pending = S.garments.filter((g) => g.state !== 'done');
  if (!S.person || !pending.length || S.running) return;
  runPending(pending);
}

/** 停下：只是打个标记，正在生成的那一张仍会跑完。 */
export function stopRun() {
  if (!S.running || !S.job) return;
  S.stopping = true;
  hint('叫停了，等正在跑的这张回来就停…');
  cancelJob(S.job).catch((e) => {
    S.stopping = false;
    hint('叫停失败：' + e.message, true);
  });
}

async function runPending(pending) {
  S.running = true;
  S.stopping = false;
  syncRun();
  $('rerun').hidden = true;
  $('docket').hidden = true;
  hint('开始换，第一张要等模型加载，大概一两分钟…');
  if (!S.cases.length) {
    $('sheet').innerHTML = '<p class="sheet-empty">正在换第一件…</p>';
    $('sheet').classList.add('is-empty');
  }

  try {
    // 指令不从这里传：服务端用 config.json 里那份固定的，页面上不再给用户改
    const data = await submitRun({
      person: S.person.path,
      garments: pending.map((g) => ({ path: g.path, name: g.name })),
    });
    S.job = data.job_id;
    // 新的一批：墙上只留这一批的结果。上一批在「存档」里，不然页面上的张数
    // 会和「整批下载」（只导这一次任务）对不上
    S.cases = [];
    S.selected = null;
    S.jobStart = 0;
    S.pendingPaths = pending.map((g) => g.path);
    S.pollFails = 0;
    if (data.queued) hint(`排上了，前面还有 ${data.queued} 单…`);
    poll();
  } catch (e) {
    // 提交失败要说真实原因，而且不能盖成"没跑完"——按钮也还在，可以直接重试
    finishRun(null, '没提交上去：' + e.message + '。服务可能没开，检查一下再点「开始换」。');
  }
}

function poll(delay = 1500) {
  clearTimeout(S.timer);
  S.timer = setTimeout(async () => {
    try {
      const job = await getJob(S.job);
      S.pollFails = 0;
      merge(job);
      render();
      if (job.state === 'queued' || job.state === 'running' || job.state === 'pending') {
        // 叫停之后别再让进度文案盖掉那句"等这张跑完就停"
        const text = S.stopping ? '叫停了，等正在跑的这张回来就停…' : progressText(job);
        hint(text);
        document.title = titleOf(job);
        poll();
      } else {
        finishRun(job);
      }
    } catch (e) {
      // 轮询偶发失败不该废掉整单：重试三次，页面上的进度一直在，别慌
      S.pollFails = (S.pollFails || 0) + 1;
      if (S.pollFails < 3) {
        hint(`连接断了一下，正在重试（${S.pollFails}/3）…`);
        poll(S.pollFails * 1200);
      } else {
        finishRun(null, '连接断了：' + e.message + '。任务可能还在跑，稍等一下看存档。');
      }
    }
  }, delay);
}

/** 服务端每次返回整个任务的快照，这里把它并进累积的结果里。 */
function merge(job) {
  const mapped = job.cases.map((c, i) => ({
    ...c,
    index: S.jobStart + i + 1,
    _path: (S.pendingPaths && S.pendingPaths[i]) || null,
  }));
  S.cases = S.cases.slice(0, S.jobStart).concat(mapped);
  S.job = job.id || S.job;
  S.personUrl = job.person_url || S.personUrl;
  S.live = mapped.find((c) => c.state === 'running') || mapped[mapped.length - 1] || null;
  S.elapsed = job.elapsed_s;
  if (job.metrics && job.state === 'done') {
    S.metrics = job.metrics;
    S.judgeMode = job.metrics.judge_mode;
  }
}

// 一件最多生成两次（首轮 + 一次重试），文案里把"第几次 / 共几次"说清楚，
// 不然用户只知道在等，不知道还要等几次
const GEN_CAP = 2;

function progressText(job) {
  if (job.state === 'queued') return '排队中：本地一次只跑一单，前面那单结束就开始…';
  const live = job.cases.find((c) => c.state === 'running')
    || job.cases[job.cases.length - 1];
  if (!live) return '准备中…';

  const spent = S.elapsed ? `已用 ${Math.round(S.elapsed)} 秒` : '';
  const gen = lastStage(live, 'generate');
  const jud = lastStage(live, 'judge');
  const tries = 1 + (live.attempts || []).filter(
    (a) => a.stage === 'generate' && a.attempt > 1).length;
  const n = `第 ${live.index} 件`;
  const clock = spent ? `（${spent}）` : '';

  let text;
  if (!gen) text = `${n}：第 ${Math.min(tries, GEN_CAP)}/${GEN_CAP} 次生成中…${clock}`;
  else if (!jud) text = `${n}：正在看换得对不对…${clock}`;
  else text = `${n}：${jud.passed ? '好了' : '不太对，再换一次'}…${clock}`;

  // 同一件、同一轮尝试卡超过 45 秒，"是不是卡住了"要主动说一句
  const sig = `${live.index}:${(live.attempts || []).length}:${gen ? 'g' : 'w'}`;
  if (S.progressSig !== sig) {
    S.progressSig = sig;
    S.progressSince = Date.now();
  } else if (Date.now() - (S.progressSince || Date.now()) > 45000) {
    text += '（比平时慢，模型可能还在加载）';
  }
  return text;
}

/** 浏览器标签页上也要能看出在跑、跑到第几件。 */
function titleOf(job) {
  const live = job.cases.find((c) => c.state === 'running')
    || job.cases[job.cases.length - 1];
  if (!live) return '换衣服';
  const n = Math.round(S.elapsed || job.elapsed_s || 0);
  return `换装中 · 第 ${live.index} 件 · ${n} 秒 · 换衣服`;
}

function finishRun(job, message) {
  S.running = false;
  S.stopping = false;
  S.progressSig = null;
  document.title = '换衣服';
  if (job && (job.state === 'done' || job.state === 'cancelled')) {
    const ok = S.cases.filter((c) => c.passed).length;
    S.garments.forEach((g) => { g.state = 'done'; });
    renderChips();
    syncRun();
    if (job.state === 'cancelled') {
      hint(`停下了。已经换好 ${ok}/${S.cases.length} 张，没跑到的那些点「重新跑一次」会从头再走一遍。`);
    } else {
      hint(`换好了：${ok}/${S.cases.length} 张可用。点图看大图、保存。`);
    }
  } else {
    syncRun();
    // message 是调用方给的、真实的原因；没有才用兜底文案。
    // 这时候「开始换」按钮已经可以再点了，所以别说「重新跑一次」（那个按钮可能没出来）
    hint(message || (job && job.error ? '出错了：' + job.error : '没跑完，再点一次「开始换」。'), true);
  }
  // 只要人和衣服还在，重跑入口就别藏；提交失败时更不能让按钮消失
  $('rerun').hidden = !(S.person && S.garments.length);
  render();
  refreshCostTag();          // 跑完刷新右上角的累计花费
}
