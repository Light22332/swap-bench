# 面试演示版 · 开发方案（2026-10-30）

目标变了，优先级跟着变。

之前的排序是「回归基线 → 打包 → 云端实测」，那是按工程完整度排的。现在的目标定了四条：面试现场用自己的笔记本演示、仓库配合文档和截图当作品、投递已经在进行随时可能面试、样例图换成可自用的放进仓库。

这四条把「安装包」和「云端后端」从待办里挪走了（现场用自己的电脑，不需要安装包；没有真 key，云端测不了），把三件以前没算进计划的事顶到了前面：**现场等太久、别人 clone 下来跑不起来、核心模块没有测试**。

---

## 一、验收标准

四条，都能当场量出来：

| 标准 | 怎么量 |
|---|---|
| 冷机从双击到出第一张图 ≤ 4 分钟 | 拔掉预热，计时 |
| 预热后单张 ≤ 70 秒 | 跑一次真任务，看页面耗时 |
| 干净目录 clone + 下模型 + 一条命令能出图 | 在 `%TEMP%` 里真做一遍，不向本机要任何文件 |
| 卡住的时候页面说得出下一步 | 手动关掉 ComfyUI 再点开始，看提示 |

---

## 二、现状（量过的）

代码规模：`app/` 36 个 py、2679 行；`tools/` 10 个 py、1210 行；`web/` 13 个文件、1797 行（无框架无构建）；`electron/main.js` 225 行。21 个提交，工作区干净，全仓 0 处 TODO。

三道闸门都在：`check.py` 8 项约 2 秒、`replay.py` 回放翻转 0 项、`api_baseline.py` 14 个接口形状。

基线：8 组合格 6 组（75%），首轮 5/8，平均重试 1.62 次，平均 100.6 秒，手部 75% 是唯一弱点。

**缺口是真的量出来的，不是猜的：**

1. `samples/` 只有 README 进版本库，7 张图全被 `.gitignore` 挡掉。别人 clone 下来点「载入示例看看」是空的。
2. `models/` 现在 0 个文件（本机靠 `D:\Comfyui` 那套？不是，是本地下过又清了）。下载命令写在 `models/README.md` 里，7 条 curl，能用但没人会耐心抄。
3. 没有 `requirements.txt`，也没有 `pyproject.toml`。依赖只写在 README 的一句话里。
4. 没有 `.github/`，没有 CI。
5. 21 个模块没有测试。其中最扎眼的是判定层 `faces.py` 127 行、`hands.py` 251 行、`rules.py` 213 行，这 591 行是整个项目的卖点（"自己验收"），一行测试都没有。
6. 冷启动：ComfyUI 起 35 秒，第一张图 90 秒。现场加起来两分钟。
7. 没有取消，没有队列。README 的已知限制里写了，但演示时选错图只能干等三分钟。
8. 全仓 0 个 gif / mp4。README 只有两张静态截图。

---

## 三、P0：现场不翻车（今晚，约 3 小时）

这三件都只服务一件事：面试官坐在旁边的那五分钟，别出岔子。

**做完的结果（2026-10-30 晚，本机实测）：**

- P0-1 预热：`tools/warmup.py` + `预热.bat`。冷启动拉起 ComfyUI 22-25 秒，暖机图 57-58 秒，从双击到「可以开始演示了」约 80 秒；之后单件任务 57 秒（生成 56.2、质检 0.8）。
- P0-2 秒数：本来就有（工序条右侧的 `rail-num`，每轮轮询都刷新），只是显示成 `43.0s`，改成了「已用 43 秒」。
- P0-3 探活：`comfyui.system_stats()` / `ping()`，`/api/run` 提交前先探一次。实测关掉 ComfyUI 再点开始，返回 400「换装服务还没起来。先双击根目录的「预热.bat」…」。
- P0-4 彩排：时间线写进 README 的「一次演示要多久」。顺带发现两个会让耗时翻倍的情况——队列里压着别的任务（56 秒变 150 秒）、ComfyUI 跑到一半被 interrupt（后面三次全判不过，重启才恢复，记进 README 坑五）。
- 三道闸门：`check.py` 8/8（2.8 秒）、`replay.py` 翻转 0 项、`api_baseline.py` 14 个接口一致。

### P0-1 预热脚本（`tools/warmup.py` + `预热.bat`）

**为什么**：ComfyUI 加载模型是懒的，第一张图 90 秒里有一大半是加载。先跑一张，把模型压进显存，后面每张回到 55-60 秒。现在没有这个动作，只能靠记性。

**做什么**（约 70 行）：

1. 探 `http://127.0.0.1:8188/system_stats`。通就直接下一步。
2. 不通就用 `config.json` 里的 `desktop.python` 和 `desktop.comfyui_dir` 起 ComfyUI，参数和 `electron/main.js` 里那套一致（`--windows-standalone-build --disable-auto-launch --port 8188`），最多等 120 秒。
3. 用 `samples/` 里现成两张提交一次生成，走 `capability.generate`，不经 pipeline，不落 `runs/`，图直接丢掉。
4. 打印三段秒数：ComfyUI 就绪 / 暖机图 / 一句「可以开始演示了，现在单张约 55 秒」。

配一个 GBK + CRLF 的 `预热.bat`（这个坑踩过，编码错一个就报 `'UI' 不是内部或外部命令`）。

**验收**：双击 `预热.bat`，2 分钟内看到"可以开始"；紧接着真跑一件，页面耗时 ≤ 70 秒。

**顺带的好处**：ComfyUI 是 `warmup.py` 起的，之后双击 `启动换装台.exe` 时 `main.js` 会发现 8188 已经在跑、不重复起，关窗口也不会误杀它。两条路不打架。

### P0-2 跑的时候显示"已经等了多少秒"（`web/js/render.js`，约 10 行）

**为什么**：现在等的时候页面只有一行「第 1 件：正在生成…」，1.5 秒刷一次，看不出在动还是在卡。有秒数在跳，等待就变得可以忍受，也不用面试官开口问"还要多久"。

**做什么**：`S.elapsed` 服务端已经返回了，`run.js` 每轮都赋值，只是没有渲染到正在跑的那一格上。先确认 `render.js` 有没有用到它，没用就在 live 卡片上加一行「已用 43 秒」。轮询 1.5 秒一次，够了，不用再加定时器。

**验收**：跑一次，秒数从个位数涨到两位数。

### P0-3 提交前先探一下 ComfyUI 在不在（`capability/generate/comfyui.py` +12 行，`api/routes/run.py` +8 行）

**为什么**：现在 ComfyUI 没启动，页面能提交，然后在后台线程里炸，用户看到的是「出错了：ConnectionRefusedError…」。现场看到这个基本等于演示结束。

**做什么**：`comfyui.py` 加一个 `ping()`，打 `/system_stats`。`run.py` 在起线程之前调一次，不通就回 400「ComfyUI 还没启动，先双击 预热.bat」。只有 `backend == comfyui` 时才探。

前端的处理已经现成：`run.js` 的 `catch` 会 `hint('提交失败：' + e.message, true)`，不用改。

**验收**：关掉 ComfyUI 点开始，页面出这句话，不是异常堆栈。

### P0-4 彩排一次，记一条时间线（文档，30 分钟）

**为什么**：上面三件做完，真实耗时还是没人量过。彩排能发现想不出来的问题（比如某一步会要求点确认、窗口没置顶、图在相册里翻不到）。

**做什么**：清一次 `runs/`（先备份），从双击开始完整走一遍两件衣服，记四个点：双击到窗口出现、放图到点开始、点开始到第一张出图、两件跑完。写进 README 新的一节「一次演示要多久」。

顺手把演示要用的图放一个固定文件夹（不放相册里翻），这是 SOP 不是代码。

---

## 四、P1：别人能把仓库跑起来（一天）

这一层服务的是"仓库本身是作品"。面试官点开 GitHub，想自己跑一遍，卡住就永远不会跑第二次。

**做完的结果（2026-10-30）：**

- P1-1 样例图：用本地 Qwen-Image 生成了 8 张（2 人像 + 6 件衣服，共约 800KB），`samples/` 随仓库分发。实测五项全过：人脸 0.85 / 0.79、身体区域变化 79% / 61%、手 2 只（复核 0.92-0.99）、背景距离 9 / 4，单张 56-58 秒。原来那 7 张商品照挪进 `bench/`，`regression.py` 改读 `bench/`，基线数字不变。
- P1-2 `requirements.txt`：文件头写清"用 ComfyUI 那个 python 就不用装"，torch 装 CPU 版够用。
- P1-3 CI：`.github/workflows/check.yml` 跑 `tools/check.py --fast`。先在干净 venv 里验过：只装 pillow / numpy / opencv-python-headless，5/5 通过，不需要模型和 GPU。README 顶部加了 badge。
- P1-4 两处过期引用修好（`parse_clothes` 的路径在 README 和 models/README 里各一处，`test_pipeline_escape.py` 换成 `tools/tests/test_runner.py`）。
- 验收：在 `%TEMP%` 里 clone 一份、拷进 `models/`、改端口起服务，点「载入示例看看」，两张全出图、都通过，第一张 55.9 秒，页面无报错。带全模型再跑一次，五项检查都有实测值。

### P1-1 换一套自己能用的样例图，旧图挪进 `bench/`

**为什么**：现在 `samples/` 里那 7 张是网上的商品照，带水印、有版权，所以被 gitignore 了。结果是仓库作为作品缺了最直观的一块：点进去看不到能用的输入。

**做什么**：

1. 用本地 Qwen-Image 生成一套：2 张人像（正面、能看清双手、脸清晰）+ 6 件衣服，覆盖现有的四种版式（标准购物照、两件拼一起、贴边特写、平铺白底）。人像要选"手在明显位置"的，不然手部质检在这一套上会随机返回 null。
2. 公开图放 `samples/`，进版本库。`.gitignore` 删掉 `samples/*` 和 `!samples/README.md`，换成 `bench/*`。
3. 现有的 6 张（2 人像 + 4 衣服）挪到 `bench/`，继续当回归输入。`tools/regression.py` 和 `tools/check.py:63` 的路径跟着改。
4. 重写 `samples/README.md`：这些图是本地模型生成的，可自由使用；回归那 8 组在 `bench/`，不随仓库分发，想复现换成自己的 8 组。

**为什么不直接拿公开图重跑基线**：README 和 ROADMAP 里四十多个数字都是这 8 张量出来的，换图就得全部重写，而且新图很可能更差（比如手部失败率上去）。数字是这个项目最值钱的部分，不值得为目录整齐冒这个险。

**验收**：在 `%TEMP%` 里 clone 一份，按 README 下模型，起服务，点「载入示例看看」，两张图就位。

### P1-2 `requirements.txt`（30 分钟）

**为什么**：现在依赖写在 README 一句话里（"PIL / numpy / cv2 / torch / transformers 那个环境里都有"），这句话对别人不成立。

**做什么**：列出来，文件头写清楚两件事：直接用 ComfyUI 那个 python 的话这个文件不用装；单独建环境的话 torch 要装 CPU 版就够（判定和解析都不吃 GPU）。

**验收**：干净 venv 里 `pip install -r requirements.txt` 之后 `python tools/check.py --fast` 全绿。

### P1-3 CI：`.github/workflows/check.yml`（1 小时，含踩坑）

**为什么**：仓库顶上有个绿色徽章，是"这人知道工程怎么做"最便宜的信号。而且以后每次改完不用记得手跑。

**做什么**：ubuntu + python 3.12，装依赖，跑 `tools/check.py --fast`（编译 + 依赖方向 + 配置入口 + 单测）。判定冒烟要 onnx 模型，模型不在仓库里，必须跳过，所以只能 `--fast`。

**先验证再写**：本地建个 venv 装最小依赖，确认 `--fast` 在没有模型、没有 torch 的情况下能过。过不了就把 CI 缩到 `py_compile` + 依赖方向两条，仍然有徽章。README 顶部加 badge。

**风险**：`tools/tests/test_runner.py` 可能间接 import cv2。真是这样就装 `opencv-python-headless`，40MB，可接受。

### P1-4 修两处过期引用（10 分钟）

- `README.md:345` 写的是 `app/parse_clothes.py`，实际在 `app/capability/prep/parse_clothes.py`。
- `ROADMAP.md:57` 引用 `tools/test_pipeline_escape.py`，那个文件已经不存在（内容并进了 `tools/tests/test_runner.py`）。
- 顺手清 `tools/__pycache__/test_pipeline_escape.cpython-312.pyc` 这个残留。

这种错面试官不会当面说，但会让"这人自己没回头看过文档"的印象落地。

---

## 五、P2：有余力再做（每件上限 3 小时）

面试前如果还有空档，按这个顺序。

### P2-1 给判定层补测试（`tools/tests/test_rules.py`，约 100 行）

591 行零测试，是这个项目工程叙事上最大的洞。测试不用加载模型：直接喂构造好的相似度、变化比例、手数、背景色差，验证 5 项判据在阈值两侧的行为（0.45 上下、20% 上下、手数相等/不等、色差 30 上下）。跑 0.1 秒，进 `check.py` 的单测那项。

### P2-2 取消任务

`state.py` 加 `cancel(job_id)`，`pipeline/runner.py` 在每轮尝试开始前查一次标记，`routes/jobs.py` 加 `POST /api/cancel`，页面「停下」。约 60 行。要说清楚的是：已经在 ComfyUI 里跑的那一张停不掉，只能等它返回再放弃。

### P2-3 架构图 + 60 秒录屏

README 现在只有 ASCII 流程图。一张四包单向依赖的图（`archify` 能出 SVG）比十行文字有效。再加一段 60 秒录屏转 GIF（控制在 5MB 内），给不看现场的人。

### P2-4 手部定向改进实验

唯一能把"我发现了弱点"升级成"我解决了弱点"的动作，也是唯一可能白干的。上限：3 小时 + 两次八组回归（26 分钟 GPU）。三种打法：base 指令里加手部完整描述、refine 子句里加手部专用约束、escape 时把 cfg 抬得更高。

没效果也有价值：把"试过什么、为什么没用"写进 README，比单纯写"手 75%"更像做过工程。

---

## 六、明确不做

- **nsis 安装包**。现场用自己的笔记本，`dist/win-unpacked/换装验收台.exe` 双击就能起。`npm run dist` 两次卡死在打包阶段（CPU 接近零、无输出），继续投入的回报最低。
- **云端后端实测**。没有真 key，也不想为一次验证花钱。保留 README 里"接口形状按 OpenAI images/edits 写的、未用真实 key 验证"的说法，这是诚实的写法。
- **队列调度 / 多任务并发**。单机独占 GPU，演示不会触发。README 已知限制里已经写了，等于说过。
- **多后端切换 UI、登录、计费**。跟"给完全不懂的人用两张图"这个定位无关，加了反而是减分。

---

## 七、纪律

改任何跟生成或判定有关的代码前后，三道闸门跑一遍：

```
D:\Comfyui\python\python.exe tools\check.py
D:\Comfyui\python\python.exe tools\replay.py --quiet      # 期望翻转 0 项
D:\Comfyui\python\python.exe tools\api_baseline.py check  # 需要服务在跑
```

动到生成、判定、裁剪的，再跑八组回归（13 分钟）和 `compare reports/base.json reports/after.json`。

一次只改一件，改完立刻跑闸门；提交走 `D:\Godot\tools\git\cmd\git.exe`，提交后钩子自动推。

推不上去先看代理：国内站通、GitHub 全挂就是节点断了，让人重启代理客户端，别去改仓库配置。

---

## 八、顺序

P0 今晚 → P1 明天 → P2 面试前有空档再说。

P0 排在最前面的理由很直接：投递已经在进行，最坏情况明天就要演示。P1 可以慢一天，因为它服务的是"别人看仓库"，不是"当场翻车"。
