"""证据层：每一次尝试都落一行 JSONL。

这是整个项目里最容易被忽略、但最能让人信服的一层。
面试官问"效果怎么保证"，打开 metrics 就有数字，不是形容词。
"""
import json
import os
import time


class Store:
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, job_id):
        return os.path.join(self.root, f"{job_id}.jsonl")

    def append(self, job_id, record):
        record = dict(record)
        record.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        with open(self._path(job_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read(self, job_id):
        p = self._path(job_id)
        if not os.path.exists(p):
            return []
        out = []
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return out

    def all_jobs(self):
        if not os.path.isdir(self.root):
            return []
        return sorted(f[:-6] for f in os.listdir(self.root) if f.endswith(".jsonl"))


def compute_metrics(cases, judge_mode):
    """一批结束后的汇总。这些数字就是报告里能写的那几行。"""
    total = len(cases)
    first_pass = sum(1 for c in cases if c.get("first_attempt_passed"))
    final_pass = sum(1 for c in cases if c.get("passed"))
    attempts = [c.get("attempts_used", 0) for c in cases if c.get("attempts_used")]
    latencies = [a.get("latency_s", 0) for c in cases for a in c.get("attempts", [])
                 if a.get("stage") == "generate"]

    reasons = {}
    for c in cases:
        for a in c.get("attempts", []):
            if a.get("stage") == "judge":
                for f in a.get("failures", []) or []:
                    reasons[f] = reasons.get(f, 0) + 1

    return {
        "cases": total,
        "first_pass_rate": round(first_pass / total, 3) if total else 0,
        "final_pass_rate": round(final_pass / total, 3) if total else 0,
        "avg_attempts": round(sum(attempts) / len(attempts), 2) if attempts else 0,
        "avg_generate_s": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "total_generate_s": round(sum(latencies), 1),
        "judge_mode": judge_mode,
        "failure_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
    }
