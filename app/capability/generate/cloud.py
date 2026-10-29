"""云端图像编辑后端。两种接口形状：

- **openai**：`POST {base}/images/edits`，multipart 带两张图，认 b64_json / url / data URL。
- **dashscope**：阿里云百炼的原生多模态接口，`POST {base}/api/v1/services/aigc/multimodal-generation/generation`，
  JSON 里塞两个 data URL 图 + 文字，回来是一个临时图片链接。

`cloud.shape` 默认 `auto`：地址里带 `aliyuncs.com` 就走 dashscope，其余走 openai。
百炼那条路 2026-10-30 用真 key 跑通过（qwen-image-2.1-pro，换衣服、脸保持不变）；
openai 那条只验过客户端逻辑（`tools/tests/test_cloud.py` 用假服务器），没花真钱。

两个刻意的选择：
1. 没配好不抛异常，返回 error_kind=auth 的失败结果——上层照常记账，页面会说人话。
2. 图一律立即下载到本地：百炼给的是带过期时间的临时链接，存链接没用。
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid

from ...core import config as app_config
from .base import GenResult

BOUNDARY = "----swapbench" + uuid.uuid4().hex[:16]

HTTP_KINDS = {401: "auth", 403: "auth", 429: "rate_limit"}


def _part(name, value):
    return (f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n").encode()


def _mime(blob):
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def _file_part(name, path):
    fn = os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()
    head = (f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{fn}"\r\n'
            f"Content-Type: {_mime(data)}\r\n\r\n").encode()
    return head + data + b"\r\n"


def _data_url(path):
    with open(path, "rb") as f:
        blob = f.read()
    return f"data:{_mime(blob)};base64," + base64.b64encode(blob).decode()


def _error_text(raw):
    """从错误响应里挑一句能看懂的话。百炼是 {code,message}，OpenAI 是 {error:{message}}。"""
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return raw[:300]
    if not isinstance(obj, dict):
        return raw[:300]
    if obj.get("message"):
        code = obj.get("code")
        return (f"{code}：{obj['message']}" if code else str(obj["message"]))[:300]
    err = obj.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err)[:300]
    if isinstance(err, str):
        return err[:300]
    return json.dumps(obj, ensure_ascii=False)[:300]


class CloudBackend:
    name = "cloud"

    def __init__(self, cfg):
        c = app_config.section(cfg, "cloud")
        self.base_url = (c.get("base_url") or "").rstrip("/")
        self.api_key = c.get("api_key") or ""
        self.model = c.get("model") or ""
        self.timeout = c.get("timeout") or 120
        self.size = (c.get("size") or "").strip()
        self.shape = (c.get("shape") or "auto").strip().lower()
        self.price = float(c.get("price_per_image") or 0)
        self.out_dir = app_config.outputs_dir(cfg)

    @property
    def configured(self):
        return bool(self.base_url and self.api_key and self.model)

    def resolve_shape(self):
        if self.shape in ("openai", "dashscope"):
            return self.shape
        return "dashscope" if "aliyuncs.com" in self.base_url else "openai"

    # ---------- 对外 ----------

    def generate(self, req):
        t0 = time.time()
        if not self.configured:
            return self._fail(t0, req, "auth",
                              "云端后端还没配好：到「设置」里填云端地址、密钥和模型名")
        if self.resolve_shape() == "dashscope":
            return self._dashscope(req, t0)
        return self._openai(req, t0)

    # ---------- OpenAI 兼容 ----------

    def _openai(self, req, t0):
        size = self._openai_size(req)
        body = b""
        body += _part("model", self.model)
        body += _part("prompt", req.instruction)
        body += _part("size", size)
        body += _part("n", "1")
        body += _part("response_format", "b64_json")   # 有的服务默认给 url，先要 base64
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
            raw = e.read().decode("utf-8", "replace")
            return self._fail(t0, req, HTTP_KINDS.get(e.code, "node_error"),
                              f"HTTP {e.code}：{_error_text(raw)}")
        except TimeoutError:
            return self._fail(t0, req, "timeout", f"等了 {self.timeout} 秒没返回")
        except urllib.error.URLError as e:
            return self._fail(t0, req, "network", f"连不上：{e.reason}")

        blob, how = self._extract(resp)
        if blob is None:
            return self._fail(t0, req, "node_error",
                              f"响应里没有图：{json.dumps(resp, ensure_ascii=False)[:300]}")
        return self._done(req, t0, blob, size, how, resp.get("usage"))

    # ---------- 百炼原生 ----------

    def native_root(self):
        """base_url 可以写成 host、host/api/v1、或 compatible-mode 那条，这里统一成 host/api/v1。"""
        base = self.base_url
        if "compatible-mode" in base:
            base = base.split("/compatible-mode")[0]
        base = base.rstrip("/")
        return base if base.endswith("/api/v1") else base + "/api/v1"

    def _dashscope(self, req, t0):
        size = (self.size or "1024x1024").replace("x", "*")
        payload = {
            "model": self.model,
            "input": {"messages": [{"role": "user", "content": [
                {"image": _data_url(req.person_path)},
                {"image": _data_url(req.garment_path)},
                {"text": req.instruction},
            ]}]},
            "parameters": {"size": size, "n": 1, "watermark": False},
        }
        if req.negative:
            payload["parameters"]["negative_prompt"] = req.negative

        r = urllib.request.Request(
            self.native_root() + "/services/aigc/multimodal-generation/generation",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
        )
        try:
            resp = json.load(urllib.request.urlopen(r, timeout=self.timeout))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            return self._fail(t0, req, HTTP_KINDS.get(e.code, "node_error"),
                              f"HTTP {e.code}：{_error_text(raw)}")
        except TimeoutError:
            return self._fail(t0, req, "timeout", f"等了 {self.timeout} 秒没返回")
        except urllib.error.URLError as e:
            return self._fail(t0, req, "network", f"连不上：{e.reason}")

        link = self._first_image(resp)
        if not link:
            return self._fail(t0, req, "node_error",
                              f"响应里没有图：{json.dumps(resp, ensure_ascii=False)[:300]}")
        blob = self._download(link)
        if blob is None:
            return self._fail(t0, req, "network", "拿到图片链接但下载失败（链接通常几分钟就过期）")
        return self._done(req, t0, blob, size, "url", resp.get("usage"))

    @staticmethod
    def _first_image(resp):
        try:
            content = resp["output"]["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        if isinstance(content, str):
            return content if content.startswith("http") else None
        for item in content:
            if isinstance(item, dict) and item.get("image"):
                return item["image"]
        return None

    def _download(self, url):
        try:
            return urllib.request.urlopen(url, timeout=self.timeout).read()
        except Exception:
            return None

    # ---------- 公共 ----------

    def _done(self, req, t0, blob, size, how, usage):
        dst = self._save(blob, req.prefix)
        meta = {"size": size, "via": how, "shape": self.resolve_shape()}
        if isinstance(usage, dict):
            meta["usage"] = usage
        return GenResult(ok=True, image_path=dst, backend=self.name, model=self.model,
                         latency_s=time.time() - t0, cost=round(self.price, 4),
                         seed=req.seed, meta=meta)

    def _fail(self, t0, req, kind, message):
        return GenResult(ok=False, backend=self.name, model=self.model,
                         latency_s=time.time() - t0, seed=req.seed,
                         error=message, error_kind=kind)

    def _openai_size(self, req):
        if self.size:
            return self.size
        return "1024x1536" if int(req.resolution or 1024) >= 900 else "1024x1024"

    def _extract(self, resp):
        """OpenAI 那边：返回 (图片字节, 来源)。拿不到返回 (None, "")。"""
        try:
            item = resp["data"][0]
        except (KeyError, IndexError, TypeError):
            return None, ""

        b64 = item.get("b64_json") if isinstance(item, dict) else None
        if isinstance(b64, str) and b64:
            if b64.startswith("data:") and "," in b64:
                b64 = b64.split(",", 1)[1]
            try:
                return base64.b64decode(b64), "b64_json"
            except (ValueError, TypeError):
                return None, ""

        url = item.get("url") if isinstance(item, dict) else None
        if isinstance(url, str) and url:
            if url.startswith("data:") and "," in url:
                try:
                    return base64.b64decode(url.split(",", 1)[1]), "data_url"
                except (ValueError, TypeError):
                    return None, ""
            blob = self._download(url)
            return (blob, "url") if blob else (None, "")
        return None, ""

    def _save(self, blob, prefix):
        ext = ".png" if blob[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg" if blob[:2] == b"\xff\xd8" else ".png"
        os.makedirs(self.out_dir, exist_ok=True)
        name = f"{prefix or 'cloud'}_{uuid.uuid4().hex[:6]}{ext}"
        dst = os.path.join(self.out_dir, name)
        with open(dst, "wb") as f:
            f.write(blob)
        return dst
