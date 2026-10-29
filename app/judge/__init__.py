from .base import CHECKS, CHECK_INDEX, DROPPED, blank_verdict, fix_clauses, summarize
from . import faces, hands, rules

__all__ = ["CHECKS", "CHECK_INDEX", "DROPPED", "blank_verdict", "fix_clauses",
           "summarize", "faces", "hands", "rules", "make_judge"]


def make_judge(cfg):
    """返回 judge 函数。现在默认就是本地真判定（人脸 + 结构）。"""
    import os
    models_dir = cfg.get("models_dir") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "models")
    if not os.path.isabs(models_dir):
        models_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            models_dir)

    def judge(person_path, result_path, garment_path=None):
        return rules.evaluate(person_path, result_path, garment_path,
                              models_dir=models_dir)

    judge.mode = "local"
    return judge
