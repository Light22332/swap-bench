"""静态资源：页面、前端文件（css/ 与 js/）、图片。

前端用浏览器原生 ES 模块，没有构建步骤，所以这里必须：
  - 允许多一层子目录（/static/js/main.js）
  - 仍然把路径钉死在 web/ 里面，防穿越
页面和前端代码一直在改，所以带 no-cache；图片允许缓存两分钟。
"""
import mimetypes
import os

from ...core import paths

# Windows 注册表里 .js 有时被猜成 text/plain，浏览器会拒绝加载 ES 模块
FIXED_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


def handle(req):
    p = req.path
    if p in ("/", "/index.html"):
        req.file(os.path.join(paths.WEB, "index.html"), cache="no-cache")
        return True
    if p.startswith("/static/"):
        rel = p[len("/static/"):]
        full = paths.inside(os.path.join("web", rel))
        if not full or not os.path.isfile(full):
            req.json({"error": "bad name"}, 400)
            return True
        req.file(full, cache="no-cache", ctype=content_type(full))
        return True
    if p == "/img":
        img = paths.inside(req.param("path"))
        req.file(img, ctype=content_type(img) if img else None)
        return True
    return False


def content_type(path):
    ext = os.path.splitext(path)[1].lower()
    return FIXED_TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
