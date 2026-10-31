"""清理工具的测试：只清该清的，样本图和别人的文件一个不碰。

跑法：python tools/tests/test_clean.py
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import clean                                  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def touch(path, mtime):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * 10)
    os.utime(path, (mtime, mtime))
    return path


def main():
    print("清理工具：按天数、按目录、按前缀")
    now = time.time()
    old = now - 10 * 86400
    new = now - 1 * 86400

    tmp = tempfile.mkdtemp(prefix="swap_clean_")
    out = os.path.join(tmp, "outputs")
    uploads = os.path.join(tmp, "uploads")
    comfy = os.path.join(tmp, "comfy_input")

    old_result = touch(os.path.join(out, "old.png"), old)
    touch(os.path.join(out, "new.png"), new)                      # 没超过 7 天，留着
    touch(os.path.join(out, "readme.txt"), old)                   # 结果图目录只清图片
    old_prep = touch(os.path.join(out, "prep", "old.png"), old)
    touch(os.path.join(out, "prep", "new.png"), new)
    old_prep_sub = touch(os.path.join(out, "prep", "sub", "deep.png"), old)   # 递归
    old_thumb = touch(os.path.join(out, ".thumbs", "abc.webp"), old)
    touch(os.path.join(uploads, "sample_demo_person_a.jpg"), old)  # 样本图，绝不删
    old_upload = touch(os.path.join(uploads, "1030_old.jpg"), old)
    touch(os.path.join(uploads, "1030_new.jpg"), new)
    old_stage1 = touch(os.path.join(comfy, "src_person_old.jpg"), old)
    old_stage2 = touch(os.path.join(comfy, "src_garment_old.jpg"), old)
    touch(os.path.join(comfy, "keep_me.png"), old)                # 不是我们放的，留着

    roots = [
        ("结果图", out, {"flat": True, "exts": clean.IMG_EXTS}),
        ("中间裁图", os.path.join(out, "prep"), {"recursive": True}),
        ("缩略图缓存", os.path.join(out, ".thumbs"), {"recursive": True}),
        ("上传原图", uploads, {"recursive": True, "skip": ("sample_",)}),
        ("ComfyUI input 副本", comfy, {"flat": True, "prefixes": clean.STAGED_PREFIXES}),
    ]

    items = clean.plan(roots, days=7, now=now)
    got = {path for _label, path, _size in items}
    want = {old_result, old_prep, old_prep_sub, old_thumb, old_upload, old_stage1, old_stage2}
    check("只清超过天数的文件", got == want, f"多={got - want} 少={want - got}")
    check("样本图不删", os.path.exists(os.path.join(uploads, "sample_demo_person_a.jpg")))
    check("结果图目录里的非图片不删", os.path.join(out, "readme.txt") not in got)
    check("ComfyUI input 里别人的图不删", os.path.join(comfy, "keep_me.png") not in got)
    check("中间裁图递归清", old_prep_sub in got)
    check("没到天数的不清", os.path.join(out, "new.png") not in got)
    check("清单里带大小", all(size == 10 for _l, _p, size in items), str(items))

    # 只算不删：plan() 之后文件都还在
    check("plan 不动文件", all(os.path.exists(p) for _l, p, _s in items))

    removed, freed, failed = clean.remove(items)
    check("remove 删掉 7 个", removed == 7, str(removed))
    check("remove 统计字节数", freed == 70, str(freed))
    check("remove 无失败", failed == [], str(failed))
    check("删完就没了", all(not os.path.exists(p) for _l, p, _s in items))
    check("没点名的还在", os.path.exists(os.path.join(out, "new.png")))

    _removed, _freed, missing = clean.remove([("结果图", os.path.join(out, "gone.png"), 1)])
    check("删不存在的算失败", len(missing) == 1, str(missing))

    check("human 小数字", clean.human(500) == "500 B", clean.human(500))
    check("human KB", clean.human(2048) == "2.0 KB", clean.human(2048))
    check("human MB", clean.human(3 * 1024 * 1024) == "3.0 MB", clean.human(3 * 1024 * 1024))

    if FAILED:
        print(f"\n{len(FAILED)} 项失败：{FAILED}")
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
