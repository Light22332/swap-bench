"""契约层：整个项目围着这几个东西转，它们不知道算法、不知道 HTTP。

  checks  五项检查的定义、加权、失败项翻成约束
  config  config.json 的读取与默认值（缺键时的默认值只在这里）
  log     日志：落到 runs/server.log，按大小轮转
  paths   项目内路径的唯一定义处
  photos  读图（EXIF 转正）与上传归一化
  store   JSONL 证据层
  thumbs  显示用的缩略图（按原图 + 宽度缓存）
"""
from . import checks, config, log, paths, photos, store, thumbs

__all__ = ["checks", "config", "log", "paths", "photos", "store", "thumbs"]
