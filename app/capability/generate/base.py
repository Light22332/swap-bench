"""后端抽象：本地 ComfyUI 和云端 API 不是等价的东西，所以接口要把差异摊开。

差异（刻意不隐藏）：
- 延迟：本地几十秒起步且冷启动额外 ~30s；云通常几秒到十几秒
- 成本：本地 0（电费），云按张计费
- 失败模式：本地是显存爆/节点报错；云是限流/余额/审核拒绝
- 重试语义：本地重试几乎免费但慢；云重试花钱
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GenRequest:
    person_path: str          # 本地绝对路径
    garment_path: str         # 本地绝对路径
    instruction: str
    negative: str = ""
    cfg: float = 1.0
    steps: int = 40
    resolution: int = 1024
    seed: Optional[int] = None
    prefix: str = "swap"


@dataclass
class GenResult:
    ok: bool
    image_path: Optional[str] = None
    backend: str = ""
    model: str = ""
    latency_s: float = 0.0
    cost: float = 0.0
    seed: Optional[int] = None
    error: Optional[str] = None
    error_kind: Optional[str] = None   # vram / node_error / rate_limit / auth / network / unknown
    meta: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "ok": self.ok,
            "image_path": self.image_path,
            "backend": self.backend,
            "model": self.model,
            "latency_s": round(self.latency_s, 2),
            "cost": self.cost,
            "seed": self.seed,
            "error": self.error,
            "error_kind": self.error_kind,
            "meta": self.meta,
        }


class BackendError(Exception):
    """带分类的失败，方便上层决定要不要重试。"""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
        self.message = message
