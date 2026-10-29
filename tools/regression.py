"""回归基线：固定八组输入跑一遍，把数字存下来，改代码前后一比就知道有没有变差。

生成是随机的，所以比的是分布不是像素：合格率、首轮通过率、平均重试、每项检查的
通过率、人脸相似度分布。同一条代码连跑两次也会有小幅波动，看的是"有没有明显掉"。

  python tools/regression.py run --out reports/base.json
  python tools/regression.py compare reports/base.json reports/after.json

跑一组要一两分钟（要真生成），八组十几分钟。跑到一半断了就重跑，
已经跑过的组会复用同一个 job 记录里的结果——但简单起见这里不做断点续跑。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "http://127.0.0.1:8770"
SAMPLES = os.path.join(ROOT, "samples")

PAIRS = [
    ("case1_person.jpg", "case1_garment.jpg"),
    ("case1_person.jpg", "case3_garment.jpg"),
    ("case1_person.jpg", "case4_garment.jpg"),
    ("case1_person.jpg", "case4_garment_crop.jpg"),
    ("case4_person.png", "case1_garment.jpg"),
    ("case4_person.png", "case3_garment.jpg"),
    ("case4_person.png", "case4_garment.jpg"),
    ("case4_person.png", "case4_garment_crop.jpg"),
]


def call(path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(HOST + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def wait_job(jid, timeout=1200):
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = call("/api/job/" + jid)
        if job.get("state") not in ("running", "pending"):
            return job
        time.sleep(3)
    raise TimeoutError(jid)


def one_pair(person, garment):
    rel_person = os.path.join("samples", person).replace("\\", "/")
    rel_garment = os.path.join("samples", garment).replace("\\", "/")
    data = call("/api/run", {"person": rel_person,
                             "garments": [{"path": rel_garment, "name": garment}]})
    job = wait_job(data["job_id"])
    case = (job.get("cases") or [{}])[0]
    verdict = case.get("verdict") or {}
    checks = verdict.get("checks") or {}
    return {
        "person": person,
        "garment": garment,
        "job": job.get("id"),
        "state": case.get("state"),
        "passed": bool(case.get("passed")),
        "score": verdict.get("score"),
        "attempts": case.get("attempts_used"),
        "elapsed_s": job.get("elapsed_s"),
        "checks": {k: (v or {}).get("pass") for k, v in checks.items()},
        "face_sim": (checks.get("face_preserved") or {}).get("sim"),
    }


def summarize(rows):
    total = len(rows)
    passed = sum(1 for r in rows if r["passed"])
    first = sum(1 for r in rows if r["passed"] and r["attempts"] == 1)
    attempts = [r["attempts"] for r in rows if r["attempts"]]
    elapsed = [r["elapsed_s"] for r in rows if r["elapsed_s"]]
    keys = sorted({k for r in rows for k in r["checks"]})
    per_check = {}
    for k in keys:
        judged = [r["checks"][k] for r in rows if r["checks"].get(k) is not None]
        if judged:
            per_check[k] = round(sum(1 for v in judged if v) / len(judged), 3)
    sims = [r["face_sim"] for r in rows if r["face_sim"] is not None]
    return {
        "cases": total,
        "pass_rate": round(passed / total, 3) if total else 0,
        "first_pass_rate": round(first / total, 3) if total else 0,
        "avg_attempts": round(sum(attempts) / len(attempts), 2) if attempts else 0,
        "avg_elapsed_s": round(sum(elapsed) / len(elapsed), 1) if elapsed else 0,
        "per_check_pass_rate": per_check,
        "face_sim": sorted(round(s, 3) for s in sims),
    }


def save(out, rows):
    """每跑完一组就落盘一次。八组要十几分钟，中途关机不至于全丢。"""
    report = {"when": time.strftime("%Y-%m-%dT%H:%M:%S"), "pairs": rows,
              "summary": summarize(rows)}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


def cmd_run(args):
    out = args.out
    if not os.path.isabs(out):
        out = os.path.join(ROOT, out)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    rows = []
    done = set()
    if args.resume and os.path.isfile(out):
        old = json.load(open(out, encoding="utf-8"))
        rows = [r for r in old.get("pairs", []) if r.get("state") != "error"]
        done = {(r["person"], r["garment"]) for r in rows}
        print(f"接着上次跑：已有 {len(rows)} 组")

    for i, (person, garment) in enumerate(PAIRS, 1):
        if (person, garment) in done:
            print(f"[{i}/{len(PAIRS)}] {person} + {garment} 已有，跳过", flush=True)
            continue
        print(f"[{i}/{len(PAIRS)}] {person} + {garment} …", flush=True)
        try:
            row = one_pair(person, garment)
        except Exception as e:
            row = {"person": person, "garment": garment, "job": None, "state": "error",
                   "passed": False, "score": None, "attempts": 0, "elapsed_s": 0,
                   "checks": {}, "face_sim": None, "error": f"{type(e).__name__}: {e}"}
        rows.append(row)
        save(out, rows)
        print(f"     {'通过' if row['passed'] else '不过'}  {row.get('attempts')} 次  "
              f"{row.get('elapsed_s')}s  {row.get('error', '')}", flush=True)

    report = save(out, rows)
    print(f"\n已写入 {os.path.relpath(out, ROOT)}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


def cmd_compare(args):
    a = json.load(open(args.before, encoding="utf-8"))
    b = json.load(open(args.after, encoding="utf-8"))
    sa, sb = a["summary"], b["summary"]
    print(f"{'指标':18s} {'之前':>10s} {'之后':>10s}   变化")
    for key in ("pass_rate", "first_pass_rate", "avg_attempts", "avg_elapsed_s"):
        va, vb = sa.get(key), sb.get(key)
        mark = ""
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            d = vb - va
            mark = "→" if abs(d) < 1e-9 else (f"{d:+.3f}")
        print(f"{key:18s} {va!s:>10s} {vb!s:>10s}   {mark}")

    print("\n每项检查通过率")
    keys = sorted(set(sa.get("per_check_pass_rate", {})) | set(sb.get("per_check_pass_rate", {})))
    for k in keys:
        va = sa.get("per_check_pass_rate", {}).get(k)
        vb = sb.get("per_check_pass_rate", {}).get(k)
        print(f"  {k:22s} {va!s:>6s} → {vb!s:>6s}")

    flips = []
    for ra in a["pairs"]:
        for rb in b["pairs"]:
            if ra["person"] == rb["person"] and ra["garment"] == rb["garment"]:
                if ra["passed"] != rb["passed"]:
                    flips.append(f"{ra['person']} + {ra['garment']}: "
                                 f"{'通过' if ra['passed'] else '不过'} → "
                                 f"{'通过' if rb['passed'] else '不过'}")
    print("\n翻转" if flips else "\n没有翻转")
    for line in flips:
        print("  " + line)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="跑一遍并把结果存下来")
    r.add_argument("--out", default="reports/regression.json")
    r.add_argument("--resume", action="store_true", help="接着上次的报告跑，跳过已完成的那几组")
    c = sub.add_parser("compare", help="两份报告对比")
    c.add_argument("before")
    c.add_argument("after")
    args = ap.parse_args()
    return cmd_run(args) if args.cmd == "run" else cmd_compare(args)


if __name__ == "__main__":
    sys.exit(main())
