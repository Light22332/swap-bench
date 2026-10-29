"""本地质检（真判定，不糊弄）。

四项：
  脸没变        人脸识别比对，余弦相似度
  衣服换上了     身体区域的像素变化量
  背景没动       从原图推平坦区域，比背景主色
  没有多余的人   人脸数量

判不了的（手部结构、文字水印）不在这里装样子，见 base.DROPPED。

背景这一项放弃了"逐块对齐"的做法：生成图经常重新构图，
块对不上就会把正常结果判成背景出错。改成各自取背景主色再比距离，
对近景/远景都成立。
"""
import time

from PIL import Image, ImageChops, ImageStat

from . import faces
from .base import blank_verdict, summarize

GRID = 16
SMALL = 128
FLAT_STD = 10.0
CHANGE_TH = 12.0
BG_COLOR_MAX = 30.0        # 背景主色距离上限
BODY_CHANGED_MIN = 0.20    # 身体区域变化块比例下限
FACE_SIM_MIN = 0.45        # 人脸相似度下限（实测：对 0.75+，错 0.00~0.19）


def _prep(path):
    im = Image.open(path)
    ratio = im.width / im.height
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)   # 只 convert 会让透明区变黑
    return im.convert("RGB").resize((SMALL, SMALL), Image.LANCZOS), ratio


def _blocks(im):
    step = SMALL // GRID
    out = []
    for r in range(GRID):
        row = []
        for c in range(GRID):
            box = (c * step, r * step, (c + 1) * step, (r + 1) * step)
            row.append(im.crop(box))
        out.append(row)
    return out


def _block_std(patch):
    return sum(ImageStat.Stat(patch).stddev) / 3.0


def _median_rgb(patches):
    rs, gs, bs = [], [], []
    for p in patches:
        m = ImageStat.Stat(p).mean
        rs.append(m[0]); gs.append(m[1]); bs.append(m[2])
    rs.sort(); gs.sort(); bs.sort()
    n = len(rs)
    if not n:
        return None
    return (rs[n // 2], gs[n // 2], bs[n // 2])


def background_color(im):
    """平坦块的均值中位数 ≈ 背景色。没有平坦块就返回 None。"""
    flat = [p for row in _blocks(im) for p in row if _block_std(p) < FLAT_STD]
    if len(flat) < 12:
        return None, 0
    return _median_rgb(flat), len(flat)


def _body_changed(p, r):
    """身体区域有多少块变了。只判断"动没动"，不判断"换成哪件"。"""
    step = SMALL // GRID
    total = changed = 0
    for row in range(int(GRID * 0.35), int(GRID * 0.95)):
        for col in range(int(GRID * 0.15), int(GRID * 0.85)):
            box = (col * step, row * step, (col + 1) * step, (row + 1) * step)
            d = ImageChops.difference(p.crop(box), r.crop(box))
            m = sum(ImageStat.Stat(d).mean) / 3.0
            total += 1
            if m > CHANGE_TH:
                changed += 1
    return (changed / total) if total else 0.0


def evaluate(person_path, result_path, garment_path=None, models_dir=None, **_):
    t0 = time.time()

    try:
        p, p_ratio = _prep(person_path)
        r, r_ratio = _prep(result_path)
    except Exception as e:
        v = blank_verdict("local", f"读图失败：{e}")
        v["error"] = str(e)
        return v

    checks = {}

    # ---- 脸 ----
    face_note = ""
    if models_dir and faces.load(models_dir):
        pa = faces.analyze(person_path)
        ra = faces.analyze(result_path)
        if pa and pa.get("emb") is not None and ra and ra.get("emb") is not None:
            sim = faces.similarity(pa["emb"], ra["emb"])
            checks["face_preserved"] = {
                "pass": sim >= FACE_SIM_MIN,
                "reason": f"人脸相似度 {sim:.2f}（阈值 {FACE_SIM_MIN}）",
                "sim": round(sim, 3),
            }
        elif ra and ra.get("count") == 0:
            checks["face_preserved"] = {
                "pass": False,
                "reason": "结果里检测不到人脸（被挡住或换掉了）",
            }
        else:
            checks["face_preserved"] = {
                "pass": None, "reason": "这张人像里找不到可用的人脸，无法比对",
            }
        if ra:
            limit = max(1, (pa or {}).get("count") or 1)
            checks["no_extra_person"] = {
                "pass": ra.get("count", 0) <= limit,
                "reason": f"结果里 {ra.get('count', 0)} 张脸",
            }
    else:
        checks["face_preserved"] = {"pass": None, "reason": faces.why() or "人脸模型未加载"}

    # ---- 衣服 ----
    changed = _body_changed(p, r)
    checks["garment_applied"] = {
        "pass": changed >= BODY_CHANGED_MIN,
        "reason": f"身体区域变化 {changed * 100:.0f}%",
    }

    # ---- 背景 ----
    p_bg, p_n = background_color(p)
    r_bg, r_n = background_color(r)
    if p_bg and r_bg:
        dist = sum(abs(a - b) for a, b in zip(p_bg, r_bg)) ** 0.5 * 1.0
        dist = (sum((a - b) ** 2 for a, b in zip(p_bg, r_bg))) ** 0.5
        checks["background_preserved"] = {
            "pass": dist <= BG_COLOR_MAX and abs(p_ratio - r_ratio) / p_ratio < 0.05,
            "reason": f"背景主色距离 {dist:.0f}（阈值 {BG_COLOR_MAX:.0f}）",
        }
    else:
        checks["background_preserved"] = {
            "pass": None, "reason": "背景不是纯色，判不了",
        }

    judged = sum(1 for c in checks.values() if c.get("pass") is not None)
    note = (f"本地质检：{judged}/4 项可自动判定；"
            "手部结构、文字水印不做自动检查，需人看一眼")
    return summarize(checks, "local", note=note, latency_s=time.time() - t0)
