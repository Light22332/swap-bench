"""把人物照片里的衣服抠出来，贴到白底上。

复用 `parse_clothes` 已经跑着的那个 SegFormer（18 类人像解析）：取上衣 / 裙子 / 裤子 /
连衣裙的掩码，掩码以外涂白，再按衣服外框裁掉四周的白边。产物既能当"衣服图"喂回换装，
也能直接存下来当一张白底图。

为什么先这么做而不是上专门的抠图模型：这个模型已经在跑，零新依赖，几分钟就能看到效果。
不满意再换 rembg 的 `u2net_cloth_seg`（MIT），只要 `extract()` 的输入输出不变，上层不用动。

边缘说实话不完美：毛领、条纹、被手或头发挡住的地方会缺块；人穿外套加内搭时，
语义分割只给一个类别，抠出来的可能是最外层那件。
"""
import os
import time

import numpy as np
from PIL import Image, ImageFilter

from ...core import photos
from . import parse_clothes

MIN_SHARE = 0.05        # 衣服像素少于这个占比就当作"没认出衣服"
EDGE_FEATHER = 1.0      # 边缘柔化，别像剪贴画；再大就会糊出一圈底色


def extract(photo_path, out_dir, models_dir, device="cpu"):
    """抠出衣服。成功返回 (白底图路径, 摘要)，失败返回 (None, {"error": ...})。"""
    t0 = time.time()
    info = parse_clothes.analyze(photo_path, models_dir, device=device, want_mask=True)
    if info is None:
        return None, {"error": parse_clothes.why() or "人像解析没跑起来"}

    mask = info.get("mask")
    share = float(info.get("share") or 0)
    if mask is None or share < MIN_SHARE:
        return None, {
            "error": f"没认出衣服：衣服像素只占 {share * 100:.0f}%，换一张能看清衣服的照片试试",
            "share": round(share, 3),
            "labels": info.get("labels") or {},
        }

    im = photos.open_upright(photo_path).convert("RGB")
    if (im.width, im.height) != (mask.shape[1], mask.shape[0]):
        im = im.resize((mask.shape[1], mask.shape[0]), Image.LANCZOS)

    alpha = Image.fromarray(mask.astype(np.uint8) * 255, "L")
    # 先把掩码收 1px：不然模糊会把原图的背景色带进边缘，成了一圈灰边
    alpha = alpha.filter(ImageFilter.MinFilter(3))
    if EDGE_FEATHER:
        alpha = alpha.filter(ImageFilter.GaussianBlur(EDGE_FEATHER))

    canvas = Image.new("RGB", im.size, (255, 255, 255))
    canvas.paste(im, (0, 0), alpha)

    box = info.get("box")
    if box:
        pad = 14
        box = (max(0, box[0] - pad), max(0, box[1] - pad),
               min(im.width, box[2] + pad), min(im.height, box[3] + pad))
        canvas = canvas.crop(box)

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(photo_path))[0]
    dst = os.path.join(out_dir, f"{stem}_cloth_{int(time.time())}.png")
    canvas.save(dst, format="PNG")

    return dst, {
        "share": round(share, 3),
        "labels": info.get("labels") or {},
        "size": list(canvas.size),
        "ms": int((time.time() - t0) * 1000),
    }
