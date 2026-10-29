"""运行期的共享状态：配置快照 + 在跑的任务表。

进程内唯一，靠这把锁串起来。任务跑完后仍留在内存里，重启后由 history 从
JSONL 还原，所以这里不做持久化。
"""
import json
import threading
import time

from ..core import config as app_config

CONFIG = {}
CONFIG_LOCK = threading.Lock()

JOBS = {}
JOBS_LOCK = threading.Lock()


def load_config():
    """启动时读一次 config.json。之后可以用 POST /api/config 改。"""
    global CONFIG
    cfg = app_config.load()
    with CONFIG_LOCK:
        CONFIG = cfg
    return cfg


def get_config():
    with CONFIG_LOCK:
        return CONFIG


def config_snapshot():
    """给一次任务用的配置副本，避免任务中途被改。"""
    with CONFIG_LOCK:
        return json.loads(json.dumps(CONFIG))


def update_config(data):
    """只接受几个白名单字段，其余忽略。"""
    with CONFIG_LOCK:
        for k in ("backend", "instruction", "negative"):
            if k in data:
                CONFIG[k] = data[k]
        if isinstance(data.get("judge"), dict):
            CONFIG.setdefault("judge", {}).update(data["judge"])


def add_job(job):
    with JOBS_LOCK:
        JOBS[job.id] = job


def get_job(jid):
    with JOBS_LOCK:
        return JOBS.get(jid)


def recent_jobs(limit=20):
    with JOBS_LOCK:
        return sorted(JOBS.values(), key=lambda j: -j.started)[:limit]


def cancel_job(jid):
    """给一个正在跑的任务打叫停标记。

    立刻返回，但真正停下来要等当前这一轮跑完：已经在 ComfyUI 里生成的那张没法中断
    （硬中断会污染 QwenImage21Cache，见 README 坑五）。还在排队的那单可以当场划掉。
    """
    job = get_job(jid)
    if job is None:
        return None
    if job.state == "queued":
        job.state = "cancelled"
        job.finished = time.time()
        return "queued"
    job.cancel_requested = True
    return "running"
