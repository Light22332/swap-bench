"""项目内路径的唯一定义处。

以前 `ROOT` 在 pipeline 和 server 里各算一次，`uploads`/`runs`/`outputs` 到处用
`os.path.join(ROOT, ...)` 拼。改目录结构时要全文搜。现在只在这里定义一次。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIG_FILE = os.path.join(ROOT, "config.json")
WEB = os.path.join(ROOT, "web")
UPLOADS = os.path.join(ROOT, "uploads")
RUNS = os.path.join(ROOT, "runs")
OUTPUTS = os.path.join(ROOT, "outputs")
MODELS = os.path.join(ROOT, "models")
SAMPLES = os.path.join(ROOT, "samples")


def inside(rel):
    """把相对路径钉死在项目目录内，防止 ../ 穿越。越界返回 None。"""
    rel = (rel or "").replace("\\", "/").lstrip("/")
    full = os.path.realpath(os.path.join(ROOT, rel))
    if not full.startswith(os.path.realpath(ROOT) + os.sep):
        return None
    return full


def rel(path):
    """绝对路径转成相对项目根的斜杠路径；在项目外返回 None。"""
    if not path:
        return None
    try:
        r = os.path.relpath(path, ROOT)
    except ValueError:
        return None
    if r.startswith(".."):
        return None
    return r.replace("\\", "/")


def url(path):
    """项目内的图片路径转成 /img 能访问的 URL；越界返回 None。"""
    if not path:
        return None
    r = rel(path)
    if not r:
        return None
    from urllib.parse import quote
    return "/img?path=" + quote(r)
