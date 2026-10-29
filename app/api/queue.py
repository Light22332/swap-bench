"""任务队列：本地串行，云端并发。

为什么本地要串行：ComfyUI 自己一次也只执行一张图。两个任务同时进来并不会并行，
只会在 ComfyUI 的队列里交替——每个任务都要等另一个任务的图跑完，而这段等待被算进
它自己的耗时（实测单张从 56 秒涨到 150 秒），缓存节点也会被交替的输入打散再重算。
排成一队之后，每个任务拿到的是一张独占的卡。

云端没这个问题：每次生成就是一次独立的 HTTP 调用，慢的是对方；再排成一队只会让
总时间更长，所以云端直接并发跑。
"""
import queue
import threading
import time
import traceback

from ..pipeline import run_job

_local = queue.Queue()
_lock = threading.Lock()
_worker_started = False


def submit(job, cfg, serial):
    """serial=True 进本地队列，False 直接开线程（云端）。"""
    if not serial:
        threading.Thread(target=run_one, args=(job, cfg), daemon=True).start()
        return
    job.state = "queued"
    _local.put((job, cfg))
    _ensure_worker()


def _ensure_worker():
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True
    threading.Thread(target=_loop, daemon=True, name="job-queue").start()


def _loop():
    while True:
        job, cfg = _local.get()
        try:
            # 排队时间不算进这单的耗时：settle 之后再计时，页面上的秒数才对得上真跑的时长
            job.started = time.time()
            run_one(job, cfg)
        finally:
            _local.task_done()


def run_one(job, cfg):
    """跑一个任务。抛异常也要落到 job 上，别让页面一直转圈。"""
    if job.cancel_requested:
        job.state = "cancelled"
        job.finished = time.time()
        return
    try:
        run_job(job, cfg)
    except Exception as e:
        traceback.print_exc()
        job.error = f"{type(e).__name__}: {e}"
        job.state = "error"
