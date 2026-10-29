"""单次换装烟测：直接对本地 ComfyUI 提交一张图，验证模型能力。

用法：
    python tools/smoke_test.py --person a.jpg --garment b.jpg --cfg 1 --out out1.png

设计说明：
- 图结构手写在 build_graph() 里，因为 UI 保存的 workflow 是 UI 格式，
  不能直接 POST 到 /prompt；这里只保留必要节点，方便后续参数化。
- images 是 Autogrow 输入（image_1..image_16），API 里用 "images.image_N" 平铺键。
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HOST = "http://127.0.0.1:8188"
COMFY_INPUT = r"D:\Comfyui\ComfyUI\input"

DEFAULT_PROMPT = (
    "图1中的人物保持脸部、发型、姿态、背景和光线完全不变，"
    "把人物身上的棕色长款羽绒服替换成图2中的暗红色长款羽绒服，"
    "保留长款廓形、蓬松质感、立领和口袋位置。"
    "图2只提供服装款式与颜色参考，不要复制图2里的人物。"
)
DEFAULT_NEGATIVE = "改变脸部, 改变发型, 改变姿势, 改变背景, 多余的人物, 水印, 文字"


def stage(name):
    """把本地图复制进 ComfyUI 的 input 目录，返回 ComfyUI 认识的文件名。"""
    dst = os.path.join(COMFY_INPUT, name)
    return dst


def build_graph(person_img, garment_img, prompt, negative, cfg, steps, seed, prefix,
                base_model="qwen_image_2.1_int8_convrot.safetensors",
                clip_name="qwen3vl_8b_int8_convrot.safetensors",
                vae_name="qwen_image_2.1_vae_bf16.safetensors",
                lora_name="Qwen-Image-2.1 NSW Image Edit.safetensors",
                lora_strength=1.0, resolution=1024):
    g = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": base_model, "weight_dtype": "default"}},
        "11": {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["1", 0], "lora_name": lora_name,
                          "strength_model": lora_strength}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": clip_name, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
        "6": {"class_type": "QwenImage21Cache",
              "inputs": {"model": ["11", 0], "device": "auto", "dtype": "default"}},
        "5": {"class_type": "TextEncodeQwenImage21",
              "inputs": {"clip": ["2", 0], "prompt": prompt, "negative_prompt": negative,
                         "vae": ["3", 0], "resolution": resolution}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["6", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "euler", "scheduler": "simple",
                         "positive": ["5", 0], "negative": ["5", 1],
                         "latent_image": ["5", 2], "denoise": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImageAdvanced",
              "inputs": {"images": ["8", 0], "filename_prefix": prefix,
                         "format": "png", "format.bit_depth": "16-bit",
                         "format.input_color_space": "sRGB"}},
    }
    if person_img:
        g["20"] = {"class_type": "LoadImage", "inputs": {"image": person_img}}
        g["5"]["inputs"]["images.image_1"] = ["20", 0]
    if garment_img:
        g["21"] = {"class_type": "LoadImage", "inputs": {"image": garment_img}}
        g["5"]["inputs"]["images.image_2"] = ["21", 0]
    return g


def post_prompt(graph):
    body = json.dumps({"prompt": graph, "client_id": uuid.uuid4().hex}).encode()
    req = urllib.request.Request(HOST + "/prompt", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        print("!! /prompt 拒绝 (HTTP %s)" % e.code, file=sys.stderr)
        try:
            print(json.dumps(json.loads(raw), ensure_ascii=False, indent=2), file=sys.stderr)
        except Exception:
            print(raw[:3000], file=sys.stderr)
        return None


def wait(pid, timeout=900, interval=3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(interval)
        hist = json.load(urllib.request.urlopen(f"{HOST}/history/{pid}", timeout=30))
        if pid in hist:
            return hist[pid], time.time() - t0
    return None, time.time() - t0


def fetch(filename, subfolder, out_path):
    q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": "output"})
    data = urllib.request.urlopen(f"{HOST}/view?{q}", timeout=120).read()
    with open(out_path, "wb") as f:
        f.write(data)
    return len(data)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", default="case1_person.jpg")
    ap.add_argument("--garment", default="case1_garment.jpg")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--negative", default=DEFAULT_NEGATIVE)
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--prefix", default="swap_test")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    # 把测试图复制进 ComfyUI input 目录
    src_dir = r"D:\找工作\项目\AI换装工作流\samples"
    for fn in (a.person, a.garment):
        src = os.path.join(src_dir, fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(COMFY_INPUT, fn))
            print("staged", fn)

    g = build_graph(a.person, a.garment, a.prompt, a.negative, a.cfg, a.steps, a.seed, a.prefix)
    print("nodes:", len(g))
    r = post_prompt(g)
    if not r:
        sys.exit(1)
    pid = r["prompt_id"]
    print("queued", pid, "| 队列位置", r.get("number"))
    h, dt = wait(pid)
    if not h:
        print("timeout")
        sys.exit(1)
    st = h.get("status", {})
    print("status:", st.get("status_str"), "| 耗时 %.1fs" % dt)
    if st.get("status_str") != "success":
        print(json.dumps(st, ensure_ascii=False)[:2000])
        sys.exit(1)
    out = a.out or os.path.join(r"D:\找工作\项目\AI换装工作流\outputs", a.prefix + ".png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    for node_out in h.get("outputs", {}).values():
        for img in node_out.get("images", []):
            n = fetch(img["filename"], img.get("subfolder", ""), out)
            print("saved", out, "%.1f KB" % (n / 1024))
