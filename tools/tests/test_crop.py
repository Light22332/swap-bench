"""参考图整理（crop_garment）的测试：不需要模型、不需要 GPU。

重点测「衣服图不理想」的那条兜底：解析出来的衣服太小（< SHARE_SURE）时，
先抠图白底当参考；抠不出来就记一条 warn，别偷偷按框裁一张没用的。
跑法：python tools/tests/test_crop.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from PIL import Image                                  # noqa: E402
from app.capability.prep import crop                   # noqa: E402

FAILED = []
TMP = os.path.join(ROOT, "outputs", "_test_crop")
os.makedirs(TMP, exist_ok=True)


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


shot = os.path.join(TMP, "shot.png")
Image.new("RGB", (300, 500), (250, 250, 250)).save(shot)
out_dir = os.path.join(TMP, "out")


def fake_analyze(share, box=None):
    def _f(path, models_dir, device="cpu", want_mask=False):
        return {"box": box, "share": share, "labels": {"背景": 0.9},
                "mask": None, "parse_ms": 1}
    return _f


def fake_extract_ok(path, out_dir2, models_dir, device="cpu"):
    os.makedirs(out_dir2, exist_ok=True)
    dst = os.path.join(out_dir2, "cut.png")
    Image.new("RGB", (60, 80), (10, 20, 30)).save(dst)
    return dst, {"share": 0.4, "size": [60, 80], "labels": {}, "ms": 1}


def fake_extract_fail(path, out_dir2, models_dir, device="cpu"):
    return None, {"error": "没抠出来"}


orig_analyze, orig_extract = crop.parse_clothes.analyze, crop.extract_garment.extract


def run(analyze, extract):
    calls = {"extract": 0}

    def counting(*a, **kw):
        calls["extract"] += 1
        return extract(*a, **kw)

    crop.parse_clothes.analyze = analyze
    crop.extract_garment.extract = counting
    try:
        return crop.crop_garment(shot, out_dir, "parse", "stub", "cpu"), calls
    finally:
        crop.parse_clothes.analyze = orig_analyze
        crop.extract_garment.extract = orig_extract


print("衣服图太小（整屏截图那种）")
(p, meta), calls = run(fake_analyze(0.05, box=(10, 10, 60, 80)), fake_extract_ok)
check("走了抠图", meta.get("how") == "extract", str(meta))
check("返回抠图产物", str(p).endswith("cut.png"), str(p))
check("记录带抠图占比", meta.get("extract_share") == 0.4, str(meta))
check("记录带抠图尺寸", meta.get("extract_size") == [60, 80], str(meta))
check("只抠一次", calls["extract"] == 1, str(calls))

print("抠图失败")
(p2, meta2), calls2 = run(fake_analyze(0.05), fake_extract_fail)
check("没把失败当成功", str(p2) != "cut.png", str(p2))
check("记了 warn 提示", bool(meta2.get("warn")), str(meta2))
check("warn 说衣服没抠出来", "没抠出" in (meta2.get("warn") or ""), str(meta2))
check("还走了老兜底（fixed/none）", meta2.get("how") in ("fixed", "none"), str(meta2))

print("干净商品图（衣服够大）")
(p3, meta3), calls3 = run(fake_analyze(0.5), fake_extract_ok)
check("不触发抠图", meta3.get("how") != "extract", str(meta3))
check("抠图没被调用", calls3["extract"] == 0, str(calls3))
check("走了固定比例裁", meta3.get("how") == "fixed", str(meta3))

print()
if FAILED:
    print(f"{len(FAILED)} 项没过：" + "、".join(FAILED))
    sys.exit(1)
print("全部通过")
