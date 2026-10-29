"""判定能力的入口：定义从 core.checks 来，实现从这里挑。

`make_judge(cfg)` 返回一个可调用的 judge，上层不用关心用的是哪套判定。
"""
from ..core import config as app_config
from ..core.checks import (CHECKS, CHECK_INDEX, DROPPED, blank_verdict, fix_clauses,
                           is_critical, summarize)
from . import faces, hands, rules

__all__ = ["CHECKS", "CHECK_INDEX", "DROPPED", "blank_verdict", "fix_clauses",
           "is_critical", "summarize", "faces", "hands", "rules", "make_judge"]


def make_judge(cfg):
    """返回 judge 函数。现在只有本地真判定（人脸 + 手部 + 结构）。"""
    models_dir = app_config.models_dir(cfg)

    def judge(person_path, result_path, garment_path=None):
        return rules.evaluate(person_path, result_path, garment_path,
                              models_dir=models_dir)

    judge.mode = "local"
    return judge
