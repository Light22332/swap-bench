"""返回给前端的视图：把文件路径换成 URL，前端就不用关心磁盘布局。"""
from ..core import paths


def decorate(job_dict):
    """给任务结构补上图片 URL。原图也带上，页面要做原片/成片对比。"""
    job_dict["person_url"] = paths.url(job_dict.get("person"))
    for c in job_dict.get("cases", []):
        for a in c.get("attempts", []):
            if a.get("stage") == "generate" and a.get("image"):
                a["image_url"] = paths.url(a["image"])
        c["final_url"] = paths.url(c.get("final_image"))
    return job_dict
