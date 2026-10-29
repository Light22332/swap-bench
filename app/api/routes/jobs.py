"""任务查询：还在跑的从内存读，跑完的从 JSONL 还原。

两条路都是为了让 ?job=<id> 的链接长期有效——服务重启后内存清了，但 JSONL 还在。
"""
import time

from .. import history, state, view


def handle_get(req):
    p = req.path
    if p.startswith("/api/job/"):
        jid = p[len("/api/job/"):]
        job = state.get_job(jid)
        if job:
            req.json(view.decorate(job.to_dict()))
            return True
        replay = history.load_job(jid)
        if replay:
            req.json(view.decorate(replay))
            return True
        req.json({"error": "no such job"}, 404)
        return True

    if p == "/api/jobs":
        items = state.recent_jobs(20)
        req.json([{"id": j.id, "state": j.state,
                   "elapsed_s": round((j.finished or time.time()) - j.started, 1),
                   "cases": len(j.cases)} for j in items])
        return True

    if p == "/api/metrics":
        req.json(history.global_metrics())
        return True
    return False
