"""取消语义的测试：排队里叫停就真的不跑了，跑起来的叫停只打标记。

为什么单独测这个：/api/cancel 对排队任务回「已经从队列里划掉了，不会再开跑」，
这句话对不对全看 state.cancel_job 有没有同时打上 cancel_requested——队列线程
（queue.run_one）只看这个标记。曾经漏过，回话说划掉了，实际照跑。

跑法：python tools/tests/test_queue.py
"""
import contextlib
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.api import queue as job_queue       # noqa: E402
from app.api import state                    # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


class FakeJob:
    def __init__(self, jid, st="queued"):
        self.id = jid
        self.state = st
        self.cancel_requested = False
        self.started = 0.0
        self.finished = None
        self.error = None


def keep(job):
    state.add_job(job)
    return job


def drop(job):
    with state.JOBS_LOCK:
        state.JOBS.pop(job.id, None)


def test_cancel_queued():
    job = keep(FakeJob("t-queued"))
    try:
        how = state.cancel_job(job.id)
        check("排队任务取消返回 queued", how == "queued", f"got={how}")
        check("排队任务打上 cancel_requested", job.cancel_requested is True)
        check("排队任务状态变 cancelled", job.state == "cancelled", job.state)
    finally:
        drop(job)


def test_queued_cancel_skips_run():
    called = []
    orig = job_queue.run_job
    job_queue.run_job = lambda j, cfg: called.append(j.id)
    job = keep(FakeJob("t-skip"))
    try:
        state.cancel_job(job.id)
        job_queue.run_one(job, {})
        check("排队取消后队列不再真跑", called == [], f"called={called}")
        check("排队取消后状态仍是 cancelled", job.state == "cancelled", job.state)
    finally:
        job_queue.run_job = orig
        drop(job)


def test_cancel_running():
    job = keep(FakeJob("t-running", st="running"))
    try:
        how = state.cancel_job(job.id)
        check("跑着的任务取消返回 running", how == "running", f"got={how}")
        check("跑着的任务只打标记、不改状态", job.cancel_requested is True and job.state == "running",
              job.state)
    finally:
        drop(job)


def test_cancel_unknown():
    check("取消不存在的任务返回 None", state.cancel_job("t-nope") is None)


def test_run_one_normal():
    seen = []
    orig = job_queue.run_job
    job_queue.run_job = lambda j, cfg: seen.append((j.id, cfg))
    job = keep(FakeJob("t-normal", st="queued"))
    try:
        job_queue.run_one(job, {"k": 1})
        check("正常任务会真跑一次", seen == [("t-normal", {"k": 1})], f"seen={seen}")
    finally:
        job_queue.run_job = orig
        drop(job)


def test_run_one_error():
    def boom(j, cfg):
        raise RuntimeError("炸了")

    orig = job_queue.run_job
    job_queue.run_job = boom
    job = keep(FakeJob("t-error", st="queued"))
    try:
        # run_one 会把 traceback 打到 stderr，这里只是测语义，别把测试输出弄脏
        with contextlib.redirect_stderr(io.StringIO()):
            job_queue.run_one(job, {})
        check("异常落到 job.error", "炸了" in (job.error or ""), str(job.error))
        check("异常后状态是 error", job.state == "error", job.state)
    finally:
        job_queue.run_job = orig
        drop(job)


def main():
    print("排队取消与队列收尾")
    test_cancel_queued()
    test_queued_cancel_skips_run()
    test_cancel_running()
    test_cancel_unknown()
    test_run_one_normal()
    test_run_one_error()
    if FAILED:
        print(f"\n{len(FAILED)} 项失败：{FAILED}")
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
