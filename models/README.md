# 模型文件

这四个文件不进版本库（一共约 47MB）。跑之前下载到这里：

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

缺文件时程序不会崩，逐项降级：

- 缺人脸模型 → 「脸没变」「没有多余的人」两项返回 null
- 缺手部模型 → 「手还在」返回 null
- 页面顶部会标出当前能自动检查几项
