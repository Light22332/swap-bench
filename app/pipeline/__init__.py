"""编排层：一条任务怎么从两张图走到一张合格的图。

  policy  要不要继续、用什么打法（纯函数）
  select  最后挑哪张（纯函数）
  runner  串起来跑，负责 IO 和记账
"""
from ..core.models import Job, new_job
from . import policy, select
from .runner import run_job

__all__ = ["Job", "new_job", "run_job", "policy", "select"]
