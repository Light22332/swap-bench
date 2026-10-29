"""人脸与人物的本地判定（OpenCV YuNet + SFace）。

这是本项目第一次能真正回答"还是不是同一个人"。
之前用像素相关做过尝试，失败了：生成图常常重新构图（近景/远景），
像素级比对既有假阴（对齐不上）又有假阳（整幅照抄反而更像）。

现在的做法是标准路径：检测人脸 → 对齐 → 提特征 → 余弦相似度。
实测分离度：换对人的 0.75~0.91，换错人/脸被挡的 0.00~0.19。

两个坑记在这里：
1. cv2.imread 读不了中文路径，必须 open() + imdecode，或者干脆走 PIL。
2. cv2 的 ONNX 加载器也读不了中文路径，模型要复制到临时目录再加载。
"""
import os
import shutil
import tempfile

import cv2
import numpy as np
from PIL import Image

DET_FILE = "face_detection_yunet.onnx"
REC_FILE = "face_recognition_sface.onnx"

_state = {"det": None, "rec": None, "tried": False, "ok": False, "why": ""}


def _ascii_copy(path):
    """OpenCV 的 ONNX 导入器只认 ASCII 路径。"""
    if path.isascii():
        return path
    dst = os.path.join(tempfile.gettempdir(), "swapbench_" + os.path.basename(path))
    need = (not os.path.exists(dst)) or os.path.getsize(dst) != os.path.getsize(path)
    if need:
        shutil.copy2(path, dst)
    return dst


def _to_bgr(path, max_side=960):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    w, h = im.size
    s = max_side / max(w, h)
    if s < 1:
        im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
    arr = np.asarray(im, dtype=np.uint8)          # RGB
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)   # BGR


def load(models_dir):
    """懒加载两个模型。缺文件时返回 False，调用方降级。"""
    if _state["tried"]:
        return _state["ok"]
    _state["tried"] = True
    det = os.path.join(models_dir, DET_FILE)
    rec = os.path.join(models_dir, REC_FILE)
    missing = [p for p in (det, rec) if not os.path.isfile(p)]
    if missing:
        _state["why"] = "缺少模型：" + "、".join(os.path.basename(p) for p in missing)
        return False
    try:
        _state["det"] = det
        _state["rec"] = cv2.FaceRecognizerSF.create(_ascii_copy(rec), "")
        _state["ok"] = True
    except Exception as e:                     # 模型坏了也不要炸整条流水线
        _state["why"] = f"{type(e).__name__}: {e}"
        _state["ok"] = False
    return _state["ok"]


def why():
    return _state["why"]


def _detector(w, h):
    det = _state.setdefault("detector", None)
    if det is None:
        det = cv2.FaceDetectorYN.create(
            _ascii_copy(_state["det"]), "", (w, h), 0.6, 0.3, 50)
        _state["detector"] = det
    det.setInputSize((w, h))
    return det


def analyze(path):
    """返回 {"count": 人脸数, "emb": 最大人脸的特征向量或 None, "box": 归一化框}"""
    if not _state["ok"]:
        return None
    try:
        img = _to_bgr(path)
    except Exception:
        return None
    h, w = img.shape[:2]
    try:
        _, faces = _detector(w, h).detect(img)
    except Exception:
        return None
    if faces is None or len(faces) == 0:
        return {"count": 0, "emb": None, "box": None}
    faces = sorted(faces, key=lambda f: -f[14])
    best = faces[0]
    try:
        crop = _state["rec"].alignCrop(img, best)
        emb = _state["rec"].feature(crop).flatten()
    except Exception:
        emb = None
    return {
        "count": len(faces),
        "emb": emb,
        "box": {
            "x": float(best[0] / w), "y": float(best[1] / h),
            "w": float(best[2] / w), "h": float(best[3] / h),
            "score": float(best[14]),
        },
    }


def similarity(a, b):
    if a is None or b is None:
        return None
    a = a / (np.linalg.norm(a) or 1e-6)
    b = b / (np.linalg.norm(b) or 1e-6)
    return float(a @ b)
