"""缩略图的测试：不联网、不需要 GPU、不需要 ComfyUI。

覆盖：WebP/JPEG 转换、按宽度缩放且不放大、宽度上下限、缓存 ETag 稳定、
原图改了 ETag 会变、透明底铺白，以及 /img 路由——缩略图带不可变缓存、
命中 If-None-Match 回 304、只放行 uploads/outputs/samples 里的图片
（config.local.json 里存着密钥，不能被 /img 读走）。

跑法：python tools/tests/test_thumbs.py
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from PIL import Image                                      # noqa: E402
from app.core import thumbs                                 # noqa: E402
from app.api.routes import static as static_route           # noqa: E402

FAILED = []
TMP = os.path.join(ROOT, "outputs", "_test_thumbs")
os.makedirs(TMP, exist_ok=True)
thumbs.CACHE_DIR = os.path.join(TMP, "cache")       # 别把测试产物混进真缓存


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def save_png(path, size, color=(120, 90, 60), mode="RGB", transparent=False):
    if transparent:
        im = Image.new("RGBA", size, (0, 0, 0, 0))      # 全透明
    elif mode == "RGB":
        # 加点噪点，免得纯色图把 PNG 压到比 WebP 还小，"省字节"的断言就测不出来
        noise = Image.effect_noise(size, 60).convert("RGB")
        im = Image.blend(Image.new("RGB", size, color), noise, 0.35)
    else:
        im = Image.new(mode, size, color)
    im.save(path)
    return path


def open_blob(blob):
    im = Image.open(io.BytesIO(blob))
    im.load()
    return im


class FakeReq:
    """只实现 /img 用到的那几个方法。"""

    def __init__(self, params, if_none_match=""):
        self.params = params
        self._inm = if_none_match
        self.out = None
        self.code = None
        self.bytes_args = None
        self.file_args = None
        self.not_modified_args = None

    def param(self, name, default=""):
        return self.params.get(name, default)

    def if_none_match(self):
        return self._inm

    def json(self, obj, code=200):
        self.out, self.code = obj, code

    def bytes(self, data, ctype, cache="", extra=None):
        self.bytes_args = (data, ctype, cache, extra or {})
        self.code = 200

    def file(self, path, cache="", ctype=None, etag=None, extra=None):
        self.file_args = (path, cache, ctype, etag, extra or {})
        self.code = 200

    def not_modified(self, etag, cache=""):
        self.not_modified_args = (etag, cache)
        self.code = 304


print("格式：默认转 WebP，jpg 也支持")
src = save_png(os.path.join(TMP, "src.png"), (1024, 1024))
data, ctype, etag = thumbs.get(src, 800, "webp")
check("默认给 WebP", ctype == "image/webp", ctype)
check("宽度缩到 800、比例不变", open_blob(data).size == (800, 800), str(open_blob(data).size))
check("字节数远小于 PNG", len(data) < os.path.getsize(src) // 10,
      f"{len(data)} vs {os.path.getsize(src)}")
check("ETag 是 16 位十六进制", len(etag) == 16 and all(c in "0123456789abcdef" for c in etag), etag)

jpg, jctype, _ = thumbs.get(src, 400, "jpg")
check("jpg 格式", jctype == "image/jpeg" and open_blob(jpg).format == "JPEG", str(open_blob(jpg).format))
webp2, jctype2, _ = thumbs.get(src, 400, "png")     # 不支持的名字退回 webp
check("不支持的格式退回 WebP", jctype2 == "image/webp", jctype2)

print("宽度：有下限、有上限")
small, _, _ = thumbs.get(src, 10, "webp")
check("宽度下限 64", open_blob(small).size[0] == thumbs.MIN_WIDTH, str(open_blob(small).size))
check("不放大（1024 的图要 2048 宽仍给 1024）",
      open_blob(thumbs.get(src, 2048, "webp")[0]).size[0] == 1024,
      str(open_blob(thumbs.get(src, 2048, "webp")[0]).size))
bigsrc = save_png(os.path.join(TMP, "big.png"), (3000, 100))
check("宽度上限 2048", open_blob(thumbs.get(bigsrc, 9999, "webp")[0]).size[0] == thumbs.MAX_WIDTH,
      str(open_blob(thumbs.get(bigsrc, 9999, "webp")[0]).size))

print("缓存：同图同宽 ETag 稳定，原图改了 ETag 就变")
_, _, again = thumbs.get(src, 800, "webp")
check("同样请求 ETag 不变", again == etag, f"{again} vs {etag}")
_, _, other = thumbs.get(src, 400, "webp")
check("不同宽度 ETag 不同", other != etag)
save_png(src, (1024, 1024), color=(10, 200, 100))
_, _, changed = thumbs.get(src, 800, "webp")
check("原图变了 ETag 会变", changed != etag, f"{changed} vs {etag}")

print("透明底：铺白，和上传归一化一致")
alpha = save_png(os.path.join(TMP, "alpha.png"), (80, 60), mode="RGBA", transparent=True)
im = open_blob(thumbs.get(alpha, 64, "webp")[0])
check("透明图输出 RGB", im.mode == "RGB", im.mode)
check("透明区域是白的", min(im.getpixel((2, 2))[:3]) >= 240, str(im.getpixel((2, 2))))

print("/img 路由：缩略图 + 缓存 + 304")
req = FakeReq({"path": "outputs/_test_thumbs/src.png", "w": "400", "fmt": "webp"})
static_route._image(req)
check("缩略图走 bytes", req.bytes_args is not None, str(req.code))
if req.bytes_args:
    payload, ctype, cache, extra = req.bytes_args
    check("Content-Type 是 WebP", ctype == "image/webp", ctype)
    check("缩略图缓存一年且不可变", cache.startswith("public, max-age=31536000") and "immutable" in cache, cache)
    check("带 ETag 响应头", "ETag" in extra, str(extra))
else:
    extra = {}

same = FakeReq({"path": "outputs/_test_thumbs/src.png", "w": "400", "fmt": "webp"},
               if_none_match=extra.get("ETag", ""))
static_route._image(same)
check("If-None-Match 命中回 304", same.code == 304 and same.not_modified_args is not None, str(same.code))

plain = FakeReq({"path": "outputs/_test_thumbs/src.png"})
static_route._image(plain)
check("不带参数发原图", plain.file_args is not None and plain.code == 200, str(plain.code))
if plain.file_args:
    check("原图缓存 1 小时", plain.file_args[1].startswith("public, max-age=3600"), plain.file_args[1])

print("/img 路由：不发出项目里的非图片文件")
for bad in ({"path": "app/core/config.py"}, {"path": "config.json"},
            {"path": "../secret.jpg"}, {"path": "outputs/.thumbs"}):
    r = FakeReq(bad)
    static_route._image(r)
    check(f"挡住 {bad['path']}", r.code == 404 and r.bytes_args is None and r.file_args is None, str(r.code))

txt = os.path.join(TMP, "note.txt")
with open(txt, "w", encoding="utf-8") as f:
    f.write("not an image")
r = FakeReq({"path": "outputs/_test_thumbs/note.txt", "w": "400"})
static_route._image(r)
check("挡住非图片扩展名", r.code == 404, str(r.code))

r = FakeReq({"path": "samples/demo_person_a.jpg", "w": "abc"})   # 宽度写错按 0 = 原图
static_route._image(r)
check("宽度写错不报 500，按原图发", r.code == 200 and r.file_args is not None, str(r.code))

print()
if FAILED:
    print(f"FAILED {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("全部通过")
