# 模型文件

这些文件都不进版本库（一共约 149MB）。跑之前下载到这里：

## 人脸 + 手部（OpenCV Zoo，四个 onnx，约 44.7MB）

```bash
curl -L -o models/face_detection_yunet.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

curl -L -o models/face_recognition_sface.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx

curl -L -o models/palm_detection_mediapipe_2023feb.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/palm_detection_mediapipe/palm_detection_mediapipe_2023feb.onnx

curl -L -o models/handpose_estimation_mediapipe_2023feb.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/handpose_estimation_mediapipe/handpose_estimation_mediapipe_2023feb.onnx
```

Windows PowerShell：

```powershell
Invoke-WebRequest -Uri "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" -OutFile models/face_detection_yunet.onnx
Invoke-WebRequest -Uri "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx" -OutFile models/face_recognition_sface.onnx
Invoke-WebRequest -Uri "https://github.com/opencv/opencv_zoo/raw/main/models/palm_detection_mediapipe/palm_detection_mediapipe_2023feb.onnx" -OutFile models/palm_detection_mediapipe_2023feb.onnx
Invoke-WebRequest -Uri "https://github.com/opencv/opencv_zoo/raw/main/models/handpose_estimation_mediapipe/handpose_estimation_mediapipe_2023feb.onnx" -OutFile models/handpose_estimation_mediapipe_2023feb.onnx
```

后两个是 MediaPipe 的手部模型，官方只有 Python 包，这里是 OpenCV 转换好的 ONNX 版本，
直接用 `cv2.dnn` 跑，不用装 100MB 的 mediapipe（它会连带升级 numpy/protobuf，容易把 ComfyUI 环境搞坏）。

## 人像解析（SegFormer-B2，约 104MB）

参考图裁剪要用它认"人身上的衣服在哪"。

```bash
mkdir -p models/segformer_b2_clothes
B=https://huggingface.co/mattmdjaga/segformer_b2_clothes/resolve/main
for f in config.json preprocessor_config.json model.safetensors; do
  curl -L -o models/segformer_b2_clothes/$f $B/$f
done
```

Windows PowerShell：

```powershell
$d = "models/segformer_b2_clothes"; New-Item -ItemType Directory -Force $d | Out-Null
$b = "https://huggingface.co/mattmdjaga/segformer_b2_clothes/resolve/main/"
foreach ($f in "config.json","preprocessor_config.json","model.safetensors") {
  Invoke-WebRequest -Uri ($b + $f) -OutFile (Join-Path $d $f)
}
```

上不了 huggingface.co 的话，把域名换成 `https://hf-mirror.com`。
也可以直接用 `huggingface-cli download mattmdjaga/segformer_b2_clothes --local-dir models/segformer_b2_clothes`
（国内加 `HF_ENDPOINT=https://hf-mirror.com`）。

**协议**：模型来自 [mattmdjaga/segformer_b2_clothes](https://huggingface.co/mattmdjaga/segformer_b2_clothes)，
SegFormer-B2 在 ATR 人像解析集上微调，基座是 NVlabs/SegFormer，**权重沿用 NVIDIA Source Code License
（仅限非商业用途）**。自己用、放作品集没问题；要商用就换 rembg 的 `u2net_cloth_seg`（MIT），
`app/capability/prep/parse_clothes.py` 换个推理后端即可，接口不用动。

## 生成要用的权重（本仓库不带，得自己准备）

上面那 149MB 是**质检和裁剪**用的。真正出图的模型在 ComfyUI 那一侧，仓库里没有，
也不打算带：GB 级别，而且各有各的许可。四个文件名要和 `config.json` 的 `models` 段对上：

| `config.json` 里的键 | 文件 | 放哪 |
|---|---|---|
| `unet` | `qwen_image_2.1_int8_convrot.safetensors` | `ComfyUI/models/unet/`（新版叫 `diffusion_models/`，两个目录都会扫） |
| `clip` | `qwen3vl_8b_int8_convrot.safetensors` | `ComfyUI/models/text_encoders/`（老版本是 `clip/`） |
| `vae` | `qwen_image_2.1_vae_bf16.safetensors` | `ComfyUI/models/vae/` |
| `lora` | `Qwen-Image-2.1 NSW Image Edit.safetensors` | `ComfyUI/models/loras/` |

换成别的模型或改了文件名，只改 `config.json` 里这四行，代码一行都不用动。

显存：这套组合实测用到 15GB，所以开跑前会看一眼显卡。阈值写在 `config.json` 的
`comfyui.min_vram_gb`（不写就按默认 12，默认值见 `app/core/config.py`），低于它就拦下来，
不让它跑到一半 OOM。填 `0` 关掉这项检查。

## 缺文件时会怎样

程序不会崩，逐项降级：

- 缺人脸模型 → 「脸没变」「没有多余的人」两项返回 null
- 缺手部模型 → 「手还在」返回 null
- 缺人像解析模型 → 参考图退回按固定比例裁剪（`config.json` 里 `prep.mode` 设成 `fixed` 也是同样效果）
- 检验单里会写「本地质检：N/5 项可自动判定」，缺的模型对应那几项自动跳过
