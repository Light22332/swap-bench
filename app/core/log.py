"""日志：落到 runs/server.log，桌面窗口没控制台时也能事后查。

为什么不用 print：Electron 起的后端是隐藏窗口，stderr 没人看；出了问题只剩
「页面上转圈」这一条线索。为什么轮转：跑久了日志会跟结果图一样只增不减，
2MB × 3 份封顶，不用再配一个清理脚本。
"""
import logging
import logging.handlers
import os

from . import paths

NAME = "swapbench"
FILE_NAME = "server.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 3

_FORMAT = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s",
                            "%Y-%m-%d %H:%M:%S")
_configured = False

# 静态文件、模型检测、队列、服务各用一个子 logger，出问题时能按来源筛。
logging.getLogger(NAME).addHandler(logging.NullHandler())


def setup(log_dir=None, level=logging.INFO):
    """第一次调用时装控制台 + 文件两个 handler；重复调用直接返回。"""
    global _configured
    root = logging.getLogger(NAME)
    if _configured:
        return root
    _configured = True
    root.setLevel(level)
    stream = logging.StreamHandler()
    stream.setFormatter(_FORMAT)
    root.addHandler(stream)

    target = log_dir or paths.RUNS
    try:
        os.makedirs(target, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(target, FILE_NAME),
            maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        handler.setFormatter(_FORMAT)
        root.addHandler(handler)
    except OSError:
        pass        # 目录只读也要能起服务，退化成只打控制台
    root.propagate = False
    return root


def get(name=""):
    """get("queue") → swapbench.queue"""
    return logging.getLogger(NAME + ("." + name if name else ""))
