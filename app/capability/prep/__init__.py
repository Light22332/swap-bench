"""参考图整理：把人像解析和裁剪决策放在一起。

crop_garment 是对外入口：给一张服装图，返回该喂给生成模型的那一块。
"""
from .crop import crop_garment

__all__ = ["crop_garment"]
