"""统计回归报告里手部判定的失败分布。

  python tools/hand_stats.py                      # 默认 reports/hand-base.json
  python tools/hand_stats.py reports/base.json    # 旧报告也能读

读两样东西：报告里的 jobs 和 runs/<job>.jsonl 里的 judge 事件。
按「每一次尝试」统计，而不是按最终结果——首轮过没过，手部都要算进去。

输出：总尝试数、手部不过的比例、失败类型（missing/mangled/occluded/extra）、
按人像和按衣服的分布。只用标准库，不加载任何模型。
"""
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rows_from(report_path):
    report = json.load(open(report_path, encoding="utf-8"))
    rows = []
    for pair in report.get("pairs") or []:
        job = pair.get("job")
        if not job:
            continue
        path = os.path.join(ROOT, "runs", f"{job}.jsonl")
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8"):
            event = json.loads(line)
            if event.get("stage") != "judge":
                continue
            hand = (event.get("checks") or {}).get("hand_preserved") or {}
            rows.append({"job": job, "person": pair.get("person"), "garment": pair.get("garment"),
                         "attempt": event.get("attempt"), "mode": event.get("mode"),
                         "hand_pass": hand.get("pass"), "kind": hand.get("kind")})
    return rows


def show(rows):
    bad = [r for r in rows if r["hand_pass"] is False]
    print(f"尝试总数：{len(rows)}  手部不过：{len(bad)}（{len(bad) / max(1, len(rows)):.0%}）")
    print("失败类型：", dict(collections.Counter(r["kind"] or "unknown" for r in bad)) or "无")
    for field, title in (("garment", "按衣服"), ("person", "按人像")):
        table = collections.defaultdict(lambda: [0, 0])
        for r in rows:
            table[r[field]][0] += 1
            if r["hand_pass"] is False:
                table[r[field]][1] += 1
        print(f"{title}（尝试数 / 手部不过）:")
        for name, (total, failed) in sorted(table.items()):
            print(f"  {name:34s} {total:2d} / {failed}")


def main(argv):
    path = argv[1] if len(argv) > 1 else os.path.join(ROOT, "reports", "hand-base.json")
    show(rows_from(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
