"""策略的纯函数测试：不碰 IO、不需要 GPU、不需要 ComfyUI。

跑法：python tools/tests/test_policy.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.pipeline import policy, select      # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


print("打法：第几轮用什么")
check("第 1 轮 base", policy.mode_for(1, 2) == policy.BASE, policy.mode_for(1, 2))
check("第 2 轮 refine", policy.mode_for(2, 2) == policy.REFINE, policy.mode_for(2, 2))
check("第 3 轮 escape", policy.mode_for(3, 2) == policy.ESCAPE, policy.mode_for(3, 2))
check("再多也还是 escape", policy.mode_for(9, 2) == policy.ESCAPE, policy.mode_for(9, 2))

print("决定：一轮判定之后怎么走")


def decide(**kw):
    base = dict(attempt=1, total_attempts=3, max_attempts=2, passed=False,
                critical_failed=True, clauses=())
    base.update(kw)
    return policy.decide(**base)


check("通过就收", decide(passed=True).action == policy.ACCEPT)
check("只有非关键项不过就停",
      decide(critical_failed=False).action == policy.STOP and
      "非关键项" in decide(critical_failed=False).reason)
check("非关键项也要落记录", decide(critical_failed=False).log is True)
check("降级轮不过就认输",
      decide(attempt=3).action == policy.STOP and "降级" in decide(attempt=3).reason)
check("轮次用完就停", decide(attempt=3, total_attempts=3, max_attempts=3).action == policy.STOP)
check("轮次用完不落 stop 记录",
      decide(attempt=3, total_attempts=3, max_attempts=3).log is False,
      str(decide(attempt=3, total_attempts=3, max_attempts=3)))
d = decide(clauses=("约束A", "约束B"))
check("关键项不过就继续", d.action == policy.RETRY)
check("继续时带上约束", d.clauses == ("约束A", "约束B"), str(d.clauses))
check("没约束也继续，但说明原因",
      decide().action == policy.RETRY and "没有可补" in decide().reason)
check("降级轮优先于轮次判断", decide(attempt=3, total_attempts=4).reason.startswith("降级"),
      decide(attempt=3, total_attempts=4).reason)

print("挑图：先看通过，再看分数")


def t(passed, score, attempt):
    return {"attempt": attempt, "verdict": {"passed": passed, "score": score}}


check("空列表返回 -1", select.best([]) == -1)
check("通过优先于高分",
      select.best([t(False, 0.99, 1), t(True, 0.80, 2)]) == 1)
check("都不通过时取高分",
      select.best([t(False, 0.5, 1), t(False, 0.78, 2)]) == 1)
check("都通过时取高分",
      select.best([t(True, 0.78, 1), t(True, 1.0, 2)]) == 1)
check("同分取靠前的", select.best([t(True, 1.0, 1), t(True, 1.0, 2)]) == 0)
check("verdict 是 None 时不崩",
      select.best([{"attempt": 1, "verdict": None}, t(True, 1.0, 2)]) == 1)

print("状态")
check("通过就是 passed", select.case_state(True, 3) == "passed")
check("试了两次没过是 reworked", select.case_state(False, 2) == "reworked")
check("一次就没过是 rejected", select.case_state(False, 1) == "rejected")

print("\n" + ("全部通过" if not FAILED else f"{len(FAILED)} 项失败"))
sys.exit(1 if FAILED else 0)
