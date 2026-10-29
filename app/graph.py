"""把一次换装请求翻译成 ComfyUI 的 API 格式图。

为什么手写而不是从 UI 的 workflow.json 转：
UI 保存的图带 pos/size/links，不能直接 POST 到 /prompt；而这个项目需要
按次覆盖 prompt / 输入图 / seed / cfg，手写一张最小图更可控，也更容易读。

TextEncodeQwenImage21 的 images 是 Autogrow 输入（image_1..image_16），
在 API 里用 "images.image_N" 这种平铺键，值是该图所在节点的 [node_id, slot]。
"""


def build_swap_graph(person_img, garment_img, prompt, negative, cfg, steps, seed,
                     resolution, models, prefix="swap"):
    """返回可直接 POST 给 /prompt 的 dict。

    person_img / garment_img 是 ComfyUI input 目录下的文件名，不是绝对路径。
    """
    g = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": models["unet"], "weight_dtype": "default"},
        },
        "11": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["1", 0],
                "lora_name": models["lora"],
                "strength_model": models.get("lora_strength", 1.0),
            },
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": models["clip"], "type": "qwen_image", "device": "default"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": models["vae"]}},
        "6": {
            "class_type": "QwenImage21Cache",
            "inputs": {"model": ["11", 0], "device": "auto", "dtype": "default"},
        },
        "5": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {
                "clip": ["2", 0],
                "prompt": prompt,
                "negative_prompt": negative,
                "vae": ["3", 0],
                "resolution": resolution,
            },
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["6", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "positive": ["5", 0],
                "negative": ["5", 1],
                "latent_image": ["5", 2],
                "denoise": 1,
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {
            "class_type": "SaveImageAdvanced",
            "inputs": {
                "images": ["8", 0],
                "filename_prefix": prefix,
                "format": "png",
                "format.bit_depth": "16-bit",
                "format.input_color_space": "sRGB",
            },
        },
    }

    if person_img:
        g["20"] = {"class_type": "LoadImage", "inputs": {"image": person_img}}
        g["5"]["inputs"]["images.image_1"] = ["20", 0]
    if garment_img:
        g["21"] = {"class_type": "LoadImage", "inputs": {"image": garment_img}}
        g["5"]["inputs"]["images.image_2"] = ["21", 0]
    return g
