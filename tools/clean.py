"""清理跑图留下的垃圾：结果图、中间裁图、缩略图缓存、上传原图、ComfyUI input 的副本。

这些目录一直「只写不删」：跑一次多两张结果图 + 两张中间裁图 + 两份 ComfyUI input
副本，几十次之后 outputs/ 就几百 MB。这个工具按修改时间清理，默认只打印清单，
加 --apply 才真删；样本图（uploads/sample_*）和 ComfyUI input 里不是我们放的图不碰。

跑法：
    python tools/clean.py                 # 看看超过 7 天的有多少
    python tools/clean.py --days 3 --apply
"""
import argparse
import os
import stat
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core import config as app_config     # noqa: E402

# ComfyUI input 里只删我们自己拷进去的（comfyui.py 的 _stage 用这两个前缀）
STAGED_PREFIXES = ("src_person_", "src_garment_")
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def targets(cfg):
    """要清理的目录和规则。dir 为空就跳过（比如没配 ComfyUI input 目录）。"""
    out = app_config.outputs_dir(cfg)
    return [
        ("结果图", out, {"flat": True, "exts": IMG_EXTS}),
        ("中间裁图", os.path.join(out, "prep"), {"recursive": True}),
        ("缩略图缓存", os.path.join(out, ".thumbs"), {"recursive": True}),
        ("上传原图", app_config.uploads_dir(cfg), {"recursive": True, "skip": ("sample_",)}),
        ("ComfyUI input 副本", app_config.comfyui_input_dir(cfg),
         {"flat": True, "prefixes": STAGED_PREFIXES}),
    ]


def _files(root, rules):
    """列 root 下的普通文件（不跟符号链接，不做递归进符号链接目录）。"""
    if rules.get("recursive"):
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                yield os.path.join(dirpath, name)
    else:
        try:
            names = os.listdir(root)
        except OSError:
            return
        for name in names:
            path = os.path.join(root, name)
            if os.path.isfile(path):
                yield path


def _wanted(path, rules):
    base = os.path.basename(path)
    if any(base.startswith(p) for p in rules.get("skip", ())):
        return False
    if rules.get("prefixes") and not base.startswith(rules["prefixes"]):
        return False
    if rules.get("exts") and not base.lower().endswith(rules["exts"]):
        return False
    return True


def plan(roots, days=7.0, now=None):
    """算出该删哪些文件：[(种类, 路径, 字节数)]。只算，不删。"""
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    found = []
    for label, root, rules in roots:
        if not root or not os.path.isdir(root):
            continue
        for path in _files(root, rules):
            if not _wanted(path, rules):
                continue
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):     # 符号链接、管道之类一律不碰
                continue
            if st.st_mtime <= cutoff:
                found.append((label, path, st.st_size))
    return found


def remove(items):
    """按 plan() 的结果删文件，返回 (删掉几个, 释放多少字节, 失败列表)。"""
    removed = freed = 0
    failed = []
    for _label, path, size in items:
        try:
            os.remove(path)
        except OSError as e:
            failed.append((path, str(e)))
            continue
        removed += 1
        freed += size
    return removed, freed, failed


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


def main(argv=None):
    ap = argparse.ArgumentParser(description="清理跑图留下的中间文件")
    ap.add_argument("--days", type=float, default=7.0,
                    help="只清修改时间早于这么多天的（默认 7）")
    ap.add_argument("--apply", action="store_true", help="真删；不加只打印清单")
    args = ap.parse_args(argv)

    cfg = app_config.load()
    roots = targets(cfg)
    items = plan(roots, days=args.days)
    if not items:
        print(f"没有超过 {args.days:g} 天的可清文件。")
        return 0

    by_kind = {}
    for label, path, size in items:
        agg = by_kind.setdefault(label, [0, 0])
        agg[0] += 1
        agg[1] += size
    total = sum(size for _l, _p, size in items)
    for label, (count, size) in by_kind.items():
        print(f"  {label}: {count} 个，{human(size)}")
    print(f"合计 {len(items)} 个文件，{human(total)}（超过 {args.days:g} 天）")

    if not args.apply:
        print("只是看看。要真删，加 --apply。")
        return 0

    removed, freed, failed = remove(items)
    print(f"删掉 {removed} 个，释放 {human(freed)}。")
    for path, err in failed:
        print(f"  删不掉 {path}：{err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
