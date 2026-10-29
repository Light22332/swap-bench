"""config.json 的读取、默认值、校验。

规矩：**缺键时的默认值只写在这里**。调用点直接取字段，不再写
`cfg.get("pipeline", {}).get("max_attempts", 2)`——那种写法的默认值和
config.json 会各走各的，`tools/check.py` 里有一条检查专门盯这个。
"""
import copy
import json
import os

from . import paths

DEFAULTS = {
    "cloud": {"base_url": "", "api_key": "", "model": "", "timeout": 120},
    "server": {"host": "127.0.0.1", "port": 8770},
    "backend": "comfyui",
    "models_dir": "models",
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
    """读 config.json 并补全默认值。文件坏了直接抛，早失败比带着错配置跑好。"""
    path = path or paths.CONFIG_FILE
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    cfg = _merge(DEFAULTS, raw)
    cfg.setdefault("paths", {})
    cfg["paths"].setdefault("outputs", paths.OUTPUTS)
    cfg["paths"].setdefault("runs", paths.RUNS)
    cfg["paths"].setdefault("uploads", paths.UPLOADS)
    return cfg


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
