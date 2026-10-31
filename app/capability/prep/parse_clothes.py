"""人像解析：找出"身上那件衣服"在画面的哪一块。

用的是现成开源模型，不自己写规则：
  mattmdjaga/segformer_b2_clothes
  https://huggingface.co/mattmdjaga/segformer_b2_clothes
  SegFormer-B2 在 ATR 人像解析集上微调，输出 18 类：上衣 / 裙子 / 裤子 / 连衣裙 /
  脸 / 头发 / 左右手臂 / 包 …… 取 4/5/6/7 就是身上的衣服。
  基座是 NVlabs/SegFormer，权重沿用它的 NVIDIA Source Code License（非商业用途）；
  要商用可以换 rembg 的 u2net_cloth_seg（MIT），接口一样。
  开源虚拟试衣项目 OOTDiffusion 的预处理也是这个模型。

为什么不用颜色/边缘规则：毛领、浅色衣服压在浅色背景上、白色水印文字，这三样
都会让色块边界判断失准；人像解析直接给语义掩码，不用猜。

跑在 ComfyUI 自带 python 上，torch 和 transformers 都是现成的，不用另装。
模型文件放 models/segformer_b2_clothes/（三个文件，见 models/README.md）。
"""
import os
import time

from PIL import Image

from ...core import photos

_state = {"proc": None, "model": None, "device": None, "dir": None,
          "tried": False, "ok": False, "why": ""}

# 解析只看这么大。模型输入本来就是 512，掩码到这个精度足够定衣服框；
# 再往上只是把 128×128 的 logits 双线性放大，白占内存——4096 的图上峰值会多 1.3GB。
# 要整张掩码时用最近邻放回原图尺寸，下游（按原图裁）不用改。
ANALYZE_MAX_SIDE = 1024

GARMENT = (4, 5, 6, 7)          # 上衣 / 裙子 / 裤子 / 连衣裙
HEAD = (1, 2, 11)               # 帽子 / 头发 / 脸
NAMES = {0: "背景", 1: "帽子", 2: "头发", 3: "墨镜", 4: "上衣", 5: "裙子", 6: "裤子",
         7: "连衣裙", 8: "腰带", 9: "左鞋", 10: "右鞋", 11: "脸", 12: "左腿",
         13: "右腿", 14: "左臂", 15: "右臂", 16: "包", 17: "围巾"}

MODEL_FILES = ("config.json", "preprocessor_config.json", "model.safetensors")


def model_dir(models_dir):
    return os.path.join(models_dir, "segformer_b2_clothes")


def installed(models_dir):
    d = model_dir(models_dir)
    return all(os.path.isfile(os.path.join(d, f)) for f in MODEL_FILES)


def load(models_dir, device="cpu"):
    """懒加载。缺文件或加载失败返回 False，调用方退回固定裁剪。"""
    d = model_dir(models_dir)
    if _state["tried"] and _state["dir"] == d and _state["device"] == device:
        return _state["ok"]
    _state.update(tried=True, dir=d, device=device)
    if not installed(models_dir):
        _state["why"] = "缺少模型：" + os.path.join("segformer_b2_clothes", "model.safetensors")
        _state["ok"] = False
        return False
    try:
        from transformers import SegformerImageProcessor, AutoModelForSemanticSegmentation
        _state["proc"] = SegformerImageProcessor.from_pretrained(d, local_files_only=True)
        model = AutoModelForSemanticSegmentation.from_pretrained(d, local_files_only=True)
        _state["model"] = model.to(device).eval()
        _state["ok"] = True
    except Exception as e:                # 别把整条流水线拖死
        _state["why"] = f"{type(e).__name__}: {e}"
        _state["ok"] = False
    return _state["ok"]


def why():
    return _state["why"]


def _box(mask):
    import numpy as np
    if mask.sum() < 10:
        return None
    ys, xs = np.where(mask)
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def _scale_box(box, full, small):
    """把在小图上量到的框换算回原图坐标。"""
    if not box:
        return None
    sx = full[0] / float(small[0])
    sy = full[1] / float(small[1])
    out = [int(round(box[0] * sx)), int(round(box[1] * sy)),
           int(round(box[2] * sx)), int(round(box[3] * sy))]
    out[2] = min(out[2], full[0])
    out[3] = min(out[3], full[1])
    return [max(0, out[0]), max(0, out[1]), out[2], out[3]]


def analyze(path, models_dir, device="cpu", want_mask=False):
    """返回 {"box": 衣服外框, "share": 衣服像素占比, "head_box": 头部外框或 None,
    "labels": {类名: 占比}, "ms": 耗时}；want_mask=True 时多给一份衣服掩码。
    box 和 mask 都是**原图坐标**（mask 尺寸等于原图）。跑不起来返回 None。"""
    if not load(models_dir, device):
        return None
    try:
        import numpy as np
        import torch
        import torch.nn.functional as F
        im = photos.open_upright(path).convert("RGB")
        full = im.size
        t0 = time.time()
        small = im
        if max(full) > ANALYZE_MAX_SIDE:
            small = im.copy()
            small.thumbnail((ANALYZE_MAX_SIDE, ANALYZE_MAX_SIDE), Image.LANCZOS)

        inputs = _state["proc"](images=small, return_tensors="pt").to(device)
        with torch.no_grad():
            logits = _state["model"](**inputs).logits
        seg = F.interpolate(logits, size=small.size[::-1], mode="bilinear",
                            align_corners=False).argmax(1)[0].cpu().numpy()
        total = seg.size
        garment, head = np.isin(seg, GARMENT), np.isin(seg, HEAD)
        labels = {}
        for v in np.unique(seg):
            share = float((seg == v).sum()) / total
            if share >= 0.005:
                labels[NAMES.get(int(v), str(int(v)))] = round(share, 3)

        mask = None
        if want_mask:
            mask = garment
            if small.size != full:      # 放回原图尺寸，下游按原图裁
                mask = np.array(Image.fromarray(garment.astype(np.uint8) * 255, "L")
                                .resize(full, Image.NEAREST)) > 127
        box = _box(garment)
        head_box = _box(head)
        if small.size != full:         # 框统一换算回原图坐标
            box = _scale_box(box, full, small.size)
            head_box = _scale_box(head_box, full, small.size)
        return {
            "box": box,
            "share": round(float(garment.sum()) / total, 3),
            "head_box": head_box,
            "labels": labels,
            "ms": int((time.time() - t0) * 1000),
            "mask": mask if want_mask else None,
        }
    except Exception as e:
        _state["why"] = f"{type(e).__name__}: {e}"
        return None
