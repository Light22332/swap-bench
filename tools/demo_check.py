"""演示前自检：五分钟里把「现场会不会翻车」的几件事先查一遍。

  python tools/demo_check.py          # 默认全查
  python tools/demo_check.py --no-net # 只查本地文件（网络不通的场合）

查五件事：网页服务在不在、ComfyUI 在不在且认得显卡、生成模型齐不齐、
质检模型齐不齐、示例图在不在。全过退出码 0，有 ❌ 退出码 1。

和 tools/check.py 的区别：check.py 是给 CI 跑代码检查的，不等模型不等服务；
这个脚本反过来，只关心演示现场那台机器准备好了没有，不跑任何生成。
"""
import argparse
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GEN_FILES = {
    "diffusion_models": "unet",
    "text_encoders": "clip",
    "vae": "vae",
    "loras": "lora",
}
JUDGE_FILES = [
    ("models", "face_detection_yunet.onnx", "人脸检测"),
    ("models", "face_recognition_sface.onnx", "人脸识别"),
    ("models", "handpose_estimation_mediapipe_2023feb.onnx", "手部关键点"),
    ("models", "palm_detection_mediapipe_2023feb.onnx", "手掌检测"),
    ("models/segformer_b2_clothes", "model.safetensors", "衣服解析"),
]
SAMPLES = [
    "samples/demo_person_a.jpg",
    "samples/demo_garment_1.jpg",
    "samples/demo_garment_2.jpg",
]


def load_config():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    local = os.path.join(ROOT, "config.local.json")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
    return cfg


def get_json(url, timeout=4.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_code(url, timeout=4.0):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def human(n):
    return f"{n / 1024 ** 3:.0f} GB" if n else "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-net", action="store_true", help="跳过网络检查")
    args = ap.parse_args()
    cfg = load_config()
    host = (cfg.get("server") or {}).get("host", "127.0.0.1")
    port = (cfg.get("server") or {}).get("port", 8770)
    base = f"http://{host}:{port}"
    comfy = (cfg.get("comfyui") or {}).get("base_url", "http://127.0.0.1:8188").rstrip("/")

    rows = []  # (ok, title, detail)

    # 1) 网页服务
    if args.no_net:
        rows.append((True, "网页服务", f"跳过（--no-net，地址 {base}）"))
    else:
        try:
            status, body = get_code(base + "/")
            ok = status == 200 and b"<!doctype html" in body.lower()
            rows.append((ok, "网页服务", f"{base} 返回 {status}，{len(body)} 字节"))
        except Exception as e:  # noqa: BLE001 - 自检脚本，任何异常都当成没起来
            rows.append((False, "网页服务", f"{base} 连不上（{e}）；先跑 python run.py"))

    # 2) ComfyUI + 显卡
    if args.no_net:
        rows.append((True, "ComfyUI", f"跳过（--no-net，地址 {comfy}）"))
    else:
        try:
            stats = get_json(comfy + "/system_stats")
            devs = (stats or {}).get("devices") or []
            if devs:
                d = devs[0]
                rows.append((True, "ComfyUI", f"{comfy} 在跑，显卡 {d.get('name', '?')} / {human(d.get('vram_total'))}"))
            else:
                rows.append((False, "ComfyUI", f"{comfy} 在跑但没认出显卡，可能是 CPU 模式，生成会很慢"))
        except Exception as e:  # noqa: BLE001
            rows.append((False, "ComfyUI", f"{comfy} 连不上（{e}）；先跑 预热.bat 或 python tools/warmup.py"))

    # 3) 生成模型（ComfyUI 的 models 目录）
    models_root = os.path.join(os.path.dirname(os.path.abspath((cfg.get("comfyui") or {}).get("input_dir", ""))), "models")
    names = cfg.get("models") or {}
    for sub, key in GEN_FILES.items():
        want = names.get(key)
        if not want:
            continue
        path = os.path.join(models_root, sub, want)
        rows.append((os.path.isfile(path), f"生成模型 {sub}", want if os.path.isfile(path) else f"缺 {path}"))

    # 4) 质检模型
    for sub, name, label in JUDGE_FILES:
        path = os.path.join(ROOT, sub, name)
        rel = os.path.join(sub, name).replace("\\", "/")
        rows.append((os.path.isfile(path), f"质检模型·{label}", rel if os.path.isfile(path) else f"缺 {rel}（见 models/README.md）"))

    # 5) 示例图
    for rel in SAMPLES:
        path = os.path.join(ROOT, rel)
        rows.append((os.path.isfile(path), "示例图", rel if os.path.isfile(path) else f"缺 {rel}"))

    bad = 0
    for ok, title, detail in rows:
        mark = "✅" if ok else "❌"
        if not ok:
            bad += 1
        print(f"{mark} {title:<12} {detail}")
    print()
    if bad:
        print(f"有 {bad} 项没过——先把上面标 ❌ 的修好，再演示。")
        return 1
    print("都齐了。建议再点一次「载入示例看看」，确认结果页能打开。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
