"""契约层：整个项目围着这几个东西转，它们不知道算法、不知道 HTTP。

  checks  五项检查的定义、加权、失败项翻成约束
  config  config.json 的读取与默认值（缺键时的默认值只在这里）
  paths   项目内路径的唯一定义处
  store   JSONL 证据层
"""
from . import checks, config, paths, store

__all__ = ["checks", "config", "paths", "store"]
