"""读图：按方向转正，上传的图先归一化再落盘。

手机拍的照片常带 EXIF 方向：浏览器按方向显示，PIL 不认，于是"预览是正的、
生成和判定拿到的是躺倒的"。所以所有读图都走 open_upright()，上传时再在
prepare_upload() 里做一次归一化（转正、透明底铺白、去 EXIF、统一 JPEG），
下游各模块就不用各自处理。

HEIC 是另一回事：Pillow 默认不解码。装了 pillow-heif 就能打开；没装就给一句
人话，而不是让任务跑到 ComfyUI 里报一串节点错误。
"""
import io
import os

from PIL import Image, ImageOps

# ISO/IEC 23008-12 的 ftyp major brand；AVIF 也是同一个容器，一起认
HEIF_BRANDS = frozenset({
    b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"hevm", b"hevs",
    b"mif1", b"msf1", b"avif", b"avis",
})
HEIF_EXTS = frozenset({".heic", ".heif", ".avif"})

MAX_SIDE = 4096        # 超过这个长边就缩一下：再大对生成和判定都没用，只吃内存
JPEG_QUALITY = 95


class PhotoError(Exception):
    """这张照片读不了。message 直接给用户看，所以要说人话、说怎么办。"""


_heif_state = {"tried": False, "ok": False}


def _register_heif():
    """装了 pillow-heif 就把 HEIC/AVIF 挂进 PIL；没装就记下来，不反复试。"""
    if _heif_state["tried"]:
        return _heif_state["ok"]
    _heif_state["tried"] = True
    try:
        from pillow_heif import register_heif_opener  # 可选依赖，没有也能跑
        register_heif_opener()
        _heif_state["ok"] = True
    except Exception:
        _heif_state["ok"] = False
    return _heif_state["ok"]


def _brand(blob):
    """HEIF/AVIF 的 major brand（ftyp 盒子的第 8–12 字节），不是就返回 b""。"""
    if len(blob) >= 12 and blob[4:8] == b"ftyp":
        return blob[8:12]
    return b""


def is_heif(blob):
    return _brand(blob) in HEIF_BRANDS


def open_upright(src):
    """打开图片并按 EXIF 方向转正。读不了就按 PIL 原来的方式抛异常。"""
    _register_heif()
    im = Image.open(src)
    try:
        return ImageOps.exif_transpose(im)
    except Exception:
        # EXIF 坏了不耽误用原图；方向错总比整张图打不开强
        return im


def _unreadable_message(heif, name):
    if heif and not _heif_state["ok"]:
        return ("这是 iPhone 的 HEIC 照片，当前环境打不开。"
                "先在相册里导出成 JPG（或用看图软件另存为 JPG）再放进来。")
    if heif:
        return "这张 HEIC 读不出来，可能文件坏了。换一张，或先导出成 JPG。"
    ext = os.path.splitext(name or "")[1].lower()
    if ext in HEIF_EXTS and not _heif_state["ok"]:
        return ("这是 HEIC 照片，当前环境打不开。"
                "先在相册里导出成 JPG（或用看图软件另存为 JPG）再放进来。")
    return "这张图打不开，可能坏了，或者不是常见格式（JPG、PNG、WebP 都行）。"


def flatten(im):
    """把各种模式统一成白底 RGB。透明区铺白，不铺黑。"""
    if im.mode == "RGB":
        return im
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        return Image.alpha_composite(bg, im).convert("RGB")
    return im.convert("RGB")


def prepare_upload(blob, name="upload"):
    """把上传的字节归一化成 JPEG，返回 (jpeg 字节, 摘要)。

    摘要里的 note 是给用户看的一句话（转正了、转格式了、太大缩了），没有就空串。
    """
    if not blob:
        raise PhotoError("这个文件是空的")

    heif = is_heif(blob) or os.path.splitext(name or "")[1].lower() in HEIF_EXTS
    if heif:
        _register_heif()

    try:
        raw = Image.open(io.BytesIO(blob))
        raw.load()
    except PhotoError:
        raise
    except Exception:
        raise PhotoError(_unreadable_message(heif, name))

    src_format = raw.format or "?"
    base_size = raw.size
    try:
        orientation = int(raw.getexif().get(274, 1) or 1)
    except Exception:
        orientation = 1
    try:
        im = ImageOps.exif_transpose(raw)
    except Exception:
        im = raw
    # 正方形照片转 90° 后宽高不变，光比尺寸会漏报；再看一眼方向标记
    rotated = im.size != base_size or orientation not in (0, 1)

    notes = []
    if rotated:
        notes.append("照片已转正")
    if src_format in ("HEIF", "AVIF"):
        notes.append("HEIC/AVIF 已转成 JPG")

    out = flatten(im)
    if out.mode != "RGB":
        out = out.convert("RGB")

    resized = False
    long_side = max(out.size)
    if long_side > MAX_SIDE:
        s = MAX_SIDE / float(long_side)
        out = out.resize((max(1, round(out.width * s)), max(1, round(out.height * s))),
                         Image.LANCZOS)
        resized = True
        notes.append(f"照片太大，已缩到 {MAX_SIDE} 长边")

    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    meta = {
        "format": src_format,
        "width": out.width,
        "height": out.height,
        "rotated": rotated,
        "resized": resized,
        "note": "；".join(notes),
    }
    return buf.getvalue(), meta
