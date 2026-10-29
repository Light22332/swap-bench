"""云端后端的客户端逻辑测试：起一个本地假服务器，不联网、不需要真 key。

覆盖四条主路径：b64_json 响应、url 响应、401、429，外加"没配好"和尺寸换算。
跑法：python tools/tests/test_cloud.py
"""
import base64
import json
import os
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.capability.generate.base import GenRequest          # noqa: E402
from app.capability.generate.cloud import CloudBackend      # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a") + b"fake-png-body"
TINY = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

MODE = {"mode": "b64", "body": b""}
FAILED = []
OUT = os.path.join(ROOT, "outputs", "_test_cloud")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, code, obj):
        blob = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        MODE["body"] = self.rfile.read(n)
        port = self.server.server_address[1]
        mode = MODE["mode"]
        if mode == "b64":
            self._json(200, {"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
        elif mode == "data_url":
            inner = "data:image/png;base64," + base64.b64encode(PNG).decode()
            self._json(200, {"data": [{"url": inner}]})
        elif mode == "url":
            self._json(200, {"data": [{"url": f"http://127.0.0.1:{port}/img.png"}]})
        elif mode == "401":
            self._json(401, {"error": {"message": "invalid api key"}})
        elif mode == "429":
            self._json(429, {"error": {"message": "rate limited, retry later"}})
        else:
            self._json(500, {"error": "boom"})

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(PNG)))
        self.end_headers()
        self.wfile.write(PNG)


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def make_cfg(port, **cloud):
    base = {"base_url": f"http://127.0.0.1:{port}", "api_key": "test-key",
            "model": "test-model", "size": "1024x1536", "price_per_image": 0.04}
    base.update(cloud)
    return {"cloud": base, "paths": {"outputs": OUT}}


def make_req(resolution=1024, prefix="t"):
    return GenRequest(person_path=os.path.join(OUT, "p.png"),
                      garment_path=os.path.join(OUT, "g.png"),
                      instruction="换个衣服", resolution=resolution, prefix=prefix)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "p.png"), "wb") as f:
        f.write(TINY)
    with open(os.path.join(OUT, "g.png"), "wb") as f:
        f.write(TINY)

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    print("没配好的时候不炸")
    bare = CloudBackend({"cloud": {}, "paths": {"outputs": OUT}}).generate(make_req())
    check("返回失败结果而不是抛异常", bare.ok is False)
    check("算 auth 类错误", bare.error_kind == "auth", str(bare.error))
    check("提示里写明去哪配", "设置" in (bare.error or ""), str(bare.error))

    print("b64_json 响应")
    MODE["mode"] = "b64"
    be = CloudBackend(make_cfg(port))
    res = be.generate(make_req(prefix="b64case"))
    check("成功", res.ok, str(res.error))
    check("落盘是 png", bool(res.image_path) and res.image_path.endswith(".png"), str(res.image_path))
    check("文件内容就是返回的字节", os.path.getsize(res.image_path) == len(PNG))
    check("记了来源", res.meta.get("via") == "b64_json", str(res.meta))
    check("按单价算了成本", abs(res.cost - 0.04) < 1e-9, str(res.cost))
    body = MODE["body"]
    check("请求里要了 b64_json", b'name="response_format"' in body and b"b64_json" in body)
    check("带了两张图", body.count(b'name="image[]"') == 2, str(body.count(b'name="image[]"')))
    check("带了 size", b'name="size"' in body)

    print("内联 data: URL")
    MODE["mode"] = "data_url"
    res = CloudBackend(make_cfg(port)).generate(make_req(prefix="datacase"))
    check("从 data URL 解出来", res.ok and os.path.getsize(res.image_path) == len(PNG), str(res.error))
    check("记成 data_url", res.meta.get("via") == "data_url", str(res.meta))

    print("外链 url 响应")
    MODE["mode"] = "url"
    res = CloudBackend(make_cfg(port)).generate(make_req(prefix="urlcase"))
    check("跟着链接下载", res.ok and os.path.getsize(res.image_path) == len(PNG), str(res.error))
    check("记成 url", res.meta.get("via") == "url", str(res.meta))

    print("错误分类")
    MODE["mode"] = "401"
    res = CloudBackend(make_cfg(port)).generate(make_req())
    check("401 -> auth", res.ok is False and res.error_kind == "auth", str(res.error_kind))
    check("把对方的话带出来", "invalid api key" in (res.error or ""), str(res.error))

    MODE["mode"] = "429"
    res = CloudBackend(make_cfg(port)).generate(make_req())
    check("429 -> rate_limit", res.ok is False and res.error_kind == "rate_limit", str(res.error_kind))

    print("尺寸")
    MODE["mode"] = "b64"
    body = (CloudBackend(make_cfg(port)).generate(make_req(resolution=1024)) or None, MODE["body"])[1]
    check("指定了 size 就照抄", b"1024x1536" in body)
    body = (CloudBackend(make_cfg(port, size="")).generate(make_req(resolution=1024)), MODE["body"])[1]
    check("没指定给竖版 1024x1536", b"1024x1536" in body)
    body = (CloudBackend(make_cfg(port, size="")).generate(make_req(resolution=640)), MODE["body"])[1]
    check("小尺寸给方形", b"1024x1024" in body)

    print("接口形状：地址决定走哪条")
    be = CloudBackend(make_cfg(port))
    check("普通地址走 openai", be.resolve_shape() == "openai", be.resolve_shape())
    be = CloudBackend({"cloud": {"base_url": "https://dashscope.aliyuncs.com/api/v1",
                                 "api_key": "k", "model": "m"}, "paths": {"outputs": OUT}})
    check("aliyuncs 地址自动走 dashscope", be.resolve_shape() == "dashscope", be.resolve_shape())
    check("compatible-mode 也归一成 host/api/v1",
          be.native_root() == "https://dashscope.aliyuncs.com/api/v1", be.native_root())
    be = CloudBackend({"cloud": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                                 "api_key": "k", "model": "m"}, "paths": {"outputs": OUT}})
    check("从 compatible-mode 剥掉", be.native_root() == "https://dashscope.aliyuncs.com/api/v1",
          be.native_root())
    be = CloudBackend(make_cfg(port, shape="dashscope"))
    check("显式指定优先", be.resolve_shape() == "dashscope", be.resolve_shape())

    srv.shutdown()
    print()
    if FAILED:
        print(f"{len(FAILED)} 项没过：" + "、".join(FAILED))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
