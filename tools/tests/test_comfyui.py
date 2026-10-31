"""ComfyUI 轮询的测试：网络抖一下不能把整单废掉，卡死了要认输。

跑法：python tools/tests/test_comfyui.py
"""
import os
import sys
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.capability.generate.base import BackendError              # noqa: E402
from app.capability.generate.comfyui import POLL_FAILS, ComfyUIBackend   # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def backend():
    """只测 _wait，不需要真配置。"""
    b = object.__new__(ComfyUIBackend)
    b.base_url = "http://127.0.0.1:1"
    return b


class Script:
    """按顺序吐结果；最后一项重复用。"""

    def __init__(self, items):
        self.items = list(items)
        self.calls = 0

    def __call__(self, pid):
        self.calls += 1
        item = self.items[0] if len(self.items) == 1 else self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def expect_error(b, **kw):
    try:
        b._wait("pid", **kw)
    except BackendError as e:
        return e
    return None


def main():
    print("轮询：偶发失败要重试，连续失败才放弃")
    b = backend()
    s = Script([urllib.error.URLError("blip"),
                urllib.error.URLError("blip"),
                {"pid": {"status": {"status_str": "running"}}, "outputs": {}}])
    b._history = s
    got = b._wait("pid", timeout=5, interval=0.01)
    check("两次抖动后照样等到结果", got is not None and s.calls == 3, str(s.calls))

    b = backend()
    s = Script([urllib.error.URLError("down")])
    b._history = s
    err = expect_error(b, timeout=5, interval=0.01)
    check("一直连不上报 network", err is not None and err.kind == "network",
          str(err and (err.kind, err.message)))
    check(f"连到第 {POLL_FAILS} 次才放弃", s.calls == POLL_FAILS, str(s.calls))
    check("报错文案说清楚是轮询失败", err is not None and "轮询连续失败" in err.message,
          err and err.message)

    print("轮询：ComfyUI 报错要分类（显存不够 vs 节点报错）")
    b = backend()
    b._history = Script([{"pid": {"status": {"status_str": "error",
                                             "messages": ["CUDA out of memory"]}}}])
    err = expect_error(b, timeout=5, interval=0.01)
    check("OOM 认成 vram", err is not None and err.kind == "vram", str(err and err.kind))

    b = backend()
    b._history = Script([{"pid": {"status": {"status_str": "error",
                                             "messages": ["node exploded"]}}}])
    err = expect_error(b, timeout=5, interval=0.01)
    check("其它错误认成 node_error", err is not None and err.kind == "node_error",
          str(err and err.kind))

    print("轮询：一直没跑完，要按总超时收场")
    b = backend()
    b._history = Script([{}])
    err = expect_error(b, timeout=0.2, interval=0.01)
    check("总超时报 timeout", err is not None and err.kind == "timeout",
          str(err and (err.kind, err.message)))
    check("超时文案提示去看 ComfyUI", err is not None and "卡住" in err.message,
          err and err.message)

    print("轮询：第一次就成功")
    b = backend()
    b._history = Script([{"pid": {"status": {"status_str": "success"},
                                  "outputs": {"9": {"images": [{"filename": "x.png"}]}}}}])
    got = b._wait("pid", timeout=5, interval=0.01)
    check("直接拿到 outputs", got.get("outputs", {}).get("9", {}).get("images"),
          str(got)[:120])

    if FAILED:
        print(f"\n{len(FAILED)} 项失败：{FAILED}")
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
