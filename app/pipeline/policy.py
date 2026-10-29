"""要不要继续、继续用什么打法、什么时候认输。

这里全是纯函数：给几个状态，返回一个决定。不调模型、不写文件，所以能脱离
GPU 和 ComfyUI 单测——以前这四个判断埋在 run_job 的 for 循环里，测一次要跑
整条流水线。

四条规则，顺序不能换：

1. 通过了就收
2. 只有非关键项不过，收（背景这类不过就重试，容易把已经对的结果改坏）
3. 降级重跑还不过，收（没有更多手段，别烧时间）
4. 轮次用完，收

剩下的情况都继续，并带上"下次该补什么约束"。
"""
from dataclasses import dataclass

ACCEPT = "accept"
RETRY = "retry"
STOP = "stop"

BASE = "base"        # 第 1 轮：原样指令
REFINE = "refine"    # 后续普通轮：追加失败项对应的约束
ESCAPE = "escape"    # 降级轮：指令退回原文、cfg 抬高


@dataclass(frozen=True)
class Decision:
    action: str
    clauses: tuple = ()     # RETRY 时要追加的约束（可能为空）
    reason: str = ""        # 为什么这么决定，写进 JSONL
    log: bool = True        # 是否落一行 stop 记录


def mode_for(attempt, max_attempts):
    """第 attempt 轮的打法。1 是原样，2..max 是加约束，超过 max 的是降级。"""
    if attempt > max_attempts:
        return ESCAPE
    return BASE if attempt == 1 else REFINE


def decide(attempt, total_attempts, max_attempts, passed, critical_failed, clauses=()):
    """一轮判定之后，下一步怎么走。"""
    if passed:
        return Decision(ACCEPT, reason="通过")
    if not critical_failed:
        return Decision(STOP, reason="只有非关键项不过，不再重试")
    if attempt > max_attempts:
        return Decision(STOP, reason="降级重跑仍不过，放弃")
    if attempt >= total_attempts:
        return Decision(STOP, reason="尝试次数用完", log=False)
    return Decision(RETRY, clauses=tuple(clauses),
                    reason="" if clauses else "没有可补的约束，下一轮降级")
