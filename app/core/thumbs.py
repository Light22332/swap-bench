"""缩略图：把几 MB 的结果图压成几十 KB，页面上的格子、小图、看大图都走这里。

原图不动，保存和下载依旧是 PNG；这里只负责"显示用"的那一份。

缓存键是「相对路径 + mtime + 大小 + 宽度 + 格式」——同一张图反复请求只压一次。
缓存在 outputs/.thumbs/ 下，和结果图一样是生成物，不进仓库。
"""
import hashlib
import os

from PIL import Image

from . import paths

CACHE_DIR = os.path.join(paths.OUTPUTS, ".thumbs")

# 只支持浏览器都能解的两种；想加 png 时记住它不省多少字节。
FORMATS = {
    "webp": ("image/webp", "WEBP"),
    "jpg": ("image/jpeg", "JPEG"),
    "jpeg": ("image/jpeg", "JPEG"),
}

MIN_WIDTH = 64
MAX_WIDTH = 2048
QUALITY = 82


def content_type(fmt):
    return FORMATS.get((fmt or "").lower(), (None, None))[0]


def get(src, width=0, fmt="webp"):
    """返回 (bytes, content_type, etag)。width 为 0 表示不缩放，只转格式。"""
    fmt = (fmt or "").lower()
    if fmt not in FORMATS:
        fmt = "webp"
    w = int(width or 0)
    if w:
        w = max(MIN_WIDTH, min(MAX_WIDTH, w))
    key = _key(src, w, fmt)
    dst = os.path.join(CACHE_DIR, key + "." + ("jpg" if fmt == "jpeg" else fmt))
    if not os.path.isfile(dst):
        _render(src, dst, w, fmt)
    with open(dst, "rb") as f:
        return f.read(), FORMATS[fmt][0], key


def _key(src, width, fmt):
    st = os.stat(src)
    raw = "{0}|{1}|{2}|{3}|{4}".format(paths.rel(src) or src, st.st_mtime_ns, st.st_size,
                                       width, fmt)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _render(src, dst, width, fmt):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with Image.open(src) as im:
        im = _rgb(im)
        if width and width < im.width:
            height = max(1, round(im.height * width / im.width))
            im = im.resize((width, height), Image.LANCZOS)
        tmp = "{0}.{1}.tmp".format(dst, os.getpid())
        im.save(tmp, FORMATS[fmt][1], quality=QUALITY, method=4)
        os.replace(tmp, dst)


def _rgb(im):
    """透明底铺白，和上传归一化保持一致；其余模式统一转 RGB。"""
    if im.mode == "RGB":
        return im
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        base = im.convert("RGBA")
        bg = Image.new("RGB", base.size, (255, 255, 255))
        bg.paste(base, mask=base.split()[-1])
        return bg
    return im.convert("RGB")
