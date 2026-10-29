/* 前端状态：一个对象装下所有跨函数共享的东西。

没有框架，改完状态自己调 render。这里不碰 DOM，也不发请求——
只放"页面要知道的东西"和两个到处要用的工具函数。 */

export const S = {
  person: null,
  garments: [],     // {path, url, name, state: 'pending'|'done'}
  cases: [],        // 累积的结果，跨多次提交
  job: null,
  timer: null,
  running: false,
  selected: null,
  metrics: null,
  judgeMode: null,
  elapsed: 0,
  live: null,
  jobStart: 0,
  pendingPaths: [],
  personUrl: null,   // 原片地址，按住格子看对比时用
  history: [],
};

export const $ = (id) => document.getElementById(id);

/** 一轮尝试里最后一次某阶段的记录（generate / judge）。 */
export function lastStage(c, stage) {
  for (let i = c.attempts.length - 1; i >= 0; i--) {
    if (c.attempts[i].stage === stage) return c.attempts[i];
  }
  return null;
}

/** 还没跑过的衣服。 */
export function pendingGarments() {
  return S.garments.filter((g) => g.state !== 'done');
}
