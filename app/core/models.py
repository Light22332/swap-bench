"""领域对象：一次任务长什么样。

Job 管一个批次（一张人像配若干件衣服），Case 管其中一件衣服的全部尝试。
这里只有数据结构，不碰文件、不碰网络、不碰模型。
"""
import time
import uuid


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


def new_job(person_path, garments, instruction, negative, config):
    return Job(uuid.uuid4().hex[:12], person_path, garments, instruction, negative, config)
