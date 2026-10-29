"""生成前的参考图整理。

这一层是这次调试里最重要的发现：**参考图干不干净，比提示词重要得多**。

同一张人像、同一句指令，只把参考图从「整张购物照（含人脸、手机、店铺背景、
水印）」裁成「只有衣服」，结果从"整幅照抄参考图"变成"人物保住、衣服换上"。

裁法不再靠猜比例，而是先跑人像解析（见 parse_clothes.py）拿到"衣服到底在哪块"，
再决定走哪条路：

1. 解析出了衣服，而且**固定比例框只切掉一点点衣服**（≤5%）→ 用固定比例框。
   这类是标准商品图：人物居中、四周留白、底部有一条店铺名水印带。
   盲切在这里恰好把水印带切掉，换成衣服外框反而会把水印带回来（实测 case4：
   固定框只切到 2.3% 的衣服）。
2. 解析出了衣服，但固定框会切掉大块衣服（实测 21%~31%）→ 用衣服外框。
   平铺图、贴边特写都属于这类：衣服本来就顶到画面边上，按比例切就是在切衣服。
   外框几乎等于整张图时干脆不裁。
3. 解析不出（没有模型、或者模型没认出衣服）→ 老办法兜底：
   图里有人脸就按固定比例切（人像照必须切掉头），没人脸就不裁。

宁可少裁，也不要裁掉衣服。
"""
import os

from PIL import Image

from . import parse_clothes

# 第 1 档（固定比例）的参数：左右各去 8%，上去 16%，下去 10%
LEFT, RIGHT = 0.08, 0.08
TOP, BOTTOM = 0.16, 0.10

MIN_SIDE = 160      # 裁完太小就放弃，用原图
MAX_KEEP = 0.85     # 裁完还剩这么多面积，说明几乎没裁，没必要
MIN_SHARE = 0.06    # 解析出的衣服至少占画面这么多，才认它是"主体"
CUT_OK = 0.05       # 固定框切掉的衣服像素占比不超过这个数，说明盲切没有伤到衣服
MARGIN = 0.02       # 用衣服外框时四周留一点，别贴着边切


def _fixed_box(size):
    w, h = size
    return (int(w * LEFT), int(h * TOP), int(w * (1 - RIGHT)), int(h * (1 - BOTTOM)))


def _pad_box(box, size, margin=MARGIN):
    w, h = size
    bw, bh = box[2] - box[0], box[3] - box[1]
    px, py = int(bw * margin), int(bh * margin)
    return (max(0, box[0] - px), max(0, box[1] - py),
            min(w, box[2] + px), min(h, box[3] + py))


# 曾经试过"用头部掩码把上边界压到下巴以下"，删掉了：长发会垂到胸口，
# 头部掩码的下边界能到画面中部，照着压会把大衣上半截切掉（case1 实测裁到只剩 34%）。


def _worth_cropping(box, size):
    w, h = size
    bw, bh = box[2] - box[0], box[3] - box[1]
    if bw < MIN_SIDE or bh < MIN_SIDE:
        return False, "裁完太小，不值得"
    # 注意：早期版本这里写的是 0.6，结果一张 750×1000 的参考图裁完剩 0.62，
    # 被自己拦掉了，水印和手机全都留着。门槛要放在"几乎没裁"上，不是"裁得不多"。
    kept = bw * bh / float(w * h)
    if kept > MAX_KEEP:
        return False, f"裁完还剩 {kept:.0%}，衣服铺满画面，裁了只会切到衣服"
    return True, ""


def _person_present(path, models_dir):
    """有没有人脸。判不了返回 None（按"有"处理，沿用老办法，保守）。"""
    if not models_dir:
        return None
    try:
        from .judge import faces
    except Exception:
        return None
    if not faces.load(models_dir):
        return None
    r = faces.analyze(path)
    if r is None:
        return None
    return (r.get("count") or 0) > 0


def crop_garment(path, out_dir, mode="parse", models_dir=None, device="cpu"):
    """返回 (裁剪后的路径, 记录)。没裁就返回原路径，记录里写明为什么没裁。

    记录字段：how（parse / fixed / none）、box、kept、from、to；
    解析跑起来时带 share、cut（固定框会切掉的衣服占比）、parse_ms。
    """
    try:
        im = Image.open(path)
    except Exception as e:
        return path, {"how": "none", "reason": f"打不开：{e}"}
    w, h = im.size
    meta = {"how": "none", "from": [w, h]}
    fixed = _fixed_box((w, h))

    if mode == "parse" and models_dir:
        res = parse_clothes.analyze(path, models_dir, device, want_mask=True)
        if res:
            for k in ("share", "parse_ms", "labels"):
                if k in res:
                    meta[k] = res[k]
            mask = res.get("mask")
            if res["box"] and res["share"] >= MIN_SHARE and mask is not None:
                total = float(mask.sum())
                outside = mask.copy()
                outside[fixed[1]:fixed[3], fixed[0]:fixed[2]] = False
                cut = float(outside.sum()) / max(1.0, total)
                meta["cut"] = round(cut, 3)
                if cut <= CUT_OK:
                    # 标准商品图：按比例切就行，它顺手切掉的正是底部的水印带
                    meta["how"] = "fixed"
                    ok, why_not = _worth_cropping(fixed, (w, h))
                    if ok:
                        return _save(im, fixed, out_dir, path, meta)
                    meta["reason"] = why_not
                    return path, meta
                # 盲切会切到衣服：改用衣服外框
                box = _pad_box(res["box"], (w, h))
                meta["how"] = "parse"
                ok, why_not = _worth_cropping(box, (w, h))
                if ok:
                    return _save(im, box, out_dir, path, meta)
                meta["reason"] = why_not
                meta["box"] = list(box)
                return path, meta

    # ---- 解析不出：按有没有人脸兜底 ----
    person = _person_present(path, models_dir)
    if person is False:
        meta["how"] = "none"
        meta["reason"] = "没认出衣服，也没有人脸——多半是平铺图，不裁"
        return path, meta

    meta["how"] = "fixed"
    meta["person"] = person          # True 或 None（判不了）
    ok, why_not = _worth_cropping(fixed, (w, h))
    if ok:
        return _save(im, fixed, out_dir, path, meta)
    meta["reason"] = why_not
    return path, meta


def _save(im, box, out_dir, path, meta):
    crop = im.crop(box)
    if crop.width < MIN_SIDE or crop.height < MIN_SIDE:
        meta["reason"] = "裁完太小"
        meta["box"] = list(box)
        return path, meta
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    dst = os.path.join(out_dir, f"prep_{stem}.png")
    if crop.mode not in ("RGB", "RGBA"):
        crop = crop.convert("RGB")
    crop.save(dst)
    w, h = im.size
    meta.update({
        "box": list(box),
        "to": [crop.width, crop.height],
        "kept": round(crop.width * crop.height / float(w * h), 3),
    })
    return dst, meta
