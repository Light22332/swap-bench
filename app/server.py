"""零依赖 HTTP 服务。

为什么不用 FastAPI：这个项目要在 ComfyUI 自带的 python 里直接跑起来，
少一个 pip 安装就少一个"面试现场装不上"的失败点。代价是没有异步，
所以任务放线程里跑、页面轮询，够用。
"""
import base64
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .pipeline import new_job, run_job
from .store import Store, compute_metrics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
UPLOADS = os.path.join(ROOT, "uploads")

JOBS = {}
JOBS_LOCK = threading.Lock()

CONFIG = {}
CONFIG_LOCK = threading.Lock()


def load_config():
    global CONFIG
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("paths", {})
    cfg["paths"].setdefault("outputs", os.path.join(ROOT, "outputs"))
    cfg["paths"].setdefault("runs", os.path.join(ROOT, "runs"))
    cfg["paths"].setdefault("uploads", UPLOADS)
    with CONFIG_LOCK:
        CONFIG = cfg
    return cfg


def _img_url(path):
    """把项目内的绝对路径转成 /img 可访问的 URL；越界返回 None。"""
    if not path:
        return None
    try:
        rel = os.path.relpath(path, ROOT)
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    return "/img?path=" + urllib.parse.quote(rel.replace("\\", "/"))


def _decorate(job_dict):
    """给返回给前端的结构补上图片 URL，前端就不用关心文件系统。"""
    for c in job_dict.get("cases", []):
        for a in c.get("attempts", []):
            if a.get("stage") == "generate" and a.get("image"):
                a["image_url"] = _img_url(a["image"])
        c["final_url"] = _img_url(c.get("final_image"))
    return job_dict


def _load_job_from_store(jid):
    """重启后从 JSONL 把一次历史任务还原出来，让 ?job=xxx 的链接长期有效。"""
    store = Store(CONFIG.get("paths", {}).get("runs", os.path.join(ROOT, "runs")))
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
    ordered = [cases[k] for k in sorted(cases)]
    return {
        "id": jid,
        "state": "done",
        "elapsed_s": metrics.get("total_generate_s", 0),
        "judge_mode": metrics.get("judge_mode", "rules"),
        "cases": ordered,
        "metrics": metrics,
        "error": None,
        "replayed": True,
    }


def _safe_path(rel):
    """把 URL 里的相对路径钉死在项目目录内，防止 ../ 穿越。"""
    rel = rel.replace("\\", "/").lstrip("/")
    full = os.path.realpath(os.path.join(ROOT, rel))
    if not full.startswith(os.path.realpath(ROOT) + os.sep):
        return None
    return full


class Handler(BaseHTTPRequestHandler):
    server_version = "SwapBench/0.1"
    protocol_version = "HTTP/1.1"

    # ---------- 基础设施 ----------

    def log_message(self, fmt, *args):
        if os.environ.get("SWAP_VERBOSE"):
            super().log_message(fmt, *args)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data, ctype, cache="max-age=120"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path, cache="max-age=120"):
        if not path or not os.path.isfile(path):
            self._json({"error": "not found", "path": path}, 404)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            self._bytes(f.read(), ctype, cache)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ---------- 路由 ----------

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path

        if p in ("/", "/index.html"):
            return self._file(os.path.join(WEB, "index.html"), cache="no-cache")
        if p.startswith("/static/"):
            name = p[len("/static/"):]
            if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
                return self._json({"error": "bad name"}, 400)
            # 页面代码一直在改，别让浏览器缓存住
            return self._file(os.path.join(WEB, name), cache="no-cache")
        if p == "/img":
            q = urllib.parse.parse_qs(u.query)
            rel = (q.get("path") or [""])[0]
            return self._file(_safe_path(rel))
        if p == "/api/config":
            with CONFIG_LOCK:
                cfg = CONFIG
            face_models = all(
                os.path.isfile(os.path.join(ROOT, cfg.get("models_dir", "models"), f))
                for f in ("face_detection_yunet.onnx", "face_recognition_sface.onnx")
            )
            hand_models = all(
                os.path.isfile(os.path.join(ROOT, cfg.get("models_dir", "models"), f))
                for f in ("palm_detection_mediapipe_2023feb.onnx",
                          "handpose_estimation_mediapipe_2023feb.onnx")
            )
            prep_cfg = cfg.get("prep", {})
            parse_dir = os.path.join(ROOT, cfg.get("models_dir", "models"), "segformer_b2_clothes")
            parse_ready = all(os.path.isfile(os.path.join(parse_dir, f))
                              for f in ("config.json", "model.safetensors"))
            return self._json({
                "backend": cfg.get("backend"),
                "judge": {"mode": "local", "face_models": face_models,
                          "hand_models": hand_models},
                "prep": {"enabled": prep_cfg.get("enabled", True),
                         "mode": prep_cfg.get("mode", "parse"),
                         "parse_model": parse_ready},
                "max_attempts": cfg.get("pipeline", {}).get("max_attempts", 2),
                "instruction": cfg.get("instruction", ""),
                "negative": cfg.get("negative", ""),
                "sampling": cfg.get("sampling", {}),
            })
        if p.startswith("/api/job/"):
            jid = p[len("/api/job/"):]
            with JOBS_LOCK:
                job = JOBS.get(jid)
            if job:
                return self._json(_decorate(job.to_dict()))
            replay = _load_job_from_store(jid)
            if replay:
                return self._json(_decorate(replay))
            return self._json({"error": "no such job"}, 404)
        if p == "/api/jobs":
            with JOBS_LOCK:
                items = sorted(JOBS.values(), key=lambda j: -j.started)[:20]
            return self._json([{"id": j.id, "state": j.state,
                                "elapsed_s": round((j.finished or time.time()) - j.started, 1),
                                "cases": len(j.cases)} for j in items])
        if p == "/api/metrics":
            return self._json(self._global_metrics())

        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path

        if p == "/api/upload":
            return self._upload()
        if p == "/api/samples":
            return self._samples()
        if p == "/api/run":
            return self._run()
        if p == "/api/config":
            data = self._body()
            with CONFIG_LOCK:
                for k in ("backend", "instruction", "negative"):
                    if k in data:
                        CONFIG[k] = data[k]
                if "judge" in data and isinstance(data["judge"], dict):
                    CONFIG.setdefault("judge", {}).update(data["judge"])
            return self._json({"ok": True})

        return self._json({"error": "not found"}, 404)

    # ---------- 业务 ----------

    def _upload(self):
        data = self._body()
        name = data.get("name") or "upload.jpg"
        raw = data.get("data") or ""
        if "," in raw and raw.strip().startswith("data:"):
            raw = raw.split(",", 1)[1]
        try:
            blob = base64.b64decode(raw)
        except Exception:
            return self._json({"error": "base64 解码失败"}, 400)
        if len(blob) > 30 * 1024 * 1024:
            return self._json({"error": "文件太大（上限 30MB）"}, 413)

        os.makedirs(UPLOADS, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.\-]", "_", os.path.basename(name))
        stamp = time.strftime("%m%d%H%M%S")
        fn = f"{stamp}_{safe}"
        full = os.path.join(UPLOADS, fn)
        with open(full, "wb") as f:
            f.write(blob)
        return self._json({"ok": True, "file": fn,
                           "path": os.path.join("uploads", fn),
                           "url": "/img?path=" + urllib.parse.quote(os.path.join("uploads", fn).replace("\\", "/")),
                           "size": len(blob)})

    def _samples(self):
        """把示例图复制进 uploads，让页面一键就能跑一次。"""
        src_dir = os.path.join(ROOT, "samples")
        want = {
            "person": "case1_person.jpg",
            "garments": ["case1_garment.jpg", "case3_garment.jpg"],
        }
        os.makedirs(UPLOADS, exist_ok=True)

        def copy_in(fn):
            src = os.path.join(src_dir, fn)
            if not os.path.isfile(src):
                return None
            dst_name = "sample_" + fn
            dst = os.path.join(UPLOADS, dst_name)
            shutil.copy2(src, dst)
            rel = os.path.join("uploads", dst_name).replace("\\", "/")
            return {"file": dst_name, "path": rel,
                    "url": "/img?path=" + urllib.parse.quote(rel),
                    "name": fn}

        person = copy_in(want["person"])
        garments = [g for g in (copy_in(f) for f in want["garments"]) if g]
        if not person or not garments:
            return self._json({"error": "samples 目录里缺少示例图"}, 404)
        return self._json({"ok": True, "person": person, "garments": garments})

    def _run(self):
        data = self._body()
        person = data.get("person")
        garments = data.get("garments") or []
        if not person or not garments:
            return self._json({"error": "需要 1 张人像和至少 1 张服装图"}, 400)

        person_full = _safe_path(person)
        if not person_full or not os.path.isfile(person_full):
            return self._json({"error": f"找不到人像：{person}"}, 400)

        glist = []
        for g in garments:
            gp = g.get("path") if isinstance(g, dict) else g
            gf = _safe_path(gp)
            if not gf or not os.path.isfile(gf):
                return self._json({"error": f"找不到服装图：{gp}"}, 400)
            # 前端传了原始文件名就用它，否则退回磁盘名（带时间戳前缀，不好看）
            label = (g.get("name") if isinstance(g, dict) else None) or os.path.basename(gp)
            glist.append({"name": label, "path": gf})

        with CONFIG_LOCK:
            cfg = json.loads(json.dumps(CONFIG))  # 快照，避免任务中途被改
            if data.get("backend"):
                cfg["backend"] = data["backend"]
            instruction = data.get("instruction") or cfg.get("instruction", "")
            negative = data.get("negative") or cfg.get("negative", "")

        job = new_job(person_full, glist, instruction, negative, cfg)
        with JOBS_LOCK:
            JOBS[job.id] = job

        t = threading.Thread(target=_run_guarded, args=(job, cfg), daemon=True)
        t.start()
        return self._json({"ok": True, "job_id": job.id})

    def _global_metrics(self):
        store = Store(CONFIG.get("paths", {}).get("runs", os.path.join(ROOT, "runs")))
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
        # 逐 case 的平均重试与首轮通过率
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


def _run_guarded(job, cfg):
    try:
        run_job(job, cfg)
    except Exception as e:
        import traceback
        traceback.print_exc()
        job.error = f"{type(e).__name__}: {e}"
        job.state = "error"


def serve():
    cfg = load_config()
    host = cfg.get("server", {}).get("host", "127.0.0.1")
    port = cfg.get("server", {}).get("port", 8770)
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"换装工作台 → http://{host}:{port}")
    print(f"后端 {cfg.get('backend')} | 质检 {CONFIG.get('judge', {}).get('backend')}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
