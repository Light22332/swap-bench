"""历史任务：从 JSONL 还原一次跑完的任务，以及全站汇总指标。

内存里的任务重启就没了，JSONL 是唯一的长久记录。这两件事都只读 runs/ 目录。
"""
from ..core import config as app_config
from ..core.store import Store

from . import state


def load_job(jid):
    """重启后从 JSONL 把一次历史任务还原出来，让 ?job=xxx 的链接长期有效。"""
    store = Store(app_config.runs_dir(state.get_config()))
    recs = store.read(jid)
    if not recs:
        return None

    cases, metrics = {}, {}
    for r in recs:
        stage = r.get("stage")
        if stage == "job_end":
            metrics = r.get("metrics", {})
        elif stage in ("generate", "judge") and r.get("case") is not None:
            idx = r["case"]
            c = cases.setdefault(idx, {
                "index": idx, "garment": r.get("garment", ""), "state": "passed",
                "attempts": [], "attempts_used": 0, "passed": False,
                "first_attempt_passed": False, "final_image": None,
                "verdict": None, "instruction_used": "",
            })
            c["attempts"].append(r)
            if r.get("garment"):
                c["garment"] = r["garment"]
            if stage == "generate" and r.get("ok"):
                c["final_image"] = r.get("image")
            if stage == "judge":
                c["attempts_used"] = r.get("attempt", 0)
                c["passed"] = bool(r.get("passed"))
                if r.get("attempt") == 1 and r.get("passed"):
                    c["first_attempt_passed"] = True
                c["state"] = "passed" if r.get("passed") else "rejected"
                c["verdict"] = {"mode": r.get("mode"), "passed": r.get("passed"),
                                "checks": r.get("checks", {}),
                                "failures": r.get("failures", []),
                                "note": r.get("note", "")}

    if not cases:
        return None
    return {
        "id": jid,
        "state": "done",
        "elapsed_s": metrics.get("total_generate_s", 0),
        "judge_mode": metrics.get("judge_mode", "rules"),
        "cases": [cases[k] for k in sorted(cases)],
        "metrics": metrics,
        "error": None,
        "replayed": True,
    }


def global_metrics():
    """扫一遍全部 runs/*.jsonl，给出全站的首轮通过率和平均重试。"""
    store = Store(app_config.runs_dir(state.get_config()))
    cases, jobs = [], 0
    for jid in store.all_jobs():
        recs = store.read(jid)
        if not recs:
            continue
        jobs += 1
        by_case = {}
        for r in recs:
            if r.get("stage") == "judge":
                by_case[r["case"]] = {
                    "passed": r.get("passed"),
                    "attempts": r.get("attempt"),
                    "first_attempt_passed": r.get("attempt") == 1 and r.get("passed"),
                    "attempts_used": r.get("attempt"),
                    "attempts_list": [],
                }
        cases.extend(by_case.values())

    total = len(cases)
    first = sum(1 for c in cases if c.get("first_attempt_passed"))
    final = sum(1 for c in cases if c.get("passed"))
    avg_att = (sum(c["attempts"] for c in cases) / total) if total else 0
    return {
        "jobs": jobs,
        "cases": total,
        "first_pass_rate": round(first / total, 3) if total else 0,
        "final_pass_rate": round(final / total, 3) if total else 0,
        "avg_attempts": round(avg_att, 2),
    }
