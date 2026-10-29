"""降级重跑的策略测试（不需要 GPU、不需要 ComfyUI）。

把后端和质检都换成假的，只验流程是不是按设计走：
  1. 关键项一挂到底 → 2 次普通 + 1 次降级，降级那次 cfg=2.0、指令回到原文
  2. 第一次就过 → 只跑一次
  3. 只有非关键项不过 → 不重试（沿用原来的约定）
  4. escape_attempts=0 → 就只跑 max_attempts 次

用法：python tools/test_pipeline_escape.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import pipeline                                    # noqa: E402
from app.adapters.base import GenResult                      # noqa: E402

BASE = "把衣服换掉"
FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("  " + detail if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.requests = []

    def generate(self, req):
        self.requests.append(req)
        n = len(self.requests)
        return GenResult(ok=True, image_path=f"/tmp/fake_{n}.png", backend="fake",
                         model="fake-model", latency_s=1.0, seed=1000 + n)


def make_judge(verdicts):
    """verdicts: 依次返回的 (passed, failures) 列表，用完之后重复最后一个。"""
    state = {"i": 0}

    def judge(person, result, garment):
        i = min(state["i"], len(verdicts) - 1)
        state["i"] += 1
        passed, failures = verdicts[i]
        return {"mode": "local", "note": "", "passed": passed, "score": 0.5 if not passed else 1.0,
                "failures": list(failures), "checks": {}, "latency_s": 0.01,
                "error": None, "semantic_checked": True}

    judge.mode = "local"
    return judge


def run(verdicts, pipeline_cfg):
    backend, judge = FakeBackend(), make_judge(verdicts)
    pipeline.make_backend = lambda *a, **k: backend
    pipeline.make_judge = lambda *a, **k: judge
    tmp = tempfile.mkdtemp()
    config = {
        "backend": "fake",
        "prep": {"enabled": False},
        "sampling": {"cfg": 1.0, "steps": 40, "resolution": 1024},
        "pipeline": dict(pipeline_cfg),
        "paths": {"runs": os.path.join(tmp, "runs"), "outputs": os.path.join(tmp, "out")},
    }
    job = pipeline.new_job("person.png", [{"name": "g.jpg", "path": "g.jpg"}],
                           BASE, "", config)
    pipeline.run_job(job, config)
    records = pipeline.Store(config["paths"]["runs"]).read(job.id)
    return job, backend.requests, records


print("1) 关键项一挂到底：2 次普通 + 1 次降级")
job, reqs, recs = run([(False, ["hand_preserved"])] * 5,
                      {"max_attempts": 2, "escape_attempts": 1, "escape_cfg": 2.0})
check("一共尝试 3 次", len(reqs) == 3, str(len(reqs)))
check("第 1、2 次 cfg=1.0", [r.cfg for r in reqs[:2]] == [1.0, 1.0], str([r.cfg for r in reqs]))
check("降级那次 cfg=2.0", reqs[-1].cfg == 2.0, str(reqs[-1].cfg))
check("降级那次指令回到原文", reqs[-1].instruction == BASE, reqs[-1].instruction)
check("第 2 次指令带了修正约束", "本次必须修正" in reqs[1].instruction, reqs[1].instruction[:60])
modes = [r.get("mode") for r in recs if r.get("stage") == "generate"]
check("记录里标了 base/refine/escape", modes == ["base", "refine", "escape"], str(modes))
check("指标里记了降级次数", job.metrics.get("escape_attempts") == 1, str(job.metrics.get("escape_attempts")))
check("最后仍然挑了一张", job.cases[0].get("final_image") is not None)
check("放弃时记了原因", any(r.get("stage") == "stop" and "降级重跑仍不过" in r.get("reason", "")
                          for r in recs))
check("没通过就不盖通过章", job.cases[0]["state"] != "passed", job.cases[0]["state"])

print("2) 第一次就过：只跑一次")
job, reqs, _ = run([(True, [])], {"max_attempts": 2, "escape_attempts": 1, "escape_cfg": 2.0})
check("只尝试 1 次", len(reqs) == 1, str(len(reqs)))
check("案例状态 passed", job.cases[0]["state"] == "passed", job.cases[0]["state"])

print("3) 只有非关键项不过：不重试")
job, reqs, recs = run([(False, ["background_preserved"])],
                      {"max_attempts": 2, "escape_attempts": 1, "escape_cfg": 2.0})
check("只尝试 1 次", len(reqs) == 1, str(len(reqs)))
check("记了 stop 原因", any(r.get("stage") == "stop" and "非关键项" in r.get("reason", "")
                          for r in recs))

print("4) escape_attempts=0：只跑 max_attempts 次")
job, reqs, _ = run([(False, ["face_preserved"])] * 5,
                   {"max_attempts": 2, "escape_attempts": 0})
check("尝试 2 次", len(reqs) == 2, str(len(reqs)))
check("没有降级记录", job.metrics.get("escape_attempts") == 0, str(job.metrics.get("escape_attempts")))

print("\n" + ("全部通过" if not FAILED else f"{len(FAILED)} 项失败"))
sys.exit(1 if FAILED else 0)
