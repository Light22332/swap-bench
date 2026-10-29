"""质检契约：有哪几项、怎么加权、多少分算过。

只有五项，因为只有这五项现在能真的判：
  脸没变 / 衣服换上了 / 手还在 / 背景没动 / 没有多余的人

文字水印判不了，所以不列进来充数——列了就必然是一排"—"，看起来像坏了。
这一点在页面提示和 README 里都写清楚了。

手这一项是"数得清"而不是"看得出好坏"：它只比原图和结果的手数，
手指有没有粘连它看不出来。名字就叫"手还在"，别把能力说得比实际大。

这里是纯数据加纯函数，不碰 IO、不加载模型。判定实现在 capability/judge/rules.py，
编排层从这里拿 CHECK_INDEX 判断"这一项是不是关键项"。
"""
import statistics

CHECKS = [
    {
        "key": "face_preserved", "label": "脸没变", "critical": True, "weight": 3.0,
        "fix": "图1人物的五官、脸型、肤色必须完全不变，不要画成另一个人",
    },
    {
        "key": "garment_applied", "label": "衣服换上了", "critical": True, "weight": 2.0,
        "fix": "必须把图1身上的衣服替换成图2的款式和颜色",
    },
    {
        "key": "hand_preserved", "label": "手还在", "critical": True, "weight": 2.0,
        "fix": "双手必须完整保留，位置和图1一致，每只手五指清楚，不要多出或减少手",
    },
    {
        "key": "background_preserved", "label": "背景没动", "critical": False, "weight": 1.0,
        "fix": "背景必须与图1完全一致，不要换成图2的背景",
    },
    {
        "key": "no_extra_person", "label": "没有多余的人", "critical": False, "weight": 1.0,
        "fix": "画面里只能有一个人，不要出现第二个人",
    },
]

CHECK_INDEX = {c["key"]: c for c in CHECKS}

# 判不了的项记在这里，免得以后被当成"已覆盖"：文字水印目前没有可信的本地做法。
DROPPED = ("文字/水印",)

PASS_SCORE = 0.75   # 加权得分下限；关键项任一不过，分数再高也不算通过


def blank_verdict(mode="local", note=""):
    return {
        "mode": mode,
        "note": note,
        "checks": {c["key"]: {"pass": None, "reason": ""} for c in CHECKS},
        "passed": False,
        "score": 0.0,
        "failures": [],
        "latency_s": 0.0,
        "error": None,
        "semantic_checked": False,
    }


def summarize(checks_result, mode, note="", latency_s=0.0, extra=None):
    """有判定结果就按权重打分；没判的项不计入，也不当成通过。"""
    failures, judged, total_w, hit_w = [], 0, 0.0, 0.0
    critical_failed = False

    for c in CHECKS:
        r = checks_result.get(c["key"], {})
        p = r.get("pass")
        if p is None:
            continue
        judged += 1
        total_w += c["weight"]
        if p is True:
            hit_w += c["weight"]
        else:
            failures.append(c["key"])
            if c["critical"]:
                critical_failed = True

    score = (hit_w / total_w) if total_w else 0.0
    passed = bool(judged and not critical_failed and score >= PASS_SCORE)

    out = {
        "mode": mode,
        "note": note,
        "checks": checks_result,
        "passed": passed,
        "score": round(score, 3),
        "failures": failures,
        "judged": judged,
        "latency_s": round(latency_s, 2),
        "error": None,
        "semantic_checked": mode == "local" and judged >= 3,
    }
    if extra:
        out.update(extra)
    return out


def is_critical(key):
    return bool(CHECK_INDEX.get(key, {}).get("critical"))


def fix_clauses(failures):
    """把失败项翻成能塞进提示词的一句约束，按 CHECKS 顺序去重。"""
    out = []
    for k in failures:
        c = CHECK_INDEX.get(k)
        if c and c["fix"] not in out:
            out.append(c["fix"])
    return out


def median(vals):
    return statistics.median(vals) if vals else 0.0
