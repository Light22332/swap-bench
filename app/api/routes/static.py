"""静态资源：页面、前端文件（css/ 与 js/）、图片。

前端用浏览器原生 ES 模块，没有构建步骤，所以这里必须：
  - 允许多一层子目录（/static/js/main.js）
  - 仍然把路径钉死在 web/ 里面，防穿越
页面和前端代码一直在改，所以带 no-cache；图片允许缓存两分钟。

/img 除了原图，还能出缩略图（?w=800&fmt=webp）：结果图是几 MB 的 PNG，
页面上只显示几百像素宽，原图发过去纯属浪费流量。缩略图按 原图+宽度+格式
缓存，带上 ETag，浏览器第二次只看 304。
"""
import mimetypes
import os

from ...core import paths, thumbs

# Windows 注册表里 .js 有时被猜成 text/plain，浏览器会拒绝加载 ES 模块
FIXED_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}

# /img 只发这三个目录里的图片：config.local.json 里存着密钥，不能顺着这个口出去
IMG_DIRS = ("uploads/", "outputs/", "samples/")
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")

PAGE_CACHE = "no-cache"
ORIGINAL_CACHE = "public, max-age=3600"
THUMB_CACHE = "public, max-age=31536000, immutable"


def handle(req):
    p = req.path
    if p in ("/", "/index.html"):
        req.file(os.path.join(paths.WEB, "index.html"), cache=PAGE_CACHE)
        return True
    if p.startswith("/static/"):
        rel = p[len("/static/"):]
        full = paths.inside(os.path.join("web", rel))
        if not full or not os.path.isfile(full):
            req.json({"error": "bad name"}, 400)
            return True
        req.file(full, cache=PAGE_CACHE, ctype=content_type(full))
        return True
    if p == "/img":
        _image(req)
        return True
    return False


def _image(req):
    raw = req.param("path")
    src = paths.inside(raw)
    if not src or not os.path.isfile(src):
        req.json({"error": "not found"}, 404)
        return
    rel = (paths.rel(src) or "").replace("\\", "/")
    ext = os.path.splitext(src)[1].lower()
    if not rel.startswith(IMG_DIRS) or ext not in IMG_EXTS:
        req.json({"error": "not found"}, 404)
        return

    try:
        width = int(req.param("w") or 0)
    except ValueError:
        width = 0
    fmt = req.param("fmt").lower()

    if width or fmt in thumbs.FORMATS:
        data, ctype, key = thumbs.get(src, width, fmt or "webp")
        etag = '"%s"' % key
        if req.if_none_match() == etag:
            req.not_modified(etag, THUMB_CACHE)
            return
        req.bytes(data, ctype, THUMB_CACHE, {"ETag": etag})
        return

    req.file(src, ORIGINAL_CACHE, content_type(src), _stat_etag(src))


def _stat_etag(path):
    st = os.stat(path)
    return '"%s-%s"' % (st.st_mtime_ns, st.st_size)


def content_type(path):
    ext = os.path.splitext(path)[1].lower()
    return FIXED_TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
