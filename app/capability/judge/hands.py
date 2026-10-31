"""手部检测（MediaPipe 手掌检测 + 21 点关键点，走 OpenCV DNN）。

为什么是两级：

手掌检测器负责"找到手"，但它在毛领、袖口、褶皱的布料上会误报——实测
一件平铺的皮草外套被判出 3 只手，最高 0.87 分，比真手的 0.70 还高。
所以分数不能直接拿来数手。第二级用 21 点关键点模型复核每个框，它认不出的
东西置信度明显低。两级都认，才算一只手。

两个坑和 faces.py 一样：cv2.imread 读不了中文路径，OpenCV 的 ONNX 加载器
同样读不了，模型要先复制到临时目录再加载。

模型来自 OpenCV Zoo（转换自 MediaPipe）：
  palm_detection_mediapipe_2023feb.onnx
  handpose_estimation_mediapipe_2023feb.onnx
"""
import os
import shutil
import tempfile
import threading

import cv2
import numpy as np
from PIL import Image

from ...core import log, photos

PALM_FILE = "palm_detection_mediapipe_2023feb.onnx"
POSE_FILE = "handpose_estimation_mediapipe_2023feb.onnx"

PALM_IN = 192
POSE_IN = 224
PALM_SCORE = 0.30        # 一级门槛放低，误报交给二级筛
POSE_CONF = 0.70         # 二级门槛：实测好手 0.90~0.99，糊成一片的 0.52，边界样本 0.75

_state = {"palm": None, "pose": None, "tried": False, "ok": False, "why": ""}
# 两个 ONNX 实例是进程里唯一的，cv2.dnn 的 setInput/forward 不能并发调：
# 云端并发跑任务时用一把锁串起来。
_lock = threading.Lock()
logger = log.get("judge.hands")


def _ascii_copy(path):
    if path.isascii():
        return path
    dst = os.path.join(tempfile.gettempdir(), "swapbench_" + os.path.basename(path))
    if (not os.path.exists(dst)) or os.path.getsize(dst) != os.path.getsize(path):
        shutil.copy2(path, dst)
    return dst


def _img_to_bgr(im, max_side=1280):
    """一张读好的图 → BGR。缩小只为省时间，不改判定。"""
    im = photos.flatten(im)
    w, h = im.size
    s = max_side / max(w, h)
    if s < 1:
        im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
    return cv2.cvtColor(np.asarray(im, dtype=np.uint8), cv2.COLOR_RGB2BGR)


def _palm_anchors():
    """2016 个锚点中心：24×24 网格每格 2 个，12×12 网格每格 6 个。

    对应 MediaPipe 的 SSD anchor 配置（min_scale 0.1484、max_scale 0.75、
    strides 8/16/16/16）。后三层 stride 相同，导出时并成了同一个 12×12 网格，
    每格 6 个（三层 × 2 个尺度），所以是 24²×2 + 12²×6 = 2016。
    顺序必须和输出张量一致，建成后按输出长度校验，对不上就抛错，而不是给出错位的框。
    """
    out = []
    for grid, per_cell in ((24, 2), (12, 6)):   # 12 网格三层合并到一起，每格 6 个
        for y in range(grid):
            for x in range(grid):
                cx, cy = (x + 0.5) / grid, (y + 0.5) / grid
                out.extend([(cx, cy)] * per_cell)
    return np.asarray(out, dtype=np.float32)


class PalmDetector:
    def __init__(self, model_path):
        self.net = cv2.dnn.readNet(model_path)
        self.anchors = _palm_anchors()

    def detect(self, img, score_th=PALM_SCORE, nms_th=0.3):
        h, w = img.shape[:2]
        ratio = PALM_IN / max(h, w)
        nw, nh = max(1, int(round(w * ratio))), max(1, int(round(h * ratio)))
        small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        pad_w, pad_h = PALM_IN - nw, PALM_IN - nh
        left, top = pad_w // 2, pad_h // 2
        small = cv2.copyMakeBorder(small, top, pad_h - top, left, pad_w - left,
                                   cv2.BORDER_CONSTANT, value=(0, 0, 0))
        blob = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        self.net.setInput(blob[None])
        out = self.net.forward(self.net.getUnconnectedOutLayersNames())

        score = 1.0 / (1.0 + np.exp(-out[1][0, :, 0].astype(np.float64)))
        if len(score) != len(self.anchors):
            raise RuntimeError(f"锚点数 {len(self.anchors)} 与模型输出 {len(score)} 不一致")
        delta = out[0][0, :, :4]
        scale = max(w, h)
        cxy = delta[:, :2] / PALM_IN
        wh = delta[:, 2:] / PALM_IN
        xy1 = (cxy - wh / 2 + self.anchors) * scale
        xy2 = (cxy + wh / 2 + self.anchors) * scale
        boxes = np.concatenate([xy1, xy2], axis=1)
        boxes -= np.array([left, top, left, top], dtype=np.float64) / ratio

        keep = cv2.dnn.NMSBoxes(boxes, score, score_th, nms_th, top_k=5000)
        if keep is None or not len(keep):
            return []
        keep = np.asarray(keep).reshape(-1)
        # 手掌 7 个关键点：相对锚点的偏移 → 原图坐标。不换算的话全是几十像素的
        # 小数字，后面按它算旋转角会得到乱七八糟的方向。
        bias = np.array([left, top], dtype=np.float64) / ratio
        lm = out[0][0, keep][:, 4:18].reshape(-1, 7, 2) / PALM_IN
        lm = (lm + self.anchors[keep][:, None, :]) * scale - bias
        return [np.r_[boxes[i], lm[n].reshape(-1), score[i]] for n, i in enumerate(keep)]


class HandPose:
    """21 点关键点。输入是手掌检测给的框，输出置信度与手部框。"""

    def __init__(self, model_path, conf_th=POSE_CONF):
        self.net = cv2.dnn.readNet(model_path)
        self.conf_th = conf_th

    @staticmethod
    def _crop_pad(image, box, enlarge, shift=(0.0, 0.0)):
        box = np.asarray(box, dtype=np.float64)
        box = box + np.array(shift) * (box[1] - box[0])
        center = box.sum(axis=0) / 2
        half = (box[1] - box[0]) * enlarge / 2
        box = np.array([center - half, center + half]).astype(np.int32)
        box[:, 0] = np.clip(box[:, 0], 0, image.shape[1])
        box[:, 1] = np.clip(box[:, 1], 0, image.shape[0])
        crop = image[box[0][1]:box[1][1], box[0][0]:box[1][0], :]
        if crop.size == 0:
            return None, box, np.zeros(2, dtype=np.int32)
        side = int(max(crop.shape[:2]))
        pad_h, pad_w = side - crop.shape[0], side - crop.shape[1]
        left, top = pad_w // 2, pad_h // 2
        crop = cv2.copyMakeBorder(crop, top, pad_h - top, left, pad_w - left,
                                  cv2.BORDER_CONSTANT, value=(0, 0, 0))
        return crop, box, box[0] - np.array([left, top], dtype=np.int32)

    def infer(self, image, palm):
        """palm: 19 维 [x1,y1,x2,y2, 7×2 个手掌点, score]。返回 None 表示不像手。"""
        pad_bias = np.zeros(2, dtype=np.int32)
        palm_box = np.asarray(palm[0:4], dtype=np.float64).reshape(2, 2)
        # 先用 4 倍框做旋转估计，保证边角不被裁掉
        crop, palm_box2, bias = self._crop_pad(image, palm_box, 4.0)
        if crop is None:
            return None
        pad_bias = pad_bias + bias
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        palm_box2 = palm_box2 - pad_bias
        pts = np.asarray(palm[4:18], dtype=np.float64).reshape(7, 2) - pad_bias
        p1, p2 = pts[0], pts[2]
        radians = np.pi / 2 - np.arctan2(-(p2[1] - p1[1]), p2[0] - p1[0])
        radians = radians - 2 * np.pi * np.floor((radians + np.pi) / (2 * np.pi))
        angle = float(np.rad2deg(radians))
        center = palm_box2.sum(axis=0) / 2
        rot = cv2.getRotationMatrix2D(tuple(center), angle, 1.0)
        rotated = cv2.warpAffine(crop, rot, (crop.shape[1], crop.shape[0]))
        hom = np.c_[pts, np.ones(len(pts))]
        rot_pts = np.array([hom @ rot[0], hom @ rot[1]])
        rot_box = np.array([rot_pts.min(axis=1), rot_pts.max(axis=1)])
        # 再用 3 倍框裁出真正的手
        crop2, rot_box2, _ = self._crop_pad(rotated, rot_box, 3.0, shift=(0.0, -0.4))
        if crop2 is None:
            return None
        blob = cv2.resize(crop2, (POSE_IN, POSE_IN), interpolation=cv2.INTER_AREA)
        self.net.setInput((blob.astype(np.float32) / 255.0)[None])
        out = self.net.forward(self.net.getUnconnectedOutLayersNames())
        conf = float(out[1][0][0])

        lm = out[0][0].reshape(-1, 3).astype(np.float64)
        wh = (rot_box2[1] - rot_box2[0]).astype(np.float64)
        sf = wh / POSE_IN
        lm[:, :2] = (lm[:, :2] - POSE_IN / 2) * float(max(sf))
        coord_rot = cv2.getRotationMatrix2D((0, 0), angle, 1.0)
        lm_rot = lm[:, :2] @ coord_rot[:, :2]
        # 反旋转回原图坐标
        rot_part = np.array([[rot[0][0], rot[1][0]], [rot[0][1], rot[1][1]]])
        trans = np.array([rot[0][2], rot[1][2]])
        inv_trans = np.array([-rot_part[0] @ trans, -rot_part[1] @ trans])
        inv = np.c_[rot_part, inv_trans]
        c = np.append(rot_box2.sum(axis=0) / 2, 1)
        origin = np.array([c @ inv[0], c @ inv[1]])
        lm_xy = lm_rot + origin + pad_bias

        box = np.array([lm_xy.min(axis=0), lm_xy.max(axis=0)])
        # conf 低于门槛也返回，调用方要区分"这里没有手"和"这里有手但画坏了"
        return {"conf": conf, "ok": conf >= self.conf_th,
                "box": box.reshape(-1), "landmarks": lm_xy}


def load(models_dir):
    with _lock:
        if _state["tried"]:
            return _state["ok"]
        _state["tried"] = True
        palm = os.path.join(models_dir, PALM_FILE)
        pose = os.path.join(models_dir, POSE_FILE)
        missing = [p for p in (palm, pose) if not os.path.isfile(p)]
        if missing:
            _state["why"] = "缺少模型：" + "、".join(os.path.basename(p) for p in missing)
            logger.warning("手部模型没加载：%s", _state["why"])
            return False
        try:
            _state["palm"] = PalmDetector(_ascii_copy(palm))
            _state["pose"] = HandPose(_ascii_copy(pose))
            _state["ok"] = True
            logger.info("手部模型已加载")
        except Exception as e:
            _state["why"] = f"{type(e).__name__}: {e}"
            _state["ok"] = False
            logger.warning("手部模型加载失败：%s", _state["why"])
        return _state["ok"]


def why():
    return _state["why"]


def analyze(path, max_hands=6):
    """读文件后交给 analyze_image()。读不了返回 None。"""
    try:
        im = photos.open_upright(path)
    except Exception:
        return None
    return analyze_image(im, max_hands=max_hands)


def analyze_image(im, max_hands=6):
    """返回 {"count": 复核通过的手数, "raw": 一级检出数, "hands": [...], "weak": [...]}

    weak 是一级找到了框、但 21 点复核没过的地方。它有用：真手被挡住时它是个漏检，
    手指糊成一团时它是个"手画坏了"的证据——两种情况的结论一样（不合格），
    但说给用户的话不一样。

    读图交给调用方做，是为了让一次判定里两张图只解码一次（参见 rules.evaluate）。
    """
    if not _state["ok"]:
        return None
    try:
        img = _img_to_bgr(im)
    except Exception:
        return None
    with _lock:
        try:
            palms = _state["palm"].detect(img)
        except Exception as e:
            _state["why"] = f"{type(e).__name__}: {e}"
            logger.warning("手掌检测失败：%s", _state["why"])
            return None
        hands, weak = [], []
        for p in palms:
            try:
                r = _state["pose"].infer(img, p)
            except Exception:
                continue
            if r is None:
                continue
            r["palm_score"] = float(p[18])
            if len(hands) < max_hands and r["ok"]:
                hands.append(r)
            elif not r["ok"]:
                weak.append({"conf": r["conf"], "palm_score": r["palm_score"]})
        return {"count": len(hands), "raw": len(palms), "hands": hands, "weak": weak}
