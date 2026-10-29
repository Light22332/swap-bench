"""把 tools/git-hooks/ 里的钩子装进 .git/hooks/。

克隆之后跑一次：

    python tools/install_hooks.py

现在装的是一个 pre-commit：拦住把密钥提交进仓库。钩子只在本地生效，
换机器或者重新 clone 之后要再跑一次。
"""
import os
import stat
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "tools", "git-hooks")
DST = os.path.join(ROOT, ".git", "hooks")


def main():
    if not os.path.isdir(DST):
        print("这里不是 git 仓库，找不到 .git/hooks")
        return 1

    done = []
    for name in sorted(os.listdir(SRC)):
        src = os.path.join(SRC, name)
        if not os.path.isfile(src) or name.endswith(".md"):
            continue
        dst = os.path.join(DST, name)
        # 一律按 LF 写出去：Windows 上 checkout 出来的是 CRLF，sh 读带 \r 的脚本会炸
        with open(src, "rb") as f:
            blob = f.read().replace(b"\r\n", b"\n")
        with open(dst, "wb") as f:
            f.write(blob)
        os.chmod(dst, os.stat(dst).st_mode | stat.S_IEXEC)
        done.append(name)

    if not done:
        print("tools/git-hooks/ 里没有可装的东西")
        return 1
    print("装好了：" + "、".join(done))
    print("钩子只对这份 clone 生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
