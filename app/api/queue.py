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
from concurrent.futures import ThreadPoolExecutor

from ..core import log
from ..pipeline import run_job

logger = log.get("queue")

# 云端并发。以前每来一单开一个线程，没有上限：十几单一起进来就十几个线程
# 同时解图、跑判定，内存和 CPU 都跟着涨。云端慢的是对方，不需要开很多，
# 两个够跑，再多只是把本地 CPU 抢光。
CLOUD_WORKERS = 2

_local = queue.Queue()
_lock = threading.Lock()
_worker_started = False
_cloud_pool = None


def _pool():
    """云端用的线程池，第一次用时创建（测试可以不碰它）。"""
    global _cloud_pool
    with _lock:
        if _cloud_pool is None:
            _cloud_pool = ThreadPoolExecutor(max_workers=CLOUD_WORKERS,
                                             thread_name_prefix="cloud-job")
        return _cloud_pool


def submit(job, cfg, serial):
    """serial=True 进本地队列，False 交给云端线程池（最多 CLOUD_WORKERS 个同时跑）。"""
    if not serial:
        logger.info("任务 %s 走云端，交给线程池", job.id)
        _pool().submit(run_one, job, cfg)
        return
    job.state = "queued"
    logger.info("任务 %s 进本地队列", job.id)
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
        logger.info("任务 %s 开跑前被取消", job.id)
        return
    started = time.time()
    try:
        logger.info("任务 %s 开始跑", job.id)
        run_job(job, cfg)
    except Exception as e:
        logger.exception("任务 %s 跑挂了", job.id)
        traceback.print_exc()
        job.error = f"{type(e).__name__}: {e}"
        job.state = "error"
    else:
        logger.info("任务 %s 结束：%s，用时 %.1f 秒", job.id, job.state, time.time() - started)
