"""配置接口：页面启动时读一次。

页面不给用户改配置——这个软件面向的是完全不懂的人，能选对两张图就够了。
改指令、换后端这些事，直接编辑 config.json 或者走 POST 接口。

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
    if req.path == "/api/settings":
        snap = app_config.settings_snapshot(state.get_config())
        # 密钥不回传给页面：接口响应会进截图、日志、接口基线文件，一个都不该带上它
        snap["_api_key_set"] = bool(snap.get("cloud.api_key"))
        snap["cloud.api_key"] = ""
        req.json(snap)
        return True

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
    if req.path == "/api/settings":
        return _save_settings(req)
    if req.path != "/api/config":
        return False
    data = req.body()
    if not isinstance(data, dict):
        req.json({"error": "请求体要是一个 JSON 对象"}, 400)
        return True
    bad = _validate_patch(data)
    if bad:
        req.json({"error": bad}, 400)
        return True
    state.update_config(data)
    req.json({"ok": True})
    return True


def _validate_patch(data):
    """POST /api/config 只收这几个字段，先把类型看住，别把内存里的配置写坏。"""
    backend = data.get("backend")
    if backend is not None and backend not in ("comfyui", "cloud"):
        return "backend 只能是 comfyui 或 cloud"
    for key in ("instruction", "negative"):
        if key in data and not isinstance(data[key], str):
            return f"{key} 要是字符串"
    judge = data.get("judge")
    if judge is not None:
        if not isinstance(judge, dict):
            return "judge 要是一个对象"
        if judge.get("mode") is not None and not isinstance(judge["mode"], str):
            return "judge.mode 要是字符串"
    return ""


def _save_settings(req):
    """改地址这类设置：写进 config.json，立刻生效，不用重启。"""
    raw = req.body()
    if not isinstance(raw, dict):
        req.json({"error": "请求体要是一个 JSON 对象"}, 400)
        return True
    data = dict(raw)
    for key in ("cloud.api_key", "cloud.base_url"):
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            req.json({"error": f"{key} 要是字符串"}, 400)
            return True
    # 页面拿不到已存的密钥，所以留空一律当"不改"，免得一次保存把密钥抹掉
    if not (data.get("cloud.api_key") or "").strip():
        data.pop("cloud.api_key", None)

    backend = data.get("backend")
    if backend not in (None, "", "comfyui", "cloud"):
        req.json({"error": "后端只能是 comfyui 或 cloud"}, 400)
        return True

    now = app_config.settings_snapshot(state.get_config())
    will = data.get("backend") or backend or now["backend"]
    cloud_url = (data.get("cloud.base_url") or now["cloud.base_url"]).strip()
    if will == "cloud" and not cloud_url:
        req.json({"error": "要用云端后端，得先把云端地址填上（现在还是空的）"}, 400)
        return True

    changed = app_config.save_settings(data)
    state.load_config()
    req.json({"ok": True, "changed": changed,
              "backend": app_config.backend(state.get_config())})
    return True
