"""提交任务：校验路径、起一个线程去跑，立刻返回 job_id。

任务在后台线程里跑，页面靠轮询 /api/job/{id} 拿进度。
"""
import os
import threading

from ...core import config as app_config
from ...core import paths
from ...pipeline import new_job, run_job
from .. import state


def handle_post(req):
    if req.path != "/api/run":
        return False

    data = req.body()
    person = data.get("person")
    garments = data.get("garments") or []
    if not person or not garments:
        req.json({"error": "需要 1 张人像和至少 1 张服装图"}, 400)
        return True

    person_full = paths.inside(person)
    if not person_full or not os.path.isfile(person_full):
        req.json({"error": f"找不到人像：{person}"}, 400)
        return True

    glist = []
    for g in garments:
        gp = g.get("path") if isinstance(g, dict) else g
        full = paths.inside(gp)
        if not full or not os.path.isfile(full):
            req.json({"error": f"找不到服装图：{gp}"}, 400)
            return True
        # 前端传了原始文件名就用它，否则退回磁盘名（带时间戳前缀，不好看）
        label = (g.get("name") if isinstance(g, dict) else None) or os.path.basename(gp)
        glist.append({"name": label, "path": full})

    cfg = state.config_snapshot()
    if data.get("backend"):
        cfg["backend"] = data["backend"]
    instruction = data.get("instruction") or app_config.instruction(cfg)
    negative = data.get("negative") or app_config.negative(cfg)

    job = new_job(person_full, glist, instruction, negative, cfg)
    state.add_job(job)
    threading.Thread(target=_run_guarded, args=(job, cfg), daemon=True).start()
    req.json({"ok": True, "job_id": job.id})
    return True


def _run_guarded(job, cfg):
    """后台线程里跑。抛异常也要落到 job 上，别让页面一直转圈。"""
    try:
        run_job(job, cfg)
    except Exception as e:
        import traceback
        traceback.print_exc()
        job.error = f"{type(e).__name__}: {e}"
        job.state = "error"
