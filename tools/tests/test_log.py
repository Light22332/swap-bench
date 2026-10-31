"""日志的测试：默认不往控制台乱打、配置一次就够、文件真的落盘。

为什么要测这个：日志是"出问题时唯一的线索"，如果 setup 没生效、或者文件
写不进去却静默失败，等于没有。桌面版的后端是隐藏窗口，控制台里什么都看不到。

跑法：python tools/tests/test_log.py
"""
import logging
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.core import log                    # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


print("日志：默认安静、配置一次、文件能落")
root = logging.getLogger(log.NAME)
check("模块导入后挂的是 NullHandler（没配置也不乱打）",
      any(isinstance(h, logging.NullHandler) for h in root.handlers))

tmp = tempfile.mkdtemp(prefix="swapbench-log-")
for h in list(root.handlers):           # 让 setup 当作第一次调用
    root.removeHandler(h)
log._configured = False
same = log.setup(tmp)
log.get("queue").info("测试一行 %s", 42)
for h in root.handlers:
    h.flush()

path = os.path.join(tmp, log.FILE_NAME)
check("日志文件写出来了", os.path.isfile(path), path)
text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
check("文件里带 logger 名和内容", "swapbench.queue" in text and "测试一行 42" in text, text[-160:])
check("setup 只生效一次", log.setup(tmp) is same)
check("get 的名字带前缀", log.get("judge.faces").name == "swapbench.judge.faces",
      log.get("judge.faces").name)

print()
if FAILED:
    print(f"{len(FAILED)} 项没过：" + "、".join(FAILED))
    sys.exit(1)
print("全部通过")
