"""命令行跑一批：不给浏览器也能验证整条链路。

    python tools/run_batch.py --person samples/a.jpg --garments samples/b.jpg samples/c.jpg
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("SWAP_BASE", "http://127.0.0.1:8770")


def _post(path, obj, timeout=60):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode("utf-8", "replace")[:500])
        sys.exit(1)


def _get(path):
    return json.load(urllib.request.urlopen(BASE + path, timeout=30))


def upload(path):
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    r = _post("/api/upload", {"name": os.path.basename(path), "data": data})
    if not r.get("ok"):
        print("上传失败", r)
        sys.exit(1)
    return r["path"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", required=True)
    ap.add_argument("--garments", nargs="+", required=True)
    ap.add_argument("--instruction", default=None)
    ap.add_argument("--timeout", type=int, default=1200)
    a = ap.parse_args()

    person = upload(a.person)
    garments = [{"path": upload(g), "name": os.path.basename(g)} for g in a.garments]
    print(f"已上传：人像 1 张，服装 {len(garments)} 张")

    payload = {"person": person, "garments": garments}
    if a.instruction:
        payload["instruction"] = a.instruction
    r = _post("/api/run", payload)
    if not r.get("ok"):
        print("提交失败", r)
        sys.exit(1)

    jid = r["job_id"]
    print("任务", jid)

    t0 = time.time()
    last = ""
    while time.time() - t0 < a.timeout:
        time.sleep(2)
        job = _get("/api/job/" + jid)
        state = job["state"]
        live = next((c for c in job["cases"] if c["state"] == "running"), None)
        line = f'[{job["elapsed_s"]:6.1f}s] {state}'
        if live:
            line += f' · 第 {live["index"]}/{len(job["cases"])} 件 · {live["state"]}'
        if line != last:
            print(line)
            last = line
        if state in ("done", "error"):
            break

    job = _get("/api/job/" + jid)
    print("\n=== 结果 ===")
    for c in job["cases"]:
        print(f'  第 {c["index"]} 件 {c["garment"]}: {c["state"]} '
              f'· 用了 {c["attempts_used"]} 次')
    m = job.get("metrics") or {}
    print("\n=== 指标 ===")
    print(f'  合格率 {m.get("final_pass_rate")} | 首轮 {m.get("first_pass_rate")} '
          f'| 平均重试 {m.get("avg_attempts")} | 平均生成 {m.get("avg_generate_s")}s')
    print(f'  质检模式 {m.get("judge_mode")}')
    if m.get("failure_reasons"):
        print(f'  失败原因 {m["failure_reasons"]}')
    if job.get("error"):
        print("  错误", job["error"])
    print(f'\n任务号 {jid}（检验单文件 runs/{jid}.jsonl）')


if __name__ == "__main__":
    main()
