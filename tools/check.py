"""一键检查：编译、单测、判定冒烟。不需要 GPU，也不需要 ComfyUI 在跑。

  python tools/check.py            # 全跑
  python tools/check.py --fast     # 跳过冒烟（只编译 + 单测）

设计上是给重构用的闸门：每改一步就跑一次，绿了再继续。
退出码非零表示有检查没过。
"""
import argparse
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESULTS = []


def report(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail and not ok else ""))


def py_files():
    out = []
    for base in ("app", "tools"):
        for dirpath, _, files in os.walk(os.path.join(ROOT, base)):
            out += [os.path.join(dirpath, f) for f in files if f.endswith(".py")]
    out.append(os.path.join(ROOT, "run.py"))
    return sorted(out)


def step_compile():
    print("编译")
    files = [f for f in py_files() if os.path.isfile(f)]
    r = subprocess.run([sys.executable, "-m", "py_compile"] + files,
                       capture_output=True, text=True)
    report("py_compile 全部模块", r.returncode == 0, r.stderr.strip()[:400])


def step_tests():
    print("单测")
    pattern = os.path.join(ROOT, "tools", "test_*.py")
    files = sorted(glob.glob(pattern)) + sorted(glob.glob(os.path.join(ROOT, "tools", "tests", "test_*.py")))
    if not files:
        report("单测", False, "tools/ 下没有 test_*.py")
        return
    for f in files:
        t0 = time.time()
        r = subprocess.run([sys.executable, f], capture_output=True, text=True, cwd=ROOT)
        name = os.path.relpath(f, ROOT) + f"（{time.time() - t0:.1f}s）"
        report(name, r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1] if (r.returncode) else "")


def step_smoke():
    """拿三张现成的图跑一遍判定，确认模型能加载、判定不炸。"""
    print("判定冒烟")
    from app.judge import make_judge
    judge = make_judge({"models_dir": os.path.join(ROOT, "models")})
    person = os.path.join(ROOT, "samples", "case1_person.jpg")
    results = sorted(glob.glob(os.path.join(ROOT, "outputs", "*.png")))
    if not os.path.isfile(person):
        report("判定冒烟", True, "没有 samples 目录，跳过")
        return
    if not results:
        report("判定冒烟", True, "没有 outputs 图，跳过")
        return
    for img in results[:3]:
        try:
            v = judge(person, img, None)
            ok = isinstance(v.get("score"), float) and "checks" in v
            report(f"判定 {os.path.basename(img)[:36]}", ok,
                   "" if ok else str(v)[:200])
        except Exception as e:
            report(f"判定 {os.path.basename(img)[:36]}", False, f"{type(e).__name__}: {e}")


def step_imports():
    """依赖方向：core 不许 import 上层，任何模块不许 import api。"""
    print("依赖方向")
    bad = []
    for f in py_files():
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        if not rel.startswith("app/") or not os.path.isfile(f):
            continue
        src = open(f, encoding="utf-8", errors="ignore").read()
        if "from .api" in src or "from app.api" in src:
            if not rel.startswith("app/api/"):
                bad.append(f"{rel} 引用了 api")
        if rel.startswith("app/core/"):
            for mod in ("capability", "pipeline", "api"):
                if f"app.{mod}" in src or f"from .{mod}" in src:
                    bad.append(f"{rel} 引用了 {mod}")
    report("core/api 单向依赖", not bad, "；".join(bad)[:400])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="跳过判定冒烟")
    args = ap.parse_args()
    t0 = time.time()
    step_compile()
    step_imports()
    step_tests()
    if not args.fast:
        step_smoke()
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过，用时 {time.time() - t0:.1f}s")
    if failed:
        print("没过：" + "、".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
