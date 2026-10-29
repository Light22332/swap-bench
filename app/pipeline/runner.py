"""编排：把整理参考图、生成、判定、决策串成一条循环。

这里只做 IO 和记账。要不要继续、走哪种打法由 policy 决定；最后挑哪张由 select 决定。
"""
import os
import time
import traceback

from ..capability.generate import GenRequest, make_backend
from ..core import config as app_config
from ..core.checks import fix_clauses, is_critical
from ..core.store import Store, compute_metrics
from ..capability.judge import make_judge
from ..capability.prep import crop_garment
from . import policy, select


def run_job(job, config):
    pipeline_cfg = app_config.section(config, "pipeline")
    sampling = app_config.section(config, "sampling")
    prep_cfg = app_config.section(config, "prep")

    max_attempts = pipeline_cfg["max_attempts"]
    escape_cfg = pipeline_cfg["escape_cfg"]
    total_attempts = max_attempts + max(0, int(pipeline_cfg["escape_attempts"]))
    do_prep = prep_cfg["enabled"]
    prep_mode = prep_cfg["mode"]
    models_dir = app_config.models_dir(config)
    prep_dir = os.path.join(app_config.outputs_dir(config), "prep")

    store = Store(app_config.runs_dir(config))
    backend = make_backend(app_config.backend(config), config)
    judge = make_judge(config)

    job.state = "running"
    store.append(job.id, {"stage": "job_start", "job": job.id,
                          "person": job.person_path,
                          "garments": [g["name"] for g in job.garments],
                          "backend": backend.name, "judge_mode": judge.mode,
                          "prep": do_prep, "prep_mode": prep_mode,
                          "max_attempts": max_attempts,
                          "escape_attempts": pipeline_cfg["escape_attempts"],
                          "escape_cfg": escape_cfg})

    for case, garment in zip(job.cases, job.garments):
        case["state"] = "running"
        ref_path = _prepare(job, case, garment, store, prep_dir, prep_mode,
                            models_dir, do_prep)
        tried = _run_attempts(job, case, ref_path, store, backend, judge,
                              sampling, max_attempts, total_attempts, escape_cfg)

        idx = select.best(tried)
        if idx < 0:
            case["state"] = "failed"
            continue
        pick = tried[idx]
        verdict = pick["verdict"]
        case["final_image"] = pick["gen"].image_path
        case["verdict"] = verdict
        case["passed"] = verdict["passed"]
        case["first_attempt_passed"] = bool(tried[0]["verdict"]["passed"])
        case["state"] = select.case_state(verdict["passed"], len(tried))
        case["chosen_attempt"] = pick["attempt"]
        if pick["attempt"] != len(tried):
            store.append(job.id, {"stage": "pick", "case": case["index"],
                                  "chosen": pick["attempt"], "of": len(tried),
                                  "score": verdict["score"]})

    job.metrics = compute_metrics(job.cases, judge.mode)
    job.finished = time.time()
    job.state = "done"
    store.append(job.id, {"stage": "job_end", "job": job.id, "metrics": job.metrics})
    return job


def _prepare(job, case, garment, store, prep_dir, prep_mode, models_dir, do_prep):
    """整理参考图。裁完的路径交给后面每一轮用。"""
    if not do_prep:
        return garment["path"]
    ref_path, meta = crop_garment(garment["path"], prep_dir, mode=prep_mode,
                                  models_dir=models_dir, device="cpu")
    if meta:
        case["prep"] = meta
        store.append(job.id, {"stage": "prep", "case": case["index"],
                              "garment": garment["name"], **meta})
    return ref_path


def _run_attempts(job, case, ref_path, store, backend, judge, sampling,
                  max_attempts, total_attempts, escape_cfg):
    """跑这件衣服的所有轮次，返回每次成功生成的 [(attempt, gen, verdict)]。"""
    tried = []
    refined = job.instruction

    for attempt in range(1, total_attempts + 1):
        case["attempts_used"] = attempt
        mode = policy.mode_for(attempt, max_attempts)
        escaping = mode == policy.ESCAPE
        instruction = job.instruction if escaping else refined
        cfg = escape_cfg if escaping else sampling["cfg"]

        req = GenRequest(
            person_path=job.person_path,
            garment_path=ref_path,
            instruction=instruction,
            negative=job.negative,
            cfg=cfg,
            steps=sampling["steps"],
            resolution=sampling["resolution"],
            seed=None,
            prefix=f"{job.id}_c{case['index']}_a{attempt}",
        )
        try:
            gen = backend.generate(req)
        except Exception as e:
            traceback.print_exc()
            gen = None
            job.error = f"{type(e).__name__}: {e}"

        if gen is None or not gen.ok:
            rec = {"stage": "generate", "case": case["index"], "attempt": attempt,
                   "garment": case["garment"], "ok": False, "mode": mode,
                   "error": job.error,
                   "error_kind": getattr(gen, "error_kind", "exception")}
            case["attempts"].append(rec)
            store.append(job.id, rec)
            break

        grec = {"stage": "generate", "case": case["index"], "attempt": attempt,
                "garment": case["garment"], "ok": True, "mode": mode,
                "cfg": cfg, "instruction_used": instruction,
                "latency_s": round(gen.latency_s, 2), "backend": gen.backend,
                "model": gen.model, "seed": gen.seed, "cost": gen.cost,
                "image": gen.image_path, "meta": gen.meta}
        case["attempts"].append(grec)
        store.append(job.id, grec)

        verdict = judge(job.person_path, gen.image_path, ref_path)
        jrec = {"stage": "judge", "case": case["index"], "attempt": attempt,
                "garment": case["garment"], "mode": mode,
                "judge_mode": verdict["mode"],
                "passed": verdict["passed"], "score": verdict["score"],
                "failures": verdict["failures"], "checks": verdict["checks"],
                "latency_s": verdict["latency_s"], "note": verdict["note"]}
        case["attempts"].append(jrec)
        store.append(job.id, jrec)

        tried.append({"attempt": attempt, "gen": gen, "verdict": verdict})

        clauses = fix_clauses(verdict["failures"])
        decision = policy.decide(
            attempt=attempt, total_attempts=total_attempts, max_attempts=max_attempts,
            passed=verdict["passed"],
            critical_failed=any(is_critical(k) for k in verdict["failures"]),
            clauses=clauses)

        if decision.action == policy.ACCEPT:
            break
        if decision.action == policy.STOP:
            if decision.log:
                store.append(job.id, {"stage": "stop", "case": case["index"],
                                      "attempt": attempt, "reason": decision.reason,
                                      "failures": verdict["failures"]})
            break

        # 继续下一轮
        if decision.clauses:
            refined = (job.instruction
                       + "\n\n本次必须修正：" + "；".join(decision.clauses)
                       + "\n注意：仍然必须完成服装替换，不得退回图1的原有衣服。")
        store.append(job.id, {"stage": "refine", "case": case["index"],
                              "attempt": attempt, "added": list(decision.clauses),
                              **({"reason": decision.reason} if decision.reason else {})})

    return tried
