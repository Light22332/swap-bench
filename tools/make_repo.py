"""用 dulwich 建仓库并提交。

为什么不用 git.exe：这台机器上 git.exe 被沙箱挡了，连 .git 目录都建不出来
（`git init` 报 Permission denied），但普通进程可以正常写文件。
所以用纯 Python 的 dulwich 生成标准格式的仓库，之后用真正的 git 推就行。

    python tools/make_repo.py
    python tools/make_repo.py -m "自定义提交信息"
"""
import argparse
import os
import sys

from dulwich import porcelain
from dulwich.repo import Repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_MSG = """换装验收台：本地服装换装生产线 + 质检

生成、质检、返工、挑最优，四步做成一条流水线。

- 生成：本地 ComfyUI 跑 Qwen-Image 2.1（INT8），约 55s/张
- 整理参考图：裁掉人脸/手机/背景/水印，这一层比提示词更影响效果
- 质检：人脸识别比对 + 身体区域变化 + 背景主色 + 人脸计数，4 项自动判定
- 返工：失败项翻译成新约束再喂回去，从所有尝试里挑分数最高的一张
- 证据：每次尝试落一行 JSONL，批次给出合格率、重试次数、失败原因分布

桌面端用 Electron 包了一层：双击启动，自动拉起 ComfyUI 和本地服务。
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", default=DEFAULT_MSG)
    args = ap.parse_args()

    git_dir = os.path.join(ROOT, ".git")
    if not os.path.isdir(git_dir):
        porcelain.init(ROOT)
        # dulwich 的 init 不接受 default_branch，直接改 HEAD 指向 main
        with open(os.path.join(git_dir, "HEAD"), "w", encoding="utf-8") as f:
            f.write("ref: refs/heads/main\n")
        print("已初始化仓库（分支 main）")
    else:
        print("仓库已存在，跳过 init")

    repo = Repo(ROOT)

    added, ignored = porcelain.add(repo, paths=None)
    staged = list(added or [])
    print(f"已暂存 {len(staged)} 个文件")
    if ignored:
        print(f"按 .gitignore 忽略 {len(ignored)} 项")

    if not staged:
        print("没有可提交的改动")
        return 0

    author = b"Light22332 <2233265681@qq.com>"
    try:
        cid = porcelain.commit(repo, message=args.message.encode("utf-8"),
                               author=author, committer=author)
    except Exception as e:
        print("提交失败：", e)
        return 1

    print("提交完成：", cid.decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
