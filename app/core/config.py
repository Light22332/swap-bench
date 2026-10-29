"""config.json 的读取、默认值、校验。

规矩：**缺键时的默认值只写在这里**。调用点直接取字段，不再写
`cfg.get("pipeline", {}).get("max_attempts", 2)`——那种写法的默认值和
config.json 会各走各的，`tools/check.py` 里有一条检查专门盯这个。
"""
import copy
import json
import os
import sys

from . import paths

DEFAULTS = {
    "cloud": {
        "base_url": "", "api_key": "", "model": "", "timeout": 120,
        "shape": "auto",            # auto / openai / dashscope：auto 看地址里有没有 aliyuncs.com
        "size": "",                 # 留空按竖版人像给 1024x1536（百炼给 1024*1024）
        "price_per_image": 0.0,     # 填了就把单张成本记进 GenResult.cost
    },
    "server": {"host": "127.0.0.1", "port": 8770},
    "backend": "comfyui",
    "models_dir": "models",
    "comfyui": {
        "base_url": "http://127.0.0.1:8188",
        "input_dir": "",          # ComfyUI 的 input 目录；装到哪台机器都不一样，留空就报错提示
        "min_vram_gb": 12,        # 显存低于这个数就别开跑，跑到一半 OOM 更难受；填 0 关掉
    },
    "prep": {
        "enabled": True,
        "mode": "parse",          # parse=人像解析找衣服框；fixed=老办法按比例裁
        "device": "cpu",          # 解析模型跑 CPU，省显存给 ComfyUI
    },
    "pipeline": {
        "max_attempts": 2,        # 普通轮次：第一次原样，之后追加修正约束
        "escape_attempts": 1,     # 降级轮：指令退回原文 + 抬 cfg
        "escape_cfg": 2.0,        # cfg=1 时负向提示词不生效，抬起来才有意义
    },
    "sampling": {
        "cfg": 1.0, "steps": 40, "resolution": 1024,
        "sampler": "euler", "scheduler": "simple",
    },
    "judge": {"mode": "local"},
    "instruction": "",
    "negative": "",
}

KEY_GROUPS = ("server", "prep", "pipeline", "sampling", "judge")


def _merge(base, over):
    """递归合并：用户配置盖在默认值上，字典往下走，其他类型直接替换。"""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(path=None):
    """读 config.json 并补全默认值。文件坏了直接抛，早失败比带着错配置跑好。

    项目根上如果有 config.local.json，就再盖一层上去——那是本机私有的，
    被 .gitignore 挡着，密钥这类东西放那儿才不会被推到公开仓库。
    """
    path = path or paths.CONFIG_FILE
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    cfg = _merge(DEFAULTS, raw)
    local = _local_file(path)
    if os.path.isfile(local):
        with open(local, encoding="utf-8") as f:
            cfg = _merge(cfg, json.load(f))
    cfg.setdefault("paths", {})
    cfg["paths"].setdefault("outputs", paths.OUTPUTS)
    cfg["paths"].setdefault("runs", paths.RUNS)
    cfg["paths"].setdefault("uploads", paths.UPLOADS)
    return cfg


def _local_file(path):
    return os.path.join(os.path.dirname(os.path.abspath(path)), "config.local.json")


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def section(cfg, name):
    """取一节配置，补上默认值。传进来的可以是残缺的配置字典（测试常这么干）。"""
    return _merge(DEFAULTS.get(name, {}), cfg.get(name) or {})


def backend(cfg):
    return cfg.get("backend") or DEFAULTS["backend"]


def instruction(cfg):
    return cfg.get("instruction") or DEFAULTS["instruction"]


def negative(cfg):
    return cfg.get("negative") or DEFAULTS["negative"]


def models_dir(cfg):
    d = cfg.get("models_dir") or DEFAULTS["models_dir"]
    return d if os.path.isabs(d) else os.path.join(paths.ROOT, d)


def runs_dir(cfg):
    return (cfg.get("paths") or {}).get("runs") or paths.RUNS


def outputs_dir(cfg):
    return (cfg.get("paths") or {}).get("outputs") or paths.OUTPUTS


def uploads_dir(cfg):
    return (cfg.get("paths") or {}).get("uploads") or paths.UPLOADS


def server_addr(cfg):
    s = section(cfg, "server")
    return s["host"], int(s["port"])


def comfyui_base(cfg):
    """ComfyUI 的地址。这一节不写进 DEFAULTS：它进 /api/config 的响应，多一个键就变形状。"""
    return ((cfg.get("comfyui") or {}).get("base_url")
            or "http://127.0.0.1:8188").rstrip("/")


def comfyui_dir(cfg):
    """ComfyUI 安装根目录（下面要有 ComfyUI/main.py）。桌面壳和预热脚本都用它。"""
    return (cfg.get("desktop") or {}).get("comfyui_dir") or ""


def comfyui_input_dir(cfg):
    """ComfyUI 的 input 目录：输入图要先放这儿，LoadImage 才读得到。"""
    return (cfg.get("comfyui") or {}).get("input_dir") or ""


def desktop_python(cfg):
    """起 ComfyUI 用哪个 python。没配就用当前这个解释器。"""
    return (cfg.get("desktop") or {}).get("python") or sys.executable


# 页面上能改的字段，点分路径。别的键一律不收：指令、采样、模型文件名这些
# 改错了软件直接跑不起来，不该出现在设置面板里。
EDITABLE = (
    "backend",
    "comfyui.base_url",
    "comfyui.input_dir",
    "cloud.base_url",
    "cloud.api_key",
    "cloud.model",
)

# 落盘时单独存 config.local.json 的键：这个值进版本库就等于把 key 公开了。
SECRETS = ("cloud.api_key",)


def _walk_get(data, key):
    cur = data
    for part in key.split("."):
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(part, "")
    return cur


def _walk_set(data, key, value):
    parts = key.split(".")
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def settings_snapshot(cfg):
    """设置面板要显示的那几项，按 EDITABLE 的顺序给。"""
    return {key: _walk_get(cfg, key) for key in EDITABLE}


def save_settings(values, path=None):
    """把改动写回配置文件，返回真正变了的键。

    密钥不落在 config.json 里（那个文件在版本库中），单独存 config.local.json，
    它被 .gitignore 挡着。其余字段先读原文再合，免得把默认值一股脑烤进文件。
    """
    path = path or paths.CONFIG_FILE
    local_path = _local_file(path)
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    local = {}
    if os.path.isfile(local_path):
        with open(local_path, encoding="utf-8") as f:
            local = json.load(f)

    changed = []
    for key in EDITABLE:
        if key not in values:
            continue
        val = values[key]
        val = val.strip() if isinstance(val, str) else str(val)
        bucket = local if key in SECRETS else raw
        if _walk_get(bucket, key) != val:
            _walk_set(bucket, key, val)
            changed.append(key)

    if changed:
        _write_json(path, raw)
        if local:
            _write_json(local_path, local)
    return changed
