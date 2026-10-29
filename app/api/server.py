"""HTTP 服务：只有骨架。

这个文件管三件事：起服务、把请求交给路由、把字节写回连接。业务分别在 routes/ 下。
零依赖是刻意的——不用 FastAPI，装一个 Web 框架换几十行代码不划算。
"""
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..core import config as app_config
from . import state
from .http import Request
from .routes import config as config_route
from .routes import jobs as jobs_route
from .routes import run as run_route
from .routes import static as static_route
from .routes import upload as upload_route

GET_ROUTES = (static_route.handle, config_route.handle_get, jobs_route.handle_get)
POST_ROUTES = (upload_route.handle_post, run_route.handle_post, config_route.handle_post)


class Handler(BaseHTTPRequestHandler):
    server_version = "SwapBench/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("SWAP_VERBOSE"):
            super().log_message(fmt, *args)

    # ---------- 写响应 ----------

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
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # ---------- 分发 ----------

    def _dispatch(self, routes):
        req = Request(self)
        for route in routes:
            if route(req):
                return
        req.json({"error": "not found"}, 404)

    def do_GET(self):
        self._dispatch(GET_ROUTES)

    def do_POST(self):
        self._dispatch(POST_ROUTES)


def serve():
    cfg = state.load_config()
    host, port = app_config.server_addr(cfg)
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"换装工作台 → http://{host}:{port}")
    print(f"后端 {app_config.backend(cfg)} | 质检 {app_config.section(cfg, 'judge')['mode']}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
        sys.exit(0)
