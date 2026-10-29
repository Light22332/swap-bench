"""任务查询：还在跑的从内存读，跑完的从 JSONL 还原。

除了单次任务，这里还有两件跟"一批图"有关的事：存档列表、整批导出。
"""
import time
import urllib.parse

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

    if p == "/api/history":
        req.json(history.list_jobs())
        return True

    if p == "/api/export":
        return _export(req)
    return False


def _export(req):
    jid = req.param("job")
    if not jid:
        req.json({"error": "要给一个 job"}, 400)
        return True

    job = state.get_job(jid)
    data = view.decorate(job.to_dict()) if job else history.load_job(jid)
    if not data:
        req.json({"error": "no such job"}, 404)
        return True

    packed, blob = history.export_zip(data)
    if not packed:
        req.json({"error": "这次任务还没有出图"}, 404)
        return True
    name = "换装_{}.zip".format(jid)
    req.bytes(blob, "application/zip", cache="no-store", extra={
        "Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name),
    })
    return True
