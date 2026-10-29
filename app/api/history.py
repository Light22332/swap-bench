"""历史任务：从 JSONL 还原一次跑完的任务、列出全部历史、导出成 zip。

内存里的任务重启就没了，JSONL 是唯一的长久记录。这几件事都只读 runs/ 目录。
"""
import io
import json
import os
import re
import zipfile

from ..core import config as app_config
from ..core.store import Store

from . import state


def _store():
    return Store(app_config.runs_dir(state.get_config()))


def load_job(jid):
    """重启后从 JSONL 把一次历史任务还原出来，让 ?job=xxx 的链接长期有效。"""
    store = _store()
    recs = store.read(jid)
    if not recs:
        return None

    person = next((r.get("person") for r in recs if r.get("stage") == "job_start"), None)
    cases, metrics = {}, {}
    images = {}          # (case, attempt) -> 图片路径
    picked = {}          # case -> 选中的第几次

    for r in recs:
        stage = r.get("stage")
        if stage == "job_end":
            metrics = r.get("metrics", {})
        elif stage == "pick":
            picked[r.get("case")] = r.get("chosen")
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
                images[(idx, r.get("attempt"))] = r.get("image")
                c["final_image"] = r.get("image")
            if stage == "judge":
                c["attempts_used"] = r.get("attempt", 0)
                c["passed"] = bool(r.get("passed"))
                if r.get("attempt") == 1 and r.get("passed"):
                    c["first_attempt_passed"] = True
                c["state"] = "passed" if r.get("passed") else "rejected"
                c["verdict"] = {"mode": r.get("mode"), "passed": r.get("passed"),
                                "score": r.get("score"),
                                "checks": r.get("checks", {}),
                                "failures": r.get("failures", []),
                                "note": r.get("note", "")}

    if not cases:
        return None

    # 选中的不一定是最后一次：以前这里是"最后一张生成图"，会把挑回来的那张显示错
    for idx, attempt in picked.items():
        if (idx, attempt) in images:
            cases[idx]["final_image"] = images[(idx, attempt)]
            cases[idx]["chosen_attempt"] = attempt

    return {
        "id": jid,
        "state": "done",
        "elapsed_s": metrics.get("total_generate_s", 0),
        "judge_mode": metrics.get("judge_mode", "rules"),
        "person": person,
        "cases": [cases[k] for k in sorted(cases)],
        "metrics": metrics,
        "error": None,
        "replayed": True,
    }


def list_jobs(limit=60):
    """列出所有跑过的任务，最近的在前。只扫一遍 JSONL 的关键几行。"""
    store = _store()
    out = []
    for jid in store.all_jobs():
        recs = store.read(jid)
        if not recs:
            continue
        start = next((r for r in recs if r.get("stage") == "job_start"), {})
        end = next((r for r in recs if r.get("stage") == "job_end"), {})
        by_case = {}
        for r in recs:
            if r.get("stage") == "judge":
                idx = r.get("case")
                by_case.setdefault(idx, False)
                by_case[idx] = by_case[idx] or bool(r.get("passed"))
        if not by_case:
            continue
        metrics = end.get("metrics") or {}
        out.append({
            "id": jid,
            "ts": start.get("ts", ""),
            "garments": start.get("garments") or [],
            "cases": len(by_case),
            "passed": sum(1 for v in by_case.values() if v),
            "elapsed_s": metrics.get("total_generate_s", 0),
        })
    out.sort(key=lambda j: j["ts"], reverse=True)
    return out[:limit]


def _safe_name(text, fallback="item"):
    text = os.path.splitext(os.path.basename(text or ""))[0]
    text = re.sub(r"[^A-Za-z0-9_.\-]", "_", text).strip("_")
    return text or fallback


def export_zip(job_dict):
    """把一次任务的所有成图打成一个 zip；再附一张清单，写明每张是怎么来的。"""
    cases = job_dict.get("cases") or []
    buf = io.BytesIO()
    lines = ["序号\t衣服\t结果\t分数\t第几次"]
    packed = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in cases:
            idx = c.get("index", 0)
            img = c.get("final_image")
            verdict = c.get("verdict") or {}
            lines.append("{:02d}\t{}\t{}\t{}\t{}".format(
                idx, c.get("garment", ""), "通过" if c.get("passed") else "不过",
                verdict.get("score", ""), c.get("chosen_attempt", c.get("attempts_used", ""))))
            if img and os.path.isfile(img):
                name = "{:02d}_{}.png".format(idx, _safe_name(c.get("garment"), "result"))
                z.write(img, arcname=name)
                packed += 1
        z.writestr("清单.txt", "\n".join(lines) + "\n")
    buf.seek(0)
    return packed, buf.getvalue()


def dump_json(obj):
    return json.dumps(obj, ensure_ascii=False)


def global_metrics():
    """扫一遍全部 runs/*.jsonl，给出全站的首轮通过率和平均重试。"""
    store = _store()
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
