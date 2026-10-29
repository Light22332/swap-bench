"""云端图像编辑后端（OpenAI 兼容的 /images/edits 形态）。

刻意做成"未配置就能跑其余部分"：没有 api_key 时它直接抛 auth 错误，
上层记一条失败，不会影响本地后端工作。

注意：这条路径没有用真实 key 验证过，README 里标注了。接口形状按
OpenAI images/edits 的 multipart 约定：image[] + prompt + model + size。
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid

from ..core import config as app_config
from .base import BackendError, GenResult

BOUNDARY = "----dshswap" + "0123456789abcdef"


def _part(name, value):
    return (f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n").encode()


def _file_part(name, path):
    fn = os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()
    head = (f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{fn}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n").encode()
    return head + data + b"\r\n"


class CloudBackend:
    name = "cloud"

    def __init__(self, cfg):
        c = app_config.section(cfg, "cloud")
        self.base_url = (c.get("base_url") or "").rstrip("/")
        self.api_key = c.get("api_key") or ""
        self.model = c.get("model") or ""
        self.timeout = c.get("timeout", 120)
        self.out_dir = app_config.outputs_dir(cfg)

    @property
    def configured(self):
        return bool(self.base_url and self.api_key and self.model)

    def generate(self, req):
        t0 = time.time()
        if not self.configured:
            raise BackendError(
                "auth",
                "云端后端未配置：在 config.json 里填 cloud.base_url / api_key / model",
            )

        size = self._size_for(req.resolution)
        body = b""
        body += _part("model", self.model)
        body += _part("prompt", req.instruction)
        body += _part("size", size)
        body += _part("n", "1")
        if req.seed is not None and req.seed >= 0:
            body += _part("seed", str(req.seed))
        body += _file_part("image[]", req.person_path)
        body += _file_part("image[]", req.garment_path)
        body += f"--{BOUNDARY}--\r\n".encode()

        r = urllib.request.Request(
            self.base_url + "/images/edits", data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={BOUNDARY}",
            },
        )
        try:
            resp = json.load(urllib.request.urlopen(r, timeout=self.timeout))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")[:600]
            kind = {401: "auth", 403: "auth", 429: "rate_limit"}.get(e.code, "node_error")
            return GenResult(ok=False, backend=self.name, model=self.model,
                             latency_s=time.time() - t0, error=f"HTTP {e.code}: {raw}",
                             error_kind=kind)
        except urllib.error.URLError as e:
            return GenResult(ok=False, backend=self.name, model=self.model,
                             latency_s=time.time() - t0,
                             error=f"网络错误：{e.reason}", error_kind="network")

        try:
            b64 = resp["data"][0]["b64_json"]
        except (KeyError, IndexError, TypeError):
            return GenResult(ok=False, backend=self.name, model=self.model,
                             latency_s=time.time() - t0,
                             error=f"响应里没有 b64_json：{json.dumps(resp)[:300]}",
                             error_kind="node_error")

        os.makedirs(self.out_dir, exist_ok=True)
        dst = os.path.join(self.out_dir, f"cloud_{uuid.uuid4().hex[:8]}.png")
        with open(dst, "wb") as f:
            f.write(base64.b64decode(b64))

        return GenResult(ok=True, image_path=dst, backend=self.name, model=self.model,
                         latency_s=time.time() - t0, cost=0.0, seed=req.seed,
                         meta={"size": size})

    @staticmethod
    def _size_for(resolution):
        # 竖版人像常见比例；resolution 是面积口径，这里换算成边
        side = max(768, int(resolution))
        return f"{int(side * 0.75)}x{side}"
