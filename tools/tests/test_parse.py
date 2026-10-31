"""人像解析的坐标换算：大图不整张喂模型，但框和掩码要按原图坐标给。

真模型不参与——假 processor 记下它看到的尺寸，假模型吐一块固定的中心矩形
（上衣类，128×128 的 logits 中间 64×64），这样坐标对不对一目了然。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import torch
from PIL import Image

from app.capability.prep import parse_clothes as pc
from app.core import paths

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILED.append(name)


class FakeInputs(dict):
    def to(self, device):
        return self


class FakeProc:
    def __init__(self):
        self.seen = None

    def __call__(self, images, return_tensors=None):
        self.seen = images.size
        return FakeInputs(pixel_values=torch.zeros(1, 3, 512, 512))


class FakeOut:
    def __init__(self, logits):
        self.logits = logits


class FakeModel:
    def __init__(self, cls=4):
        self.cls = cls

    def __call__(self, **kw):
        logits = torch.full((1, 18, 128, 128), -10.0)
        logits[:, self.cls, 32:96, 32:96] = 10.0
        return FakeOut(logits)


def use_fake(cls=4):
    pc._state.update(proc=FakeProc(), model=FakeModel(cls), dir=pc.model_dir("models"),
                     device="cpu", tried=True, ok=True, why="")


def make_img(path, size, color=(200, 120, 90)):
    Image.new("RGB", size, color).save(path, quality=90)
    return path


def main():
    out = os.path.join(paths.OUTPUTS, "_test_parse")
    os.makedirs(out, exist_ok=True)
    big = make_img(os.path.join(out, "big.jpg"), (2048, 2048))
    small = make_img(os.path.join(out, "small.jpg"), (512, 512))

    # 大图：processor 只该看到 1024，掩码和框要回到 2048
    use_fake()
    info = pc.analyze(big, "models", want_mask=True)
    check("大图返回结果", info is not None, pc.why())
    seen = pc._state["proc"].seen
    check("processor 只看到 1024 长边", seen == (1024, 1024), seen)
    check("掩码是原图尺寸", info and info["mask"].shape == (2048, 2048),
          None if not info else info["mask"].shape)
    check("衣服框换算回原图坐标",
          info and all(abs(a - b) <= 10 for a, b in zip(info["box"], [512, 512, 1536, 1536])),
          None if not info else info["box"])
    check("衣服占比约 1/4", info and abs(info["share"] - 0.25) <= 0.02,
          None if not info else info["share"])
    check("标签按小图统计", info and 0.24 <= info["labels"].get("上衣", 0) <= 0.28,
          None if not info else info["labels"])
    check("没有头就是 None", info and info["head_box"] is None, None if not info else info["head_box"])

    # 小图：不缩放
    use_fake()
    info2 = pc.analyze(small, "models", want_mask=False)
    check("小图直接喂", pc._state["proc"].seen == (512, 512), pc._state["proc"].seen)
    check("不要掩码就不给", info2 is not None and info2["mask"] is None)
    check("小图框也对",
          info2 and all(abs(a - b) <= 2 for a, b in zip(info2["box"], [128, 128, 384, 384])),
          None if not info2 else info2["box"])

    # 只有背景：没框、占比 0
    use_fake(cls=0)
    info3 = pc.analyze(big, "models", want_mask=True)
    check("没衣服时框为 None", info3 is not None and info3["box"] is None)
    check("没衣服时占比 0", info3 is not None and info3["share"] == 0)

    # 模型没加载：返回 None
    pc._state.update(ok=False, why="")
    check("加载失败返回 None", pc.analyze(big, "models") is None)

    # 换算函数本身：贴边时裁到原图内
    check("换算不超出原图", pc._scale_box([3, 4, 30, 40], (30, 40), (10, 10))
          == [9, 16, 30, 40], pc._scale_box([3, 4, 30, 40], (30, 40), (10, 10)))
    check("None 还是 None", pc._scale_box(None, (10, 10), (5, 5)) is None)

    if FAILED:
        print(f"\n{len(FAILED)} 项失败：{', '.join(FAILED)}")
        return 1
    print("\n全部通过（人像解析坐标换算）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
