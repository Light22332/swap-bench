# 人脸模型

这两个文件不进版本库（一共约 37MB）。跑之前下载到这里：

```bash
curl -L -o models/face_detection_yunet.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

curl -L -o models/face_recognition_sface.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
```

Windows PowerShell：

```powershell
Invoke-WebRequest -Uri "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" -OutFile models/face_detection_yunet.onnx
Invoke-WebRequest -Uri "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx" -OutFile models/face_recognition_sface.onnx
```

缺文件时程序不会崩：质检降级为 2 项（衣服、背景），页面顶部会标出来。
