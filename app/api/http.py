"""HTTP 层的最小包装。

路由函数拿到 Request 就能读完请求、写完响应，不用碰 BaseHTTPRequestHandler
的细节；Handler 只负责把请求交给路由，路由返回 False 表示"这条不归我管"。
"""
import urllib.parse


class Request:
    def __init__(self, handler):
        self.handler = handler
        u = urllib.parse.urlparse(handler.path)
        self.path = u.path
        self.query = urllib.parse.parse_qs(u.query)
        self.method = handler.command

    def param(self, name, default=""):
        return (self.query.get(name) or [default])[0]

    def body(self):
        """请求体解析成 dict；空体或坏 JSON 一律返回 {}（和以前一致）。"""
        return self.handler._body()

    def json(self, obj, code=200):
        self.handler._json(obj, code)

    def file(self, path, cache="max-age=120", ctype=None):
        self.handler._file(path, cache, ctype)

    def bytes(self, data, ctype, cache="max-age=120", extra=None):
        self.handler._bytes(data, ctype, cache, extra)
