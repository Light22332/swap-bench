"""判定层的测试：不加载模型、不需要 GPU、不需要 ComfyUI。

onxx 模型不在仓库里，所以人脸和手这两项这里只测"没有模型时的降级行为"；
真正拿模型跑判定的路径由 tools/check.py 的判定冒烟覆盖（用 samples 里的图）。

跑法：python tools/tests/test_rules.py
"""
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw                   # noqa: E402
from app.capability.judge import rules             # noqa: E402

FAILED = []
TMP = os.path.join(ROOT, "outputs", "_test_rules")
os.makedirs(TMP, exist_ok=True)


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def canvas(size=(256, 320), bg=(245, 245, 245), body=None, box=(0.25, 0.40, 0.75, 0.90)):
    """一张"人像"：纯色背景 + 中间一块矩形当身体。"""
    im = Image.new("RGB", size, bg)
    if body is not None:
        w, h = size
        x0, y0, x1, y1 = box
        ImageDraw.Draw(im).rectangle(
            [int(w * x0), int(h * y0), int(w * x1), int(h * y1)], fill=body)
    return im


def save(im, name):
    p = os.path.join(TMP, name)
    im.save(p)
    return p


print("预处理：读图、透明底、缩放")
gray = canvas(body=(150, 150, 150))
p_gray = save(gray, "person.png")
im128, ratio = rules._prep(p_gray)
check("缩到 128×128", im128.size == (rules.SMALL, rules.SMALL), str(im128.size))
check("长宽比保留", abs(ratio - 256 / 320) < 0.01, f"{ratio:.3f}")

rgba = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
rgba.putpixel((0, 0), (255, 0, 0, 255))
im_rgba, _ = rules._prep(save(rgba, "alpha.png"))
r, g, b = im_rgba.getpixel((127, 127))
check("透明区补白底，不是黑", r > 250 and g > 250 and b > 250, f"像素 {im_rgba.getpixel((127, 127))}")

pal = canvas().convert("P")
im_pal, _ = rules._prep(save(pal, "palette.png"))
check("调色板图能读", im_pal.mode == "RGB", im_pal.mode)

print("背景主色：只统计平坦块")
bg, n = rules.background_color(rules._prep(save(canvas(bg=(200, 200, 200)), "flat.png"))[0])
check("纯色图取到背景色", bg is not None and abs(bg[0] - 200) <= 2, str(bg))
check("平坦块数等于全部块数", n == rules.GRID * rules.GRID, str(n))

noise = Image.new("RGB", (256, 320))
px = noise.load()
rnd = random.Random(7)
for y in range(320):
    for x in range(256):
        px[x, y] = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
bg, n = rules.background_color(rules._prep(save(noise, "noise.png"))[0])
check("满屏噪点判不出背景", bg is None and n == 0, f"{bg} / {n}")

print("衣服换没换：只看身体区域的块")
same = rules._body_changed(*[rules._prep(save(canvas(body=(150, 150, 150)), n))[0]
                             for n in ("a.png", "a2.png")])
check("同一张图 0 变化", same == 0.0, str(same))

changed = rules._body_changed(
    rules._prep(save(canvas(body=(150, 150, 150)), "b1.png"))[0],
    rules._prep(save(canvas(body=(30, 60, 120)), "b2.png"))[0])
check("身体块变蓝 → 判定为换了", changed >= rules.BODY_CHANGED_MIN, f"{changed:.2f}")

head1 = canvas(body=(150, 150, 150))
head2 = head1.copy()
ImageDraw.Draw(head2).rectangle([64, 10, 190, 90], fill=(20, 20, 20))   # 只动头部那片
head_only = rules._body_changed(rules._prep(save(head1, "c1.png"))[0],
                                rules._prep(save(head2, "c2.png"))[0])
check("只改头部不算换衣服", head_only == 0.0, f"{head_only:.2f}")

print("整条判定：没有模型时怎么降级")
v = rules.evaluate(p_gray, save(canvas(body=(150, 150, 150)), "same.png"), models_dir=None)
check("脸判不了 → null", v["checks"]["face_preserved"]["pass"] is None)
check("手判不了 → null", v["checks"]["hand_preserved"]["pass"] is None)
check("判了 2 项", v["judged"] == 2, str(v["judged"]))
check("衣服没换 → 不过", v["checks"]["garment_applied"]["pass"] is False)
check("背景没动 → 过", v["checks"]["background_preserved"]["pass"] is True)
check("关键项不过 → 整体不过", v["passed"] is False, str(v["passed"]))
check("降级时不宣称语义已检", v["semantic_checked"] is False, str(v["semantic_checked"]))
check("note 写明 2/5", "2/5" in v["note"], v["note"])

v2 = rules.evaluate(p_gray, save(canvas(body=(30, 60, 120)), "worn.png"), models_dir=None)
check("换了衣服 → 这一项过", v2["checks"]["garment_applied"]["pass"] is True)
check("两项都过 → 整体过", v2["passed"] is True, str(v2["score"]))
check("分数是 1.0", abs(v2["score"] - 1.0) < 0.001, str(v2["score"]))

v3 = rules.evaluate(p_gray, save(canvas(bg=(120, 120, 120), body=(30, 60, 120)), "bgmove.png"),
                    models_dir=None)
check("背景被换 → 这一项不过", v3["checks"]["background_preserved"]["pass"] is False)
check("非关键项不过 + 分数不够 → 整体不过", v3["passed"] is False, str(v3["score"]))

v4 = rules.evaluate(p_gray, save(canvas(size=(256, 256), body=(30, 60, 120)), "reshape.png"),
                    models_dir=None)
check("构图比例变了 → 背景不过", v4["checks"]["background_preserved"]["pass"] is False)

print("读不到图时不抛异常")
v5 = rules.evaluate(p_gray, os.path.join(TMP, "没有这个文件.png"), models_dir=None)
check("返回 error 判定", bool(v5.get("error")) and v5["passed"] is False, str(v5.get("error")))

print()
if FAILED:
    print(f"{len(FAILED)} 项没过：" + "、".join(FAILED))
    sys.exit(1)
print("全部通过")
