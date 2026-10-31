"""本地 ComfyUI 后端。

调用链：POST /prompt → 轮询 /history/{id} → GET /view 取图。
这里比随手写的脚本多做了三件事：失败分类、耗时拆分（排队/生成）、取图落地。
"""
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from ...core import config as app_config
from .graph import build_swap_graph
from .base import BackendError, GenResult

# 轮询 /history 连续失败这么多次才放弃：一次 URLError 可能只是 ComfyUI 忙了一下
POLL_FAILS = 5


class ComfyUIBackend:
    name = "comfyui"

    def __init__(self, cfg):
        c = cfg["comfyui"]
        self.base_url = c["base_url"].rstrip("/")
        self.input_dir = c["input_dir"]
        self.models = cfg["models"]
        self.sampling = cfg["sampling"]
        self.out_dir = app_config.outputs_dir(cfg)
        self.cold_start_seconds = None

    # ---------- 对外 ----------

    def generate(self, req):
        t0 = time.time()
        person_name = self._stage(req.person_path, prefix="src_person_")
        garment_name = self._stage(req.garment_path, prefix="src_garment_")

        seed = req.seed
        if seed is None or seed < 0:
            seed = int(time.time() * 1000) % (2**31 - 1)

        graph = build_swap_graph(
            person_name, garment_name, req.instruction, req.negative,
            req.cfg or self.sampling["cfg"],
            req.steps or self.sampling["steps"],
            seed,
            req.resolution or self.sampling["resolution"],
            self.models,
            prefix=req.prefix,
        )

        t_submit = time.time()
        try:
            pid = self._submit(graph)
        except BackendError as e:
            return GenResult(ok=False, backend=self.name, model=self.models["unet"],
                             latency_s=time.time() - t0, seed=seed,
                             error=e.message, error_kind=e.kind)

        try:
            hist = self._wait(pid)
        except BackendError as e:
            return GenResult(ok=False, backend=self.name, model=self.models["unet"],
                             latency_s=time.time() - t0, seed=seed,
                             error=e.message, error_kind=e.kind)

        latency = time.time() - t0
        queue_s = t_submit - t0
        try:
            img_path = self._fetch(hist, req.prefix)
        except BackendError as e:
            return GenResult(ok=False, backend=self.name, model=self.models["unet"],
                             latency_s=latency, seed=seed,
                             error=e.message, error_kind=e.kind)

        return GenResult(
            ok=True, image_path=img_path, backend=self.name,
            model=self.models["unet"], latency_s=latency, cost=0.0, seed=seed,
            meta={"queue_s": round(queue_s, 2), "prompt_id": pid},
        )

    def system_stats(self, timeout=3.0):
        """探活：打一枪 /system_stats，拿不到返回 None，不抛。

        这个接口不碰模型，所以 ComfyUI 刚起来、权重还没进显存时也能答上来。
        上层用它决定"现在点开始会不会白等"。
        """
        try:
            return json.load(urllib.request.urlopen(
                self.base_url + "/system_stats", timeout=timeout))
        except Exception:
            return None

    def ping(self, timeout=3.0):
        return self.system_stats(timeout) is not None

    # ---------- 内部 ----------

    def _stage(self, path, prefix):
        """把输入图放进 ComfyUI 的 input 目录，因为 LoadImage 只认那里。"""
        if not os.path.exists(path):
            raise BackendError("input", f"找不到输入图：{path}")
        name = prefix + os.path.basename(path)
        dst = os.path.join(self.input_dir, name)
        if os.path.abspath(dst) != os.path.abspath(path):
            shutil.copy2(path, dst)
        return name

    def _submit(self, graph):
        body = json.dumps({"prompt": graph, "client_id": uuid.uuid4().hex}).encode()
        r = urllib.request.Request(self.base_url + "/prompt", data=body,
                                   headers={"Content-Type": "application/json"})
        try:
            resp = json.load(urllib.request.urlopen(r, timeout=60))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            raise BackendError("node_error", f"提交被拒 HTTP {e.code}: {raw[:600]}")
        except urllib.error.URLError as e:
            raise BackendError("network", f"连不上 ComfyUI：{e.reason}")
        if "prompt_id" not in resp:
            raise BackendError("node_error", f"响应异常：{json.dumps(resp)[:400]}")
        return resp["prompt_id"]

    def _history(self, pid):
        """问一次 ComfyUI 跑完没有。失败让调用方决定重试还是放弃。"""
        return json.load(urllib.request.urlopen(
            f"{self.base_url}/history/{pid}", timeout=30))

    def _wait(self, pid, timeout=900, interval=2.0):
        """等 ComfyUI 跑完。

        网络抖一下不能把整单废掉：连续失败 POLL_FAILS 次才报错，中间退避重试。
        一直没跑完就按总超时收场，报错里提示去看 ComfyUI 的控制台。"""
        t0 = time.time()
        fails = 0
        base = interval
        while True:
            if time.time() - t0 >= timeout:
                raise BackendError("timeout",
                                   f"等待 {timeout}s 仍未完成（ComfyUI 可能卡住了，"
                                   f"去看看它的控制台）")
            time.sleep(interval)
            try:
                hist = self._history(pid)
            except (urllib.error.URLError, OSError, ValueError) as e:
                fails += 1
                if fails >= POLL_FAILS:
                    reason = getattr(e, "reason", e)
                    raise BackendError("network", f"轮询连续失败 {fails} 次：{reason}")
                interval = min(interval * 2, 10.0)      # 退避，别把 ComfyUI 打爆
                continue
            fails = 0
            interval = base
            if pid in hist:
                status = hist[pid].get("status", {})
                if status.get("status_str") == "error":
                    msg = json.dumps(status, ensure_ascii=False)
                    kind = "vram" if "out of memory" in msg.lower() else "node_error"
                    raise BackendError(kind, msg[:800])
                return hist[pid]

    def _fetch(self, hist, prefix):
        for node_out in hist.get("outputs", {}).values():
            for img in node_out.get("images", []):
                q = urllib.parse.urlencode({
                    "filename": img["filename"],
                    "subfolder": img.get("subfolder", ""),
                    "type": "output",
                })
                try:
                    data = urllib.request.urlopen(
                        f"{self.base_url}/view?{q}", timeout=120).read()
                except urllib.error.URLError as e:
                    raise BackendError("network", f"取图失败：{e.reason}")
                os.makedirs(self.out_dir, exist_ok=True)
                dst = os.path.join(self.out_dir, img["filename"])
                with open(dst, "wb") as f:
                    f.write(data)
                return dst
        raise BackendError("node_error", "history 里没有输出图")
