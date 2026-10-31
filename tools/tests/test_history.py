"""历史还原的测试：中断的单子不能报成 done。

进程被杀时 JSONL 里没有 job_end，那一单其实只跑了一半。以前 load_job 一律
返回 state="done"，页面会把半张图盖个「通过」章。现在按事件还原：
有 job_end → done，有 cancel → cancelled，都没有 → interrupted。

跑法：python tools/tests/test_history.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.api import history, state           # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def write(root, jid, recs):
    """直接写 JSONL，ts 自己给，才能测耗时兜底。"""
    with open(os.path.join(root, jid + ".jsonl"), "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def start(**kw):
    r = {"stage": "job_start", "job": "j", "person": "/tmp/p.png",
         "garments": ["g1.jpg"], "backend": "comfyui", "judge_mode": "rules"}
    r.update(kw)
    return r


def gen(case=0, attempt=1, ok=True, image=None, **kw):
    r = {"stage": "generate", "job": "j", "case": case, "attempt": attempt,
         "ok": ok, "image": image or f"/tmp/c{case}_a{attempt}.png",
         "latency_s": 5.0, "seed": 7}
    r.update(kw)
    return r


def judge(case=0, attempt=1, passed=True, **kw):
    r = {"stage": "judge", "job": "j", "case": case, "attempt": attempt,
         "passed": passed, "mode": "rules", "score": 1.0,
         "checks": {"face_preserved": {"pass": passed}}, "failures": [],
         "latency_s": 1.0}
    r.update(kw)
    return r


def job_end(**kw):
    r = {"stage": "job_end", "job": "j",
         "metrics": {"total_generate_s": 12.5, "judge_mode": "rules",
                     "cases": 1, "final_pass_rate": 1.0}}
    r.update(kw)
    return r


def main():
    print("历史还原：done / cancelled / interrupted")
    tmp = tempfile.mkdtemp(prefix="swap_history_")
    state.CONFIG = {"paths": {"runs": tmp}}

    write(tmp, "done1", [
        start(ts="2026-10-31T10:00:00"),
        gen(image="/tmp/done_c0.png", ts="2026-10-31T10:00:05"),
        judge(ts="2026-10-31T10:00:09"),
        job_end(ts="2026-10-31T10:00:10"),
    ])
    write(tmp, "half1", [
        start(ts="2026-10-31T11:00:00", garments=["g1.jpg", "g2.jpg"]),
        gen(case=0, image="/tmp/half_c0.png", ts="2026-10-31T11:00:05"),
        gen(case=1, image="/tmp/half_c1.png", ts="2026-10-31T11:00:20"),
    ])
    write(tmp, "cancel1", [
        start(ts="2026-10-31T12:00:00"),
        gen(ts="2026-10-31T12:00:05"),
        judge(ts="2026-10-31T12:00:09"),
        {"stage": "cancel", "job": "j", "cases_done": 1, "ts": "2026-10-31T12:00:10"},
        job_end(ts="2026-10-31T12:00:10"),
    ])
    write(tmp, "empty1", [start(ts="2026-10-31T13:00:00")])

    done = history.load_job("done1")
    check("跑完的单子 state=done", done and done["state"] == "done", str(done and done["state"]))
    check("跑完的单子按 job_end 拿耗时", done and done["elapsed_s"] == 12.5, str(done and done["elapsed_s"]))
    check("判定过的 case 是 passed", done and done["cases"][0]["state"] == "passed",
          str(done and done["cases"][0]["state"]))
    check("选了图就有 final_image", done and done["cases"][0]["final_image"] == "/tmp/done_c0.png")

    half = history.load_job("half1")
    check("没有 job_end 的单子 state=interrupted", half and half["state"] == "interrupted",
          str(half and half["state"]))
    check("中断的单子不装通过：case=interrupted",
          half and all(c["state"] == "interrupted" for c in half["cases"]),
          str(half and [c["state"] for c in half["cases"]]))
    check("中断的单子保留已生成的图",
          half and half["cases"][0]["final_image"] == "/tmp/half_c0.png")
    check("中断的单子耗时用首尾 ts 兜底", half and abs(half["elapsed_s"] - 20.0) < 0.1,
          str(half and half["elapsed_s"]))

    cancel = history.load_job("cancel1")
    check("有 cancel 事件且跑完的单子 state=cancelled",
          cancel and cancel["state"] == "cancelled", str(cancel and cancel["state"]))

    check("只有 job_start 的残片返回 None", history.load_job("empty1") is None)
    check("不存在的单子返回 None", history.load_job("nope") is None)

    jobs = history.list_jobs()
    ids = [j["id"] for j in jobs]
    check("存档不吞中断的单子", "half1" in ids, str(ids))
    check("空残片不进存档", "empty1" not in ids, str(ids))
    by_id = {j["id"]: j for j in jobs}
    check("中断单的件数按 generate 算", by_id["half1"]["cases"] == 2, str(by_id["half1"]))
    check("中断单的通过数只算判定过的", by_id["half1"]["passed"] == 0, str(by_id["half1"]))
    check("跑完单的通过数正常", by_id["done1"]["passed"] == 1, str(by_id["done1"]))

    if FAILED:
        print(f"\n{len(FAILED)} 项失败：{FAILED}")
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
