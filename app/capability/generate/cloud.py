"""云端图像编辑后端（OpenAI 兼容的 /images/edits 形态）。

三种响应都认：`data[0].b64_json`、`data[0].url`、以及内联的 `data:` URL。
错误按 HTTP 状态分类（auth / rate_limit / network / node_error），交给上层决定要不要重试。

这条路径没有用真实 key 打过，README 里标着"未用真实 key 验证"。客户端逻辑本身由
`tools/tests/test_cloud.py` 用本地假服务器覆盖：b64、url、401、429、未配置，四条都测。

两个刻意的选择：
1. 没配好不抛异常，返回一个 error_kind=auth 的失败结果——上层照常记账，页面会说人话。
2. 尺寸默认按竖版人像给 1024x1536（gpt-image-1 只认 1024x1024 / 1024x1536 / 1536x1024
   这三个），要别的尺寸就在「设置」里没法填，得改 config.json 的 cloud.size。
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


def _file_part(name, path):
    fn = os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()
    ctype = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    head = (f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{fn}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n").encode()
    return head + data + b"\r\n"


def _error_text(raw):
    """从错误响应里挑一句能看懂的话。"""
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return raw[:300]
    err = obj.get("error") if isinstance(obj, dict) else None
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
        self.price = float(c.get("price_per_image") or 0)
        self.out_dir = app_config.outputs_dir(cfg)

    @property
    def configured(self):
        return bool(self.base_url and self.api_key and self.model)

    # ---------- 对外 ----------

    def generate(self, req):
        t0 = time.time()
        if not self.configured:
            return self._fail(t0, req, "auth",
                              "云端后端还没配好：到「设置」里填云端地址、密钥和模型名")

        size = self._size_for(req)
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
            kind = HTTP_KINDS.get(e.code, "node_error")
            return self._fail(t0, req, kind, f"HTTP {e.code}：{_error_text(raw)}")
        except TimeoutError:
            return self._fail(t0, req, "timeout", f"等了 {self.timeout} 秒没返回")
        except urllib.error.URLError as e:
            return self._fail(t0, req, "network", f"连不上：{e.reason}")

        blob, how = self._extract(resp)
        if blob is None:
            return self._fail(t0, req, "node_error",
                              f"响应里没有图：{json.dumps(resp, ensure_ascii=False)[:300]}")

        dst = self._save(blob, req.prefix)
        meta = {"size": size, "via": how}
        if isinstance(resp.get("usage"), dict):
            meta["usage"] = resp["usage"]
        return GenResult(ok=True, image_path=dst, backend=self.name, model=self.model,
                         latency_s=time.time() - t0, cost=round(self.price, 4),
                         seed=req.seed, meta=meta)

    # ---------- 内部 ----------

    def _fail(self, t0, req, kind, message):
        return GenResult(ok=False, backend=self.name, model=self.model,
                         latency_s=time.time() - t0, seed=req.seed,
                         error=message, error_kind=kind)

    def _size_for(self, req):
        if self.size:
            return self.size
        # 竖版人像：gpt-image-1 只认这三个尺寸，挑最接近的
        return "1024x1536" if int(req.resolution or 1024) >= 900 else "1024x1024"

    def _extract(self, resp):
        """返回 (图片字节, 来源)。拿不到返回 (None, "")。"""
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
            try:
                return urllib.request.urlopen(url, timeout=self.timeout).read(), "url"
            except Exception:
                return None, ""
        return None, ""

    def _save(self, blob, prefix):
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            ext = ".png"
        elif blob[:2] == b"\xff\xd8":
            ext = ".jpg"
        else:
            ext = ".png"     # 认不出就按 png 存，PIL 读的时候按内容识别
        os.makedirs(self.out_dir, exist_ok=True)
        name = f"{prefix or 'cloud'}_{uuid.uuid4().hex[:6]}{ext}"
        dst = os.path.join(self.out_dir, name)
        with open(dst, "wb") as f:
            f.write(blob)
        return dst
