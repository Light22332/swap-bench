"""历史回放：把以前的任务重新判一遍，和记录里的结果逐项对比。

重构期间的底气来自这里。历史 JSONL 是旧代码写的，重跑是新代码，差异分三类：

  新增项  —— 记录里没有、现在能判的（比如后来才加的手部检查），预期内
  消失项  —— 记录里有、现在判不了的（模型缺失、图片被删），要解释
  翻转项  —— 以前判过的项现在判反了，这类必须为零或者逐条说清

用法：
  python tools/replay.py                 # 全部历史
  python tools/replay.py --job 6e8f77   # 只回放一个
  python tools/replay.py --quiet         # 只打印汇总
"""
import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.capability.judge import make_judge            # noqa: E402


def read_job(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return recs


def attempts_of(recs):
    """把 generate / judge 记录按 (case, attempt) 配成对。"""
    gen, judged = {}, {}
    for r in recs:
        key = (r.get("case"), r.get("attempt"))
        if r.get("stage") == "generate" and r.get("ok"):
            gen[key] = r
        elif r.get("stage") == "judge":
            judged[key] = r
    return [(key, gen.get(key), j) for key, j in sorted(judged.items()) if gen.get(key)]


def compare(old, new):
    """按检查项比 pass 值。返回 (新增, 消失, 翻转)。"""
    old_checks = old.get("checks") or {}
    new_checks = new.get("checks") or {}
    added = [k for k in new_checks if k not in old_checks]
    missing = [k for k in old_checks if k not in new_checks]
    flipped = []
    for k in old_checks:
        if k in new_checks:
            a, b = old_checks[k].get("pass"), new_checks[k].get("pass")
            if a is not None and b is not None and a != b:
                flipped.append((k, a, b, new_checks[k].get("reason", "")))
    return added, missing, flipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", help="只回放某个 job id（前缀匹配）")
    ap.add_argument("--quiet", action="store_true", help="只打印汇总")
    args = ap.parse_args()

    judge = make_judge({"models_dir": os.path.join(ROOT, "models")})
    files = sorted(glob.glob(os.path.join(ROOT, "runs", "*.jsonl")))
    if args.job:
        files = [f for f in files if os.path.basename(f).startswith(args.job)]
    if not files:
        print("没有可回放的任务")
        return 1

    total = {"ok": 0, "added": 0, "missing": 0, "flipped": 0, "skipped": 0}
    flipped_detail = []

    for f in files:
        jid = os.path.basename(f)[:-6]
        recs = read_job(f)
        person = next((r.get("person") for r in recs if r.get("stage") == "job_start"), None)
        pairs = attempts_of(recs)
        if not pairs:
            total["skipped"] += 1
            if not args.quiet:
                print(f"{jid}  跳过：没有可复判的尝试")
            continue
        if not person or not os.path.isfile(person):
            total["skipped"] += 1
            if not args.quiet:
                print(f"{jid}  跳过：人像已不在磁盘上")
            continue

        if not args.quiet:
            print(f"{jid}  人像 {os.path.basename(person)}")
        for (case, attempt), gen, old in pairs:
            img = gen.get("image")
            if not img or not os.path.isfile(img):
                total["skipped"] += 1
                if not args.quiet:
                    print(f"  第 {case} 件第 {attempt} 次：结果图已删除，跳过")
                continue
            new = judge(person, img, None)
            added, missing, flipped = compare(old, new)
            total["ok"] += 1
            total["added"] += len(added)
            total["missing"] += len(missing)
            total["flipped"] += len(flipped)
            for k, a, b, why in flipped:
                flipped_detail.append(f"{jid} 第 {case} 件第 {attempt} 次 · {k}: {a} → {b}  {why}")
            if not args.quiet:
                flag = "翻转" if flipped else ("新增" if added else "一致")
                print(f"  第 {case} 件第 {attempt} 次：{flag}  "
                      f"新增 {len(added)} 消失 {len(missing)} 翻转 {len(flipped)}")
                for k in added:
                    print(f"      + {k} = {new['checks'][k].get('pass')}")
                for k in missing:
                    print(f"      - {k}")
                for k, a, b, why in flipped:
                    print(f"      ! {k}: {a} → {b}  {why}")

    print("\n汇总：复判 {ok} 次尝试，新增 {added} 项，消失 {missing} 项，翻转 {flipped} 项，跳过 {skipped} 处".format(**total))
    if flipped_detail:
        print("翻转明细：")
        for line in flipped_detail:
            print("  " + line)
    return 1 if total["flipped"] else 0


if __name__ == "__main__":
    sys.exit(main())
