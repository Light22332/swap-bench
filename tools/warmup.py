"""预热：把 ComfyUI 拉起来，再跑一张暖机图，让模型进显存。

  python tools/warmup.py              # 起来 + 暖机（演示前五分钟跑这个）
  python tools/warmup.py --no-warm    # 只确保 ComfyUI 在跑，不花一张图
  python tools/warmup.py --no-start   # ComfyUI 没起就报错，不去拉它

为什么要有这个：ComfyUI 加载模型是懒的，第一张图 90 秒里一大半是加载。
先跑一张把权重压进显存，之后每张回到 55-60 秒，现场就不用干等两分钟。

只用标准库：真正干活的 ComfyUI 用 config.json 里 desktop.python 那个解释器起，
这个脚本本身拿系统 python 就能跑。
"""
import argparse
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.capability.generate import GenRequest, make_backend  # noqa: E402
from app.core import config as app_config  # noqa: E402


def comfy_port(base):
    tail = base.rsplit(":", 1)
    if len(tail) != 2:
        return 8188
    return int(tail[1].split("/")[0])


def device_line(stats):
    """/system_stats 里第一块卡的名字和显存，用来确认跑在 GPU 上而不是 CPU。"""
    devs = (stats or {}).get("devices") or []
    if not devs:
        return ""
    d = devs[0]
    gb = (d.get("vram_total") or 0) / (1024 ** 3)
    return f"{d.get('name', '?')} · 显存 {gb:.0f}GB"


def pick_pair(person=None, garment=None):
    """找一对能用的图。优先 samples/（随仓库分发），其次 bench/（回归用，不进仓库）。"""
    if person and garment:
        return person, garment
    for name in ("samples", "bench"):
        box = os.path.join(ROOT, name)
        if not os.path.isdir(box):
            continue
        people = sorted(glob.glob(os.path.join(box, "*person*.jpg"))
                        + glob.glob(os.path.join(box, "*person*.png")))
        clothes = sorted(glob.glob(os.path.join(box, "*garment*.jpg")))
        if people and clothes:
            return person or people[0], garment or clothes[0]
    return None, None


def spawn_comfy(cfg, port):
    py = app_config.desktop_python(cfg)
    home = app_config.comfyui_dir(cfg)
    if not home:
        print("config.json 里没写 desktop.comfyui_dir，不知道 ComfyUI 装在哪。")
        print("先自己到 ComfyUI 目录里把它启动起来，再跑一次这个脚本。")
        return False
    main_py = os.path.join(home, "ComfyUI", "main.py")
    if not os.path.isfile(main_py):
        print(f"找不到 {main_py}")
        print(r"desktop.comfyui_dir 要指向安装根目录（下面直接有 ComfyUI\main.py 那一层）。")
        return False

    logs = os.path.join(ROOT, "logs")
    os.makedirs(logs, exist_ok=True)
    log_path = os.path.join(logs, "comfyui-warmup.log")
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    cmd = [py, "-s", main_py,
           "--windows-standalone-build",
           # 不加这个 ComfyUI 会自己去开浏览器，演示时多一个窗口很乱
           "--disable-auto-launch",
           "--port", str(port)]
    # DETACHED_PROCESS：这个脚本（或黑窗口）退出之后，ComfyUI 要接着活着，
    # 这样再双击「启动换装台」时它发现 8188 已经在跑，就不会起第二个。
    flags = 0x00000008 if os.name == "nt" else 0
    subprocess.Popen(cmd, cwd=home, stdout=log, stderr=subprocess.STDOUT,
                     creationflags=flags, close_fds=True)
    print(f"已拉起 ComfyUI：{py}")
    print(f"日志：{log_path}")
    return True


def wait_ready(backend, timeout, t0):
    last = 0.0
    while time.time() - t0 < timeout:
        stats = backend.system_stats(timeout=1.5)
        if stats is not None:
            return stats
        spent = time.time() - t0
        if spent - last >= 5:
            print(f"  等了 {spent:.0f} 秒…", flush=True)
            last = spent
        time.sleep(1.0)
    print(f"等了 {timeout:.0f} 秒还没就绪。看 logs/comfyui-warmup.log 里报了什么。")
    return None


def main():
    ap = argparse.ArgumentParser(description="预热 ComfyUI：起来 + 跑一张暖机图")
    ap.add_argument("--no-warm", action="store_true", help="只确保 ComfyUI 在跑，不跑暖机图")
    ap.add_argument("--no-start", action="store_true", help="ComfyUI 没起就报错，不去拉它")
    ap.add_argument("--timeout", type=float, default=180.0, help="等就绪的秒数，默认 180")
    ap.add_argument("--person", help="暖机用的人像，默认从 samples/ 里找")
    ap.add_argument("--garment", help="暖机用的衣服，默认从 samples/ 里找")
    args = ap.parse_args()

    cfg = app_config.load()
    backend = make_backend("comfyui", cfg)
    base = backend.base_url
    t0 = time.time()

    stats = backend.system_stats()
    if stats is None:
        if args.no_start:
            print(f"ComfyUI 没在 {base} 上跑，而且说了不去拉它（--no-start）。")
            return 1
        print(f"ComfyUI 没在 {base} 上跑，开始拉…")
        if not spawn_comfy(cfg, comfy_port(base)):
            return 1
        stats = wait_ready(backend, args.timeout, t0)
        if stats is None:
            return 1
    print(f"ComfyUI 就绪，用了 {time.time() - t0:.0f} 秒。{device_line(stats)}")

    if args.no_warm:
        print("没跑暖机图。第一张仍要等模型加载，大概 90 秒。")
        return 0

    person, garment = pick_pair(args.person, args.garment)
    if not person:
        print("samples/ 和 bench/ 里都没找到一对图，跳过暖机。")
        print("放两张进去（或加 --person / --garment）再跑一次。")
        return 0

    print(f"暖机：{os.path.basename(person)} + {os.path.basename(garment)}")
    t1 = time.time()
    res = backend.generate(GenRequest(
        person_path=person,
        garment_path=garment,
        instruction=app_config.instruction(cfg),
        negative=app_config.negative(cfg),
        prefix="warmup",
    ))
    if not res.ok:
        print(f"暖机失败（{res.error_kind}）：{res.error}")
        print("模型没下齐、显存被别的程序占了，都会长这样。看 models/README.md。")
        return 1

    spent = time.time() - t1
    try:
        os.remove(res.image_path)   # 暖机图不留在 outputs/ 里，免得混进检验单
    except OSError:
        pass

    print(f"暖机完成，{spent:.0f} 秒（含加载模型）。")
    print("可以开始演示了。后面每张会比这个数快不少，本机实测 55-60 秒。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
