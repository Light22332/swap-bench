"""配置接口：页面启动时读一次，高级设置里改。

GET 除了原样给出配置，还多报三个"模型在不在"——页面顶部据此显示能自动检查几项。
"""
import os

from ...core import config as app_config
from .. import state

FACE_MODELS = ("face_detection_yunet.onnx", "face_recognition_sface.onnx")
HAND_MODELS = ("palm_detection_mediapipe_2023feb.onnx",
               "handpose_estimation_mediapipe_2023feb.onnx")
PARSE_MODELS = ("config.json", "model.safetensors")


def _all_present(folder, names):
    return all(os.path.isfile(os.path.join(folder, f)) for f in names)


def handle_get(req):
    if req.path != "/api/config":
        return False
    cfg = state.get_config()
    models = app_config.models_dir(cfg)
    prep_cfg = app_config.section(cfg, "prep")
    req.json({
        "backend": app_config.backend(cfg),
        "judge": {"mode": "local",
                  "face_models": _all_present(models, FACE_MODELS),
                  "hand_models": _all_present(models, HAND_MODELS)},
        "prep": {"enabled": prep_cfg["enabled"],
                 "mode": prep_cfg["mode"],
                 "parse_model": _all_present(os.path.join(models, "segformer_b2_clothes"),
                                             PARSE_MODELS)},
        "max_attempts": app_config.section(cfg, "pipeline")["max_attempts"],
        "instruction": app_config.instruction(cfg),
        "negative": app_config.negative(cfg),
        "sampling": app_config.section(cfg, "sampling"),
    })
    return True


def handle_post(req):
    if req.path != "/api/config":
        return False
    state.update_config(req.body())
    req.json({"ok": True})
    return True
