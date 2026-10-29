"""生成前的参考图整理。

这一层是这次调试里最重要的发现：**参考图干不干净，比提示词重要得多**。

同一张人像、同一句指令，只把参考图从「整张购物照（含人脸、手机、店铺背景、
水印）」裁成「只有衣服」，结果从"整幅照抄参考图"变成"人物保住、衣服换上"。

裁法保守：去掉上下边缘，保留中间主体。宁可少裁，也不要裁掉衣服。
"""
import os

from PIL import Image

# 左右各留 8%，上下各去掉 16% / 10%
LEFT, RIGHT = 0.08, 0.08
TOP, BOTTOM = 0.16, 0.10
MIN_SIDE = 160      # 裁完太小就放弃，用原图
MAX_KEEP = 0.85     # 裁完还剩这么多面积，说明几乎没裁，没必要


def crop_garment(path, out_dir):
    """返回整理后的路径；不需要/裁不了就原样返回。"""
    try:
        im = Image.open(path)
        w, h = im.size
        box = (int(w * LEFT), int(h * TOP), int(w * (1 - RIGHT)), int(h * (1 - BOTTOM)))
        crop = im.crop(box)
        if crop.width < MIN_SIDE or crop.height < MIN_SIDE:
            return path, None
        # 注意：早期版本这里写的是 0.6，结果一张 750×1000 的参考图裁完剩 0.62，
        # 被自己拦掉了，水印和手机全都留着。门槛要放在"几乎没裁"上，不是"裁得不多"。
        if crop.width * crop.height > MAX_KEEP * w * h:
            return path, None
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(path))[0]
        dst = os.path.join(out_dir, f"prep_{stem}.png")
        if crop.mode not in ("RGB", "RGBA"):
            crop = crop.convert("RGB")
        crop.save(dst)
        return dst, {"from": [w, h], "to": [crop.width, crop.height],
                     "box": list(box),
                     "kept": round(crop.width * crop.height / (w * h), 3)}
    except Exception:
        return path, None
