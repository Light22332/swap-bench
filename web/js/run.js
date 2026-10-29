/* 跑任务：提交、轮询、把进度并进结果墙。

轮询是 setTimeout 自调用，不用 setInterval——上一次请求回来之后再排下一次，
断网时不会堆一串请求。 */

import { cancelJob, getJob, submitRun } from './api.js';
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
  S.jobStart = S.cases.length;
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
      const job = await getJob(S.job);
      merge(job);
      render();
      if (job.state === 'running' || job.state === 'pending') {
        // 叫停之后别再让进度文案盖掉那句"等这张跑完就停"
        hint(S.stopping ? '叫停了，等正在跑的这张回来就停…' : progressText(job));
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

function progressText(job) {
  const live = job.cases.find((c) => c.state === 'running')
    || job.cases[job.cases.length - 1];
  if (!live) return '准备中…';
  const gen = lastStage(live, 'generate');
  const jud = lastStage(live, 'judge');
  if (!gen) return `第 ${live.index} 件：正在生成…`;
  if (!jud) return `第 ${live.index} 件：正在检查…`;
  return `第 ${live.index} 件：${jud.passed ? '通过' : '在返工'}…`;
}

function finishRun(job) {
  S.running = false;
  S.stopping = false;
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
    hint(job && job.error ? '出错了：' + job.error : '没跑完，可以点「重新跑一次」。', true);
  }
  $('rerun').hidden = S.cases.length === 0;
  render();
}
