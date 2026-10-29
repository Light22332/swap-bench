# 工程整理计划

这份文档管的是代码形状，不是功能。六轮迭代里每轮都加了一个能力（手部质检、参考图裁剪、降级重跑），加完就走，没有回头整理。现在 4654 行、30 个文件，职责开始互相伸手。这份计划把目标结构、迁移顺序和验收办法定下来，之后按阶段执行。

已定的四个方向（2026-10-29 确认）：

1. 允许顺带改行为，包括 JSONL 字段名和结构
2. 后端切成 `core / capability / pipeline / api` 四个包，不引 Web 框架
3. 前端拆成浏览器原生 ES 模块，不做构建
4. 验收靠纯函数单测 + 一键检查脚本 + 历史回放对比

---

## 一、现状体检

按行数排，问题集中在五个文件：

| 文件 | 行数 | 现在干的事 | 问题 |
|---|---|---|---|
| `web/style.css` | 769 | 全部样式 | 单文件，改一处要全文搜类名 |
| `web/app.js` | 610 | 状态、请求、渲染、事件 | 全局 `S` 贯穿，没有模块边界 |
| `app/server.py` | 405 | 路由、静态文件、上传、任务表、配置读写、指标 | 一个 `Handler` 类二十多个方法 |
| `app/judge/hands.py` | 251 | 模型加载、检测、后处理 | 算法部分，可以接受 |
| `app/pipeline.py` | 224 | 编排 + 重试策略 + 降级策略 + 挑最优 + 记录格式 | 策略无法单独测，测一次要跑整个 `run_job` |
| `app/judge/rules.py` | 213 | 四项判定实现 + 阈值常量 + 说明文案 | 阈值埋在实现里，调阈值要读代码 |
| `app/prep.py` | 165 | 三档裁剪决策 + 裁剪 + 依赖人脸检测和人像解析 | 判定层的 `faces` 被裁剪层反向引用 |
| `app/judge/vlm.py` | 123 | VLM 判定（HTTP 调多模态模型） | **死代码**，没有任何地方 import |

五个具体问题：

**1. 依赖方向反了。** `prep.py` 为了判断"图里有没有人脸"去 import `judge.faces`；`pipeline.py` 为了判断"这一项是不是关键项"去 import `judge.base.CHECK_INDEX`。编排层伸手进了判定层的内部表。

**2. 策略和 IO 搅在一起。** "什么时候重试、什么时候降级、什么时候停、最后挑哪张"这四件事写在 `run_job` 的 for 循环里，和调后端、写 JSONL 交错。改一条策略要有 GPU 才能验证。

**3. 配置默认值有两个来源。** `config.json` 里一套，代码里 `config.get("x", 默认)` 又一套，散在六处以上。两边改不同步时，行为取决于哪个先跑。

**4. 死代码和未验证代码。** `judge/vlm.py` 123 行没人调用；`adapters/cloud.py` 从没跑通过；`judge.base.DROPPED` 只出现在注释里。

**5. 前端没有边界。** 上传、轮询、渲染、事件全在一个文件，改一个渲染函数要翻 600 行确认副作用。

---

## 二、目标结构

```
app/
  core/                契约层：不 import 任何算法，也不 import 上层
    models.py          Job / Case / Attempt / Verdict 的数据形状（Phase 2 迁入）
    checks.py          5 项检查的定义：key、权重、是否关键、失败时的修法文案
    config.py          config.json 的读取、默认值、校验（唯一来源）
    store.py           JSONL 读写，带 schema_version
    paths.py           项目内路径解析（runs/ outputs/ models/ 各在哪）
  capability/          能力层：每个模块都能脱离流水线单独调用
    generate/
      graph.py         ComfyUI API 图
      comfyui.py       本地后端
      cloud.py         云端后端（保留，标注未验证）
    judge/
      faces.py         人脸检测与比对
      hands.py         手掌检测与关键点复核
      rules.py         逐项判定
    prep/
      parse_clothes.py 人像解析
      crop.py          三档裁剪决策
  pipeline/            编排层：只依赖 core 和 capability 的公开接口
    policy.py          decide(...) -> accept / refine / escape / stop，纯函数
    select.py          best(tried) -> 第几次最好，纯函数
    runner.py          串起来跑：调后端、调判定、落 JSONL
  api/                 HTTP 层：只管请求解析和响应
    server.py          骨架：ThreadingHTTPServer + 路由注册
    routes/
      config.py  upload.py  run.py  job.py  static.py
    jobs.py            在跑任务的内存表（锁、查询、清理）
  cli.py               `python -m app` 的入口
web/
  index.html
  css/                 tokens.css  base.css  layout.css  bench.css  docket.css
  js/
    api.js             所有 fetch 收在这里
    state.js           S 与它的读写
    upload.js          选图、拖放、转 base64
    run.js             提交、轮询、合并进度
    render.js          rail / sheet / docket / metrics 四块渲染
    main.js            启动与事件绑定
tools/
  check.py             一键检查（单测 + 编译 + 冒烟）
  replay.py            历史回放对比
  tests/               test_policy.py  test_select.py  test_crop.py  test_rules.py
```

依赖方向只有一条：`api → pipeline → capability → core`。

两条硬规矩，写进 `tools/check.py` 里自动检查：

- 任何文件不得 import `app.api`
- `core/` 不得 import `app.capability`、`app.pipeline`、`app.api`

同一层内可以互引：`prep/crop.py` 调 `judge/faces.py` 判断有没有脸，这属于能力之间协作，不算反向依赖。现在的别扭感来自 `prep.py` 在包根、`judge` 在子包，看起来像跨层；挪进 `capability/` 就平了。

---

## 三、契约与行为变更

既然允许顺手改行为，这次一起把契约定下来。下面四条是**会变**的东西，其余接口保持原样。

**1. JSONL 加 `schema_version: 2`。** 现在同一个词 `mode` 有两种含义：一次尝试的打法（base/refine/escape），和质检的模式（local/vlm）。第 2 项已经在记录里改名成 `judge_mode`，字段本身还叫 `mode`。schema 2 统一为：

```json
{"schema": 2, "job": "id", "stage": "judge", "case": 1, "attempt": 2,
 "mode": "escape", "judge_mode": "local", "ts": "..."}
```

读旧文件时按 `schema` 缺失判定为 v1，走兼容分支。`tools/replay.py` 和页面深链都要能读 v1。

**2. 删掉 `judge/vlm.py`。** 它从没被接进 `make_judge`，也没有测试。删之前记下它最后的 commit，需要时从历史取回。

**3. `DROPPED` 并进 `checks.py` 的注释。** 这个常量只出现在两处文档字符串里，留着反而让人以为有代码在用。

**4. 配置默认值集中到 `core/config.py`。** `config.json` 只放用户可调的项，代码里缺键时的默认值只写一次，并带注释说明为什么是这个数。

`cloud.py` 保留，但文件头加一行"未用真实 key 验证过"，和 README 里已有的说法对齐。

---

## 四、执行阶段

每个阶段一个 commit，commit message 写阶段号和验收结果。任何阶段完成后程序都能跑。

### Phase 0 先搭安全网（不改一行业务代码）

现在只有 `tools/test_pipeline_escape.py` 一个测试，而且它跑的是整条 `run_job`。重构之前先有"没改坏"的证据，否则后面每一步都是盲改。

要做两件事：

- `tools/replay.py`：读 `runs/*.jsonl`，对每次尝试重跑当前的判定，逐项对比历史记录里的 `checks`，输出新增项、消失项、翻转项三个列表。
- `tools/check.py`：一条命令做完——`py_compile` 全部模块、跑 `tools/tests/`、跑一次判定冒烟（挑三张图，不需要 GPU 和 ComfyUI）。

**验收**：10 个历史 job 全部能回放。差异里只允许出现"新增项"——历史记录里没有 `hand_preserved`，重跑会多出来，这是预期的。翻转项必须逐条解释。

**这条验收不是形式。** 历史记录是旧代码写的，重跑是新代码，`hand_preserved` 那类新增必然出现；真正的信号是"以前判过的项现在判反了"。

### Phase 1 core 包

挪 `checks.py`（原 `judge/base.py` 的检查表）、`store.py`、路径解析，新建 `config.py` 收拢默认值。

**验收**：`tools/check.py` 全绿；全仓搜索 `config.get(`，只剩 `core/config.py` 一处。

### Phase 2 策略纯函数化

把 `run_job` 里的四个判断抽出来：

- `policy.decide(attempt, verdict, cfg) -> "accept" | "refine" | "escape" | "stop"`：什么时候停、什么时候加约束重来、什么时候降级。
- `select.best(tried) -> index`：按"先看通过、再看分数"挑。

`runner.py` 只留"调后端 → 调判定 → 交给 policy → 落记录"。

**验收**：现有 17 条断言改写成针对纯函数的断言，另加三条——降级后仍不过要停、非关键项不过不重试、`escape_attempts=0` 时不降级。

### Phase 3 capability 包

三块归位：`generate/`（graph + comfyui + cloud）、`judge/`（faces + hands + rules）、`prep/`（parse_clothes + crop）。删 `vlm.py`。

**验收**：回放 diff 与 Phase 0 基线一致。这一步只挪文件，diff 出现任何变化都说明挪错了。

### Phase 4 api 包

`server.py` 拆成骨架加五个路由模块，任务表独立成 `jobs.py`。

**验收**：改造前先把五个接口的响应录成基线文件，改完用脚本逐个比对键集合：`/api/config`、`/api/upload`、`/api/samples`、`/api/run`、`/api/job/{id}`、`/img`。

### Phase 5 前端 ESM

`app.js` 按职责拆六个模块，`style.css` 按用途拆五个。浏览器原生 `import`，不做构建。

**验收**：手工走五条路径——首屏渲染、放两张图、点开始出结果、打开已有 job 深链、刷新后进度恢复。DOM 结构保持不变，改的只是文件组织。

---

## 五、总验收标准

1. `python tools/check.py` 一条命令全绿，60 秒内跑完，不需要 GPU 和 ComfyUI
2. `python tools/replay.py` 对 10 个历史 job 给出可解释的 diff，翻转项为零或逐条有说明
3. 六个 HTTP 接口的响应键集合与改造前基线一致
4. 前端五条路径手工过一遍
5. 每条 import 都符合 `api → pipeline → capability → core` 的单向依赖，由 `tools/check.py` 自动校验

---

## 六、不做的事

- 不换 FastAPI 或任何 Web 框架。零依赖的 `ThreadingHTTPServer` 是这个项目的卖点之一，换掉等于用一张依赖清单换几十行代码。
- 不上前端构建工具。双击就能跑比模块热更新重要。
- 不引入数据库。JSONL 已经够用，而且它是"证据可查"这个卖点的一部分。
- 不动 Electron 外壳。219 行，职责清楚，改它没有收益。
- 不做全量类型标注和 mypy。公共接口加注解，内部函数不加，按现在的体量这个折中更划算。

---

## 七、风险

**回放依赖历史图片。** `outputs/` 和 `runs/` 都在 `.gitignore` 里，换了机器就回放不了。`tools/replay.py` 遇到缺图时跳过并在报告里写明，不把"缺图"算成失败。

**重构期间服务不能停太久。** 每阶段结束都要能启动。Phase 3 挪文件时最危险，所以它前面必须先有 Phase 0 的回放基线。

**前端拆分容易漏事件绑定。** `style.css` 拆成五个文件后，加载顺序会影响层叠。做法是保留原顺序，按原文件中的段落顺序切，不重排。

**删除 `vlm.py` 前记 commit。** 删掉的那次 commit 号写进本文件，需要时能取回。

---

## 八、顺序和体量

| 阶段 | 改动面 | 预计 | 风险 |
|---|---|---|---|
| 0 安全网 | 新增 2 个工具 + 测试目录 | 1 轮 | 低 |
| 1 core | 挪 3 个文件、新建 config | 1 轮 | 低 |
| 2 策略 | 重写 pipeline 的循环 | 1–2 轮 | 中，逻辑要逐条对齐 |
| 3 capability | 挪 8 个文件、删 1 个 | 1 轮 | 中，import 路径全改 |
| 4 api | 拆 405 行 | 1–2 轮 | 中，接口不能变 |
| 5 前端 | 拆 1379 行 | 1–2 轮 | 低 |

Phase 0 和 1 不改变任何行为，可以放心做；Phase 2 是唯一需要仔细对齐逻辑的一步；Phase 3–5 是搬家和拆分，靠回放和接口基线兜底。

---

## 九、执行记录

**Phase 0 完成（2026-10-29）**

- `tools/check.py`：编译 + 依赖方向 + 单测 + 判定冒烟，6 项全绿，2.0 秒
- `tools/replay.py`：复判 20 次尝试，新增 4 项（都是后来才有的 `hand_preserved`），消失 0，**翻转 0**，跳过 6 处（历史图片已删）
- 基线：翻转数为 0，后续每个阶段都拿这个数对

**Phase 1 完成（2026-10-29）**

- 新增 `app/core/`：`checks.py`（原 `judge/base.py`）、`config.py`、`paths.py`、`store.py`（原 `app/store.py`）
- 配置默认值收到 `core/config.py` 一处。`tools/check.py` 加了「配置只从 core.config 取」这项检查，别处再写 `cfg.get(键, 默认)` 会直接报红
- `paths.py` 收掉了 server 里重复的 `ROOT/WEB/UPLOADS` 和两个路径穿越防护函数
- 验收：`check.py` 7/7 全绿（新增配置入口一项）；`replay.py` 仍是 20 次尝试、**翻转 0**

**Phase 2 完成（2026-10-29）**

- `app/pipeline.py` 变成包：`policy.py`（`mode_for` / `decide`，纯函数）、`select.py`（`best` / `case_state`，纯函数）、`runner.py`（只剩 IO 和记账）
- `Job` / `new_job` 挪进 `core/models.py`
- 单测拆成两份：`tools/tests/test_policy.py` 测策略本身（不碰 IO），`tools/tests/test_runner.py` 用假后端测"策略和记录怎么串"
- 验收：`check.py` 8/8；`replay.py` 仍是 20 次尝试、**翻转 0**——说明抽成纯函数之后判定行为没变

**Phase 3 完成（2026-10-29）**

- `app/capability/` 三个子包：`generate/`（graph + comfyui + cloud + base）、`judge/`（faces + hands + rules）、`prep/`（crop + parse_clothes）
- `app/prep.py` → `capability/prep/crop.py`，`app/parse_clothes.py` → `capability/prep/parse_clothes.py`，`app/graph.py` → `capability/generate/graph.py`
- 删掉 `judge/vlm.py`（123 行死代码，它最后的版本在提交 `489de5d7` 之前）
- 相对 import 从两级变三级（`...core`），`tools/check.py` 的依赖检查扩成整条链：core 不许往上、capability 不许引 pipeline/api
- 验收：`check.py` 8/8；`replay.py` 20 次尝试、**翻转 0**；服务重启后 `/api/config` 正常




