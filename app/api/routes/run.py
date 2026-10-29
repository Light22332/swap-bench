"""提交任务：校验路径、探一下服务、丢进队列，立刻返回 job_id。

本地后端排成一队串行跑（ComfyUI 一次只跑一张图，见 queue.py 里的说明）；
云端后端直接并发。页面靠轮询 /api/job/{id} 拿进度。
"""
import os

from ...capability.generate import make_backend
from ...core import config as app_config
from ...core import paths
from ...pipeline import new_job
from .. import queue, state


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

    if app_config.backend(cfg) == "comfyui":
        bad = _preflight(cfg)
        if bad:
            req.json({"error": bad}, 400)
            return True

    job = new_job(person_full, glist, instruction, negative, cfg)
    state.add_job(job)
    busy = sum(1 for j in state.recent_jobs(50) if j.state in ("queued", "running"))
    queue.submit(job, cfg, serial=(app_config.backend(cfg) == "comfyui"))
    req.json({"ok": True, "job_id": job.id, "queued": busy})
    return True


def _preflight(cfg):
    """本地后端开跑之前该说的话，别等 LoadImage 报一串节点错误。

    返回一句话就表示拦下来；返回 None 表示可以跑。
    """
    input_dir = app_config.comfyui_input_dir(cfg)
    if not input_dir or not os.path.isdir(input_dir):
        return (f"ComfyUI 的收图目录不存在：{input_dir or '（没填）'}。"
                "到「设置」里改成 ComfyUI 的 input 目录，比如 …\\ComfyUI\\input。")

    min_vram = app_config.section(cfg, "comfyui")["min_vram_gb"]
    if not min_vram:
        return None

    stats = make_backend("comfyui", cfg).system_stats()
    if stats is None:
        return ("换装服务还没起来。先双击根目录的「预热.bat」，"
                "等它说「可以开始演示了」，再点一次开始。")
    devs = stats.get("devices") or []
    if devs:
        gb = (devs[0].get("vram_total") or 0) / (1024 ** 3)
        if 0 < gb < float(min_vram):
            return (f"这张显卡只有 {gb:.0f}GB 显存，这套模型要 {min_vram:.0f}GB 以上。"
                    "换张卡，或者到「设置」里改用云端。")
    return None
