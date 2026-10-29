"""编排层：整理参考图 → 生成 → 质检 → 按失败项补约束 → 重试 → 挑最好的一张。

两个关键决定（都是被实际结果逼出来的）：

1. **保留每次尝试，最后挑最好的一张，而不是"通过了就用最后一张"。**
   实测发生过：第 2 次人像保住了，但被判"背景不合格"，重试后第 3 次脸被手机挡住，
   因为当时的判定只看背景，于是放行了更差的那张。现在按评分取最优。

2. **只有关键项（脸、衣服、手）不过才重试。**
   背景这类非关键项不过就重试，容易把已经对的结果改坏。宁可记一笔，也不折腾。

配置从 core.config 取，路径从 core.paths 取，判定规则从 core.checks 取；
这个文件不定义默认值，也不拼项目路径。
"""
import os
import time
import traceback
import uuid

from .adapters import GenRequest, make_backend
from .core import config as app_config
from .core.checks import is_critical
from .core.store import Store, compute_metrics
from .judge import make_judge, fix_clauses
from .prep import crop_garment


class Job:
    def __init__(self, job_id, person_path, garments, instruction, negative, config):
        self.id = job_id
        self.person_path = person_path
        self.garments = garments
        self.instruction = instruction
        self.negative = negative
        self.config = config
        self.state = "pending"
        self.started = time.time()
        self.finished = None
        self.cases = [
            {"index": i + 1, "garment": g["name"], "state": "pending",
             "attempts": [], "attempts_used": 0, "passed": False,
             "first_attempt_passed": False, "final_image": None,
             "verdict": None, "instruction_used": instruction, "prep": None}
            for i, g in enumerate(garments)
        ]
        self.metrics = {}
        self.error = None

    def to_dict(self):
        return {
            "id": self.id,
            "state": self.state,
            "elapsed_s": round((self.finished or time.time()) - self.started, 1),
            "judge_mode": "local",
            "cases": self.cases,
            "metrics": self.metrics,
            "error": self.error,
        }


def _critical_failed(failures):
    return any(is_critical(k) for k in failures)


def run_job(job, config):
    pipeline_cfg = app_config.section(config, "pipeline")
    sampling = app_config.section(config, "sampling")
    prep_cfg = app_config.section(config, "prep")
    do_prep = prep_cfg["enabled"]
    prep_mode = prep_cfg["mode"]
    max_attempts = pipeline_cfg["max_attempts"]
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
                          "escape_cfg": pipeline_cfg["escape_cfg"]})

    for case, garment in zip(job.cases, job.garments):
        case["state"] = "running"

        ref_path = garment["path"]
        if do_prep:
            ref_path, prep_meta = crop_garment(
                garment["path"], prep_dir, mode=prep_mode, models_dir=models_dir,
                device=prep_cfg["device"])
            if prep_meta:
                case["prep"] = prep_meta
                store.append(job.id, {"stage": "prep", "case": case["index"],
                                      "garment": garment["name"], **prep_meta})

        instruction = job.instruction
        tried = []          # [(verdict, gen_result)]
        escape_cfg = pipeline_cfg["escape_cfg"]
        escape_left = max(0, int(pipeline_cfg["escape_attempts"]))
        total_attempts = max_attempts + escape_left

        for attempt in range(1, total_attempts + 1):
            # attempt > max_attempts 的那几轮是"降级重跑"：回到原始指令、把 cfg 抬起来，
            # 靠负向提示词生效换一条路，而不是继续在越来越长的约束里打转。
            escaping = attempt > max_attempts
            case["attempts_used"] = attempt
            mode = "escape" if escaping else ("base" if attempt == 1 else "refine")
            cfg_now = escape_cfg if escaping else sampling["cfg"]
            instr_now = job.instruction if escaping else instruction

            req = GenRequest(
                person_path=job.person_path,
                garment_path=ref_path,
                instruction=instr_now,
                negative=job.negative,
                cfg=cfg_now,
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
                    "cfg": cfg_now, "instruction_used": instr_now,
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

            tried.append((verdict, gen))

            if verdict["passed"]:
                break
            if not _critical_failed(verdict["failures"]):
                # 只有非关键项不过：记一笔就停，别把已经对的结果改坏
                store.append(job.id, {"stage": "stop", "case": case["index"],
                                      "attempt": attempt,
                                      "reason": "只有非关键项不过，不再重试",
                                      "failures": verdict["failures"]})
                break
            if escaping:
                # 降级重跑也不过，没有更多手段了，别再烧时间
                store.append(job.id, {"stage": "stop", "case": case["index"],
                                      "attempt": attempt,
                                      "reason": "降级重跑仍不过，放弃",
                                      "failures": verdict["failures"]})
                break
            if attempt >= total_attempts:
                break

            clauses = fix_clauses(verdict["failures"])
            if clauses:
                instruction = (
                    job.instruction
                    + "\n\n本次必须修正：" + "；".join(clauses)
                    + "\n注意：仍然必须完成服装替换，不得退回图1的原有衣服。"
                )
                store.append(job.id, {"stage": "refine", "case": case["index"],
                                      "attempt": attempt, "added": clauses})
            else:
                # 没有可补的约束，下一轮直接走降级
                store.append(job.id, {"stage": "refine", "case": case["index"],
                                      "attempt": attempt, "added": [],
                                      "reason": "没有可补的约束，下一轮降级"})

        # ---- 挑最好的一张：先看通过，再看分数 ----
        if tried:
            best_v, best_g = max(tried, key=lambda t: (t[0]["passed"], t[0]["score"]))
            case["final_image"] = best_g.image_path
            case["verdict"] = best_v
            case["passed"] = best_v["passed"]
            case["first_attempt_passed"] = bool(tried[0][0]["passed"])
            case["state"] = "passed" if best_v["passed"] else (
                "reworked" if len(tried) > 1 else "rejected")
            case["chosen_attempt"] = [i + 1 for i, (v, g) in enumerate(tried)
                                      if g.image_path == best_g.image_path][0]
            if case["chosen_attempt"] != len(tried):
                store.append(job.id, {"stage": "pick", "case": case["index"],
                                      "chosen": case["chosen_attempt"],
                                      "of": len(tried), "score": best_v["score"]})
        else:
            case["state"] = "failed"

    job.metrics = compute_metrics(job.cases, judge.mode)
    job.finished = time.time()
    job.state = "done"
    store.append(job.id, {"stage": "job_end", "job": job.id, "metrics": job.metrics})
    return job


def new_job(person_path, garments, instruction, negative, config):
    return Job(uuid.uuid4().hex[:12], person_path, garments, instruction, negative, config)
