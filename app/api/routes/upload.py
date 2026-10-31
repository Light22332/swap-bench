"""上传接口：页面把图片转成 base64 发上来，归一化后落到 uploads/。

落盘之前先过 app/core/photos.py：按 EXIF 方向转正、透明底铺白、去元数据、
统一成 JPEG。这样下游（ComfyUI、人像解析、判定）拿到的都是同一张"正"图，
不会出现"页面预览是正的、处理出来是躺倒的"。

文件名加时间戳前缀，避免同名覆盖；非 ASCII 字符替换成下划线，免得在
ComfyUI 那侧踩中文路径的坑。
"""
import base64
import os
import re
import shutil
import time
import urllib.parse

from ...capability.prep.extract_garment import extract
from ...core import config as app_config
from ...core import paths, photos
from .. import state

MAX_BYTES = 30 * 1024 * 1024
SAFE = re.compile(r"[^A-Za-z0-9_.\-]")

SAMPLES = {
    "person": "demo_person_a.jpg",
    "garments": ["demo_garment_1.jpg", "demo_garment_2.jpg"],
}


def _url(rel):
    return "/img?path=" + urllib.parse.quote(rel.replace("\\", "/"))


def handle_post(req):
    if req.path == "/api/upload":
        return _upload(req)
    if req.path == "/api/samples":
        return _samples(req)
    if req.path == "/api/extract":
        return _extract(req)
    return False


def _extract(req):
    """从一张人物照片里把衣服抠出来，产物落在 outputs/extract/。"""
    data = req.body() or {}
    src = paths.inside(data.get("path") or "")
    if not src or not os.path.isfile(src):
        req.json({"error": "找不到要提取的那张照片"}, 400)
        return True

    cfg = state.get_config()
    out_dir = os.path.join(app_config.outputs_dir(cfg), "extract")
    dst, meta = extract(src, out_dir, app_config.models_dir(cfg))
    if not dst:
        req.json({"error": meta.get("error", "没提取出来"), **meta}, 422)
        return True

    rel = paths.rel(dst)
    req.json({"ok": True, "path": rel, "url": _url(rel),
              "name": os.path.splitext(os.path.basename(src))[0] + " 提取的衣服",
              **meta})
    return True


def _upload(req):
    data = req.body()
    name = data.get("name") or "upload.jpg"
    raw = data.get("data") or ""
    if raw.strip().startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        blob = base64.b64decode(raw)
    except Exception:
        req.json({"error": "base64 解码失败"}, 400)
        return True
    if not blob:
        req.json({"error": "这个文件是空的"}, 400)
        return True
    if len(blob) > MAX_BYTES:
        req.json({"error": "文件太大（上限 30MB）"}, 413)
        return True

    try:
        jpeg, meta = photos.prepare_upload(blob, name)
    except photos.PhotoError as e:
        req.json({"error": str(e)}, 415)
        return True

    os.makedirs(paths.UPLOADS, exist_ok=True)
    stem = os.path.splitext(os.path.basename(name))[0] or "upload"
    safe = SAFE.sub("_", stem)
    fn = f"{time.strftime('%m%d%H%M%S')}_{safe}.jpg"
    with open(os.path.join(paths.UPLOADS, fn), "wb") as f:
        f.write(jpeg)
    rel = os.path.join("uploads", fn)
    req.json({"ok": True, "file": fn, "path": rel, "url": _url(rel),
              "size": len(jpeg), "note": meta["note"],
              "rotated": meta["rotated"], "from_format": meta["format"]})
    return True


def _samples(req):
    """把示例图复制进 uploads，让页面一键就能跑一次。"""
    os.makedirs(paths.UPLOADS, exist_ok=True)

    def copy_in(fn):
        src = os.path.join(paths.SAMPLES, fn)
        if not os.path.isfile(src):
            return None
        dst_name = "sample_" + fn
        shutil.copy2(src, os.path.join(paths.UPLOADS, dst_name))
        rel = os.path.join("uploads", dst_name)
        return {"file": dst_name, "path": rel, "url": _url(rel), "name": fn}

    person = copy_in(SAMPLES["person"])
    garments = [g for g in (copy_in(f) for f in SAMPLES["garments"]) if g]
    if not person or not garments:
        req.json({"error": "samples 目录里缺少示例图"}, 404)
        return True
    req.json({"ok": True, "person": person, "garments": garments})
    return True
