"""把远程地址写进 .git/config。

**现在多半用不上了**：这台机器上有一份能正常写盘的 git
（`D:\\Godot\\tools\\git\\cmd\\git.exe`），`git remote add` 直接就能用。
当时写这个脚本，是因为 PATH 上那份 git 报
"could not lock config file .git/config: Permission denied"，
只好用 dulwich 直接改配置文件，格式和 git 自己写出来的完全一样。

    python tools/set_remote.py https://github.com/user/repo.git
"""
import sys

from dulwich.repo import Repo
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) < 2:
        print("用法：python tools/set_remote.py <仓库地址>")
        return 1
    url = sys.argv[1].strip()
    if not url:
        print("地址为空")
        return 1

    repo = Repo(ROOT)
    cfg = repo.get_config()
    cfg.set((b"remote", b"origin"), b"url", url.encode("utf-8"))
    cfg.set((b"remote", b"origin"), b"fetch",
            b"+refs/heads/*:refs/remotes/origin/*")
    cfg.set((b"branch", b"main"), b"remote", b"origin")
    cfg.set((b"branch", b"main"), b"merge", b"refs/heads/main")
    cfg.write_to_path()
    print("已设置 origin =", url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
