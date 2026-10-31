"""本地质检（真判定，不糊弄）。

五项：
  脸没变        人脸识别比对，余弦相似度
  衣服换上了     身体区域的像素变化量
  手还在        手掌检测 + 关键点复核，比原图和结果的手数
  背景没动       从原图推平坦区域，比背景主色
  没有多余的人   人脸数量

判不了的（文字水印）不在这里装样子，见 base.DROPPED。

背景这一项放弃了"逐块对齐"的做法：生成图经常重新构图，
块对不上就会把正常结果判成背景出错。改成各自取背景主色再比距离，
对近景/远景都成立。
"""
import time

from PIL import Image, ImageChops, ImageStat

from . import faces, hands
from ...core import photos
from ...core.checks import CHECKS, blank_verdict, summarize

GRID = 16
SMALL = 128
FLAT_STD = 10.0
CHANGE_TH = 12.0
BG_COLOR_MAX = 30.0        # 背景主色距离上限
BODY_CHANGED_MIN = 0.20    # 身体区域变化块比例下限
FACE_SIM_MIN = 0.45        # 人脸相似度下限（实测：对 0.75+，错 0.00~0.19）


def _prep_image(im):
    """一张读好的图 → (128×128 RGB, 宽高比)。透明底铺白，不铺黑。"""
    im = photos.flatten(im)
    ratio = im.width / im.height
    return im.convert("RGB").resize((SMALL, SMALL), Image.LANCZOS), ratio


def _prep(path):
    """读文件再缩到判定尺寸。留一个按路径的入口，测试和临时排查用。"""
    return _prep_image(photos.open_upright(path))


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

    # 两张图各读一次，人脸/手部直接复用，不再各开各的（以前一次判定要解码六遍）
    try:
        p_full = photos.open_upright(person_path)
        r_full = photos.open_upright(result_path)
        p, p_ratio = _prep_image(p_full)
        r, r_ratio = _prep_image(r_full)
    except Exception as e:
        v = blank_verdict("local", f"读图失败：{e}")
        v["error"] = str(e)
        return v

    checks = {}

    # ---- 脸 ----
    face_note = ""
    if models_dir and faces.load(models_dir):
        pa = faces.analyze_image(p_full)
        ra = faces.analyze_image(r_full)
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

    # ---- 手 ----
    if models_dir and hands.load(models_dir):
        ph = hands.analyze_image(p_full)
        rh = hands.analyze_image(r_full)
        if ph is None or rh is None:
            checks["hand_preserved"] = {
                "pass": None, "reason": hands.why() or "手部检测没跑起来",
            }
        elif ph["count"] == 0:
            checks["hand_preserved"] = {
                "pass": None, "reason": "原图里没检出手（被挡住或不在画面里），无法比对",
            }
        else:
            a, b = ph["count"], rh["count"]
            weak = rh["weak"]
            if a == b:
                confs = " / ".join(f"{h['conf']:.2f}" for h in rh["hands"]) or "—"
                checks["hand_preserved"] = {
                    "pass": True, "reason": f"原图 {a} 只手，结果 {b} 只（复核置信度 {confs}）",
                }
            elif b < a and weak:
                # 一级找到了框、二级不认。两种情况说法不一样：
                # 复核分很低 → 那个位置根本不是手（插兜、被挡住）；
                # 复核分中不溜 → 手在那里，但画糊了。
                low = min(w["conf"] for w in weak)
                if low < hands.POSE_CONF * 0.5:
                    checks["hand_preserved"] = {
                        "pass": False, "kind": "occluded",
                        "reason": f"原图 {a} 只手，结果里找不到手（{len(weak)} 处像手的位置"
                                  f"复核只有 {low:.2f}，多半是插兜或被挡住了）",
                        "counts": [a, b], "weak_conf": round(low, 3),
                    }
                else:
                    checks["hand_preserved"] = {
                        "pass": False, "kind": "mangled",
                        "reason": f"原图 {a} 只手，结果只有 {b} 只通过复核；另外 {len(weak)} 处"
                                  f"像手但形状不对（复核 {low:.2f}，门槛 {hands.POSE_CONF}），"
                                  "常见于手指粘连或变形",
                        "counts": [a, b], "weak_conf": round(low, 3),
                    }
            else:
                checks["hand_preserved"] = {
                    "pass": False, "kind": "extra" if b > a else "missing",
                    "reason": f"原图 {a} 只手，结果 {b} 只（{'少了' if b < a else '多了'} "
                              f"{abs(a - b)} 只）",
                    "counts": [a, b],
                }
    else:
        checks["hand_preserved"] = {
            "pass": None, "reason": hands.why() or "手部模型未加载",
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
    note = (f"本地质检：{judged}/{len(CHECKS)} 项可自动判定；"
            "文字水印不做自动检查，需人看一眼")
    return summarize(checks, "local", note=note, latency_s=time.time() - t0)
