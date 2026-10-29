"""从几轮尝试里挑一张交出去。

规则是被真实事故定下来的：先看有没有通过，再看分数。原来"通过了就用最后一次"，
结果返工把好图改成了坏图还盖了通过章。同分取靠前的那次——先跑出来的更可信。
"""


def best(tried):
    """tried: [{"verdict": ..., "attempt": ...}]，返回最好那张的下标；空列表返回 -1。"""
    if not tried:
        return -1

    def key(i):
        v = tried[i]["verdict"] or {}
        return (bool(v.get("passed")), float(v.get("score") or 0.0))

    return max(range(len(tried)), key=key)


def case_state(passed, attempts):
    """一件衣服最终的状态。reworked = 试了不止一次、最后还是没过。"""
    if passed:
        return "passed"
    return "reworked" if attempts > 1 else "rejected"
