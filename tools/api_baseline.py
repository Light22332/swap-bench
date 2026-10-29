"""接口基线：重构 HTTP 层前后，接口的"形状"必须一致。

比的不只是状态码，还有响应 JSON 的键结构（每一层的键名，数组只看第一个元素），
以及二进制响应的 Content-Type。值可以变（任务 id、耗时、时间戳），结构不能变。

  python tools/api_baseline.py record    # 把当前服务的结构存成基线
  python tools/api_baseline.py check     # 拿当前服务和基线比

基线文件是 tools/api_baseline.json，进版本库，这样以后谁改接口都能对一眼。
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_FILE = os.path.join(ROOT, "tools", "api_baseline.json")
HOST = "http://127.0.0.1:8770"

PNG_1PX = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da63f8cfc000000301010018dd8db00000000049454e44ae426082"
)).decode()


def shape(obj, depth=0):
    """把 JSON 压成"结构"：只看键和类型，不看值。"""
    if depth > 6:
        return "..."
    if isinstance(obj, dict):
        return {k: shape(v, depth + 1) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [shape(obj[0], depth + 1)] if obj else []
    if obj is None:
        return "null"
    return type(obj).__name__


def call(method, path, body=None):
    url = HOST + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            ctype = r.headers.get("Content-Type", "")
            status = r.status
    except urllib.error.HTTPError as e:
        raw, ctype, status = e.read(), e.headers.get("Content-Type", ""), e.code
    if "json" in ctype:
        try:
            return {"status": status, "type": "json", "shape": shape(json.loads(raw))}
        except Exception:
            return {"status": status, "type": "bad-json", "shape": raw[:80].decode("utf-8", "replace")}
    return {"status": status, "type": ctype.split(";")[0], "shape": "binary"}


def newest_job():
    runs = os.path.join(ROOT, "runs")
    files = sorted(f[:-6] for f in os.listdir(runs) if f.endswith(".jsonl")) if os.path.isdir(runs) else []
    return files[-1] if files else "none"


def probes():
    job = newest_job()
    return {
        "GET /api/config": ("GET", "/api/config", None),
        "GET /api/jobs": ("GET", "/api/jobs", None),
        "GET /api/metrics": ("GET", "/api/metrics", None),
        "GET /api/job/<id>": ("GET", f"/api/job/{job}", None),
        "GET /api/job/不存在": ("GET", "/api/job/nosuchjob", None),
        "GET /img?path=": ("GET", "/img?path=" + urllib.parse.quote("outputs/page.png"), None),
        "GET /static/app.js": ("GET", "/static/app.js", None),
        "GET /不存在": ("GET", "/no/such/path", None),
        "POST /api/upload": ("POST", "/api/upload", {"name": "probe.png", "data": PNG_1PX}),
        "POST /api/run 空": ("POST", "/api/run", {}),
        "POST /api/config 空": ("POST", "/api/config", {}),
    }


def snapshot():
    out = {}
    for name, (method, path, body) in probes().items():
        try:
            out[name] = call(method, path, body)
        except Exception as e:
            out[name] = {"status": 0, "type": "error", "shape": f"{type(e).__name__}: {e}"}
    return out


def diff(old, new):
    lines = []
    for name in old:
        a, b = old.get(name), new.get(name)
        if a == b:
            continue
        if a is None:
            lines.append(f"{name}: 新增")
        elif b is None:
            lines.append(f"{name}: 消失")
        elif a["status"] != b["status"]:
            lines.append(f"{name}: 状态码 {a['status']} → {b['status']}")
        elif a["type"] != b["type"]:
            lines.append(f"{name}: 类型 {a['type']} → {b['type']}")
        else:
            lines.append(f"{name}: 结构变了\n    旧 {json.dumps(a['shape'], ensure_ascii=False)[:300]}"
                         f"\n    新 {json.dumps(b['shape'], ensure_ascii=False)[:300]}")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["record", "check"])
    args = ap.parse_args()

    if args.action == "record":
        snap = snapshot()
        with open(BASE_FILE, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"已记录 {len(snap)} 个接口 → {os.path.relpath(BASE_FILE, ROOT)}")
        for name, r in snap.items():
            print(f"  {r['status']}  {name}")
        return 0

    with open(BASE_FILE, encoding="utf-8") as f:
        old = json.load(f)
    lines = diff(old, snapshot())
    if not lines:
        print(f"接口结构与基线一致（{len(old)} 个）")
        return 0
    print(f"{len(lines)} 处不一致：")
    for line in lines:
        print("  " + line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
