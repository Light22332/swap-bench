/* 右上角的云端累计花费：页面一打开就能看到，跑完一单也刷新一次。

   数是 /api/metrics 现算的（扫全部 runs/*.jsonl），不存别处。读不到就不显示，不打扰。 */

import { getMetrics } from './api.js';
import { $ } from './state.js';
import { money } from './render.js';

export async function refreshCostTag() {
  const el = $('cost-tag');
  if (!el) return;
  try {
    const m = await getMetrics();
    if (m.total_cost) {
      el.hidden = false;
      el.textContent = `已花 ${money(m.total_cost, m.cost_currency)}`;
      el.title = `云端累计 ${money(m.total_cost, m.cost_currency)}，按 config.json 里的单价算；本地跑不花钱`;
    } else {
      el.hidden = true;
    }
  } catch (e) {
    el.hidden = true;      // 接口挂了就别挂个假数字在上面
  }
}
