# 用 SWE-bench Lite 评测网页版 Agent

用官方 SWE-bench 给 `coding-web` 这个网页编码 Agent 打分。分成两段：

1. **生成 patch（在宿主机跑）**：`run_agent.py` 对每个实例检出仓库到 base commit，起一个
   `coding-web` 进程，通过 WebSocket 把 issue 交给它，最后从工作区提取 `git diff`，
   写进 `predictions.jsonl`。
2. **打分（在 Docker 里跑）**：官方 harness 拉取每个实例的预构建镜像，应用你的 patch，
   跑 FAIL_TO_PASS / PASS_TO_PASS，输出 resolved 率。

上面两段互不依赖：生成不需要 Docker，打分不需要你的 API key。

---

## 前提

- **Docker Desktop**，并且把虚拟磁盘调大（官方建议 ≥120GB；只跑 15 条也建议留 40GB 以上）。
- **Python 3.14 venv**（仓库根目录的 `.venv`），用来跑 Agent 和本目录的 `run_agent.py`。
  Agent 侧只需要标准库 + `websockets`，都已具备。
- **一个模型端点的凭据**。任何 OpenAI 兼容端点都行，通过 `--base-url` 接入。
- **（可选但推荐）HuggingFace token**。不配也能跑，但数据集下载会被匿名限速，harness 会一直刷
  `You are sending unauthenticated requests to the HF Hub`。配置一次即可：

  ```powershell
  [Environment]::SetEnvironmentVariable('HF_TOKEN', 'hf_xxx', 'User')   # 新开的终端生效
  ```

  `docker/run.sh` 和 `run.ps1` 会自动把它转发进容器 —— 容器看不到宿主机的环境变量，
  不转发的话 harness 仍然是匿名状态。想临时用也可以只在当前会话
  `$env:HF_TOKEN = 'hf_xxx'` 再跑。

---

## 快速开始

在 `benchmarks/swebench/` 目录下操作。

```bash
cd benchmarks/swebench
```

### 第 0 步：环境自检（强烈建议先做，不花 token）

用 gold 补丁跑一条实例。这一步通了，说明 Docker、镜像拉取、patch 应用、测试执行、判分
整条链路都没问题，后面出问题就一定在 Agent 侧。

```bash
# Windows
.\docker\run.ps1 bash ./validate_gold.sh

# Linux / WSL / macOS
./docker/run.sh bash ./validate_gold.sh
```

第一次会构建 harness 镜像并拉取示例实例的镜像，需要几分钟。

### 第 1 步：抽样

```bash
.\docker\run.ps1 python select_instances.py --count 15
```

产物是 `instances.json`。抽样只影响「跑哪些」，不影响评测正确性，因为 harness 会用同一个数据集
自行加载。`--seed` 固定时结果可复现。

```powershell
# 机器上直接跑（有 HF_TOKEN 就走认证下载）
..\..\.venv\Scripts\python.exe select_instances.py --count 15 --seed 0

# 按仓库或具体 id 挑
..\..\.venv\Scripts\python.exe select_instances.py --instance-ids sympy__sympy-20590 pylint-dev__pylint-5859

# 按难度筛（先看有哪些标签）
..\..\.venv\Scripts\python.exe select_instances.py --list-difficulties
..\..\.venv\Scripts\python.exe select_instances.py --difficulty "1-4 hours" --count 3
```

`--difficulty` 的取值是数据集自带的标注：`<15 min fix`、`15 min - 1 hour`、`1-4 hours`。
注意 **300 条里只有 93 条带标注**，另外 207 条是「未标注」而不是「简单」，所以按难度筛会大幅
缩小可选范围（`1-4 hours` 只有 3 条，想凑 5 条得往下取一档）。

### 第 2 步：让 Agent 生成 patch（在宿主机跑，会花 token）

```bash
# 用 OpenAI 兼容端点。key 也可以放在 OPENAI_API_KEY / CODING_API_KEY 环境变量里。
..\..\.venv\Scripts\python.exe run_agent.py `
    --instances instances.json `
    --model gpt-4.1 `
    --api-key $env:OPENAI_API_KEY `
    --max-turns 40 `
    --timeout 1200

# 或者指向本地/自建的 OpenAI 兼容服务
..\..\.venv\Scripts\python.exe run_agent.py `
    --instances instances.json `
    --base-url http://localhost:8000/v1 `
    --model my-model `
    --api-key dummy
```

会产出 `predictions.jsonl`，以及 `logs/agent/<instance_id>.json` 的逐实例元数据
（Stop 原因、回合数、工具调用数、改了哪些文件）。**整个跑批可断点续跑**：已经在
`predictions.jsonl` 里的 instance_id 会被跳过。

想先看看会改哪些文件、不想花钱，用 `--dry-run`：只做检出并断言工作区干净。

```bash
..\..\.venv\Scripts\python.exe run_agent.py --instances instances.json --model unused --dry-run
```

### 第 3 步：打分

```bash
.\docker\run.ps1 bash ./evaluate.sh
```

结果在 `logs/evaluation/<run_id>/`。harness 会在结束时把汇总打印到终端，同时写下
`results.json`。最省事的读法是这个脚本：

```powershell
..\..\.venv\Scripts\python.exe show_results.py            # 所有 run
..\..\.venv\Scripts\python.exe show_results.py coding-web-v1
```

它会打印 resolved 率，以及每条实例的 FAIL_TO_PASS / PASS_TO_PASS 通过情况；
没通过的会直接列出是哪个测试挂了（`regression:` 表示改坏了已有测试）。

想深挖就看这几个文件：

| 文件 | 内容 |
|---|---|
| `logs/evaluation/<run_id>/results.json` | 官方汇总。注意 `incomplete_ids` 是「数据集里你没提交的」，不是失败 |
| `logs/evaluation/<run_id>/<model>/<instance_id>/report.json` | 逐实例：`resolved` + 每个测试的状态 |
| `.../test_output.txt` | 该实例的原始 pytest 输出，诊断「为什么没通过」看这个 |
| `.../patch.diff` | 实际被评测的那个 patch |
| `.../run_instance.log` | 建容器、应用 patch、跑测试的全过程 |

> **改了 patch 一定要换 `RUN_ID`。** 同一个 run_id 下，已有 `report.json` 的实例会被直接跳过，
> 于是你会读到**旧 patch 的分数**却以为在评新的。要么 `RUN_ID=xxx-v2`，要么先删掉整个
> `<run_id>/` 目录。会话库同理：`predictions.jsonl` 里已有的 instance_id 也不会被重跑。

### 在网页界面里查看对话

每次运行都会把自己那次对话写进 `logs/agent/sessions.db`（由 `--session-db` 指定，整个批次共用一个），
所以可以直接把这个库喂给界面来看：

```powershell
.venv\Scripts\coding-web.exe --port 8000 --db benchmarks\swebench\logs\agent\sessions.db
```

打开 http://127.0.0.1:8000 ，左侧栏就会列出每个实例那次运行，点进去能看到完整的 prompt、
每一步工具调用和最终的回复。`logs/agent/<instance_id>.json` 里另有一份元数据
（回合数、工具调用数、改了哪些文件、是否保存成功）。

注意这个库里的会话是**每个实例各一次运行**，标题就是任务 prompt 的开头，所以按标题区分实例。
因为共用一个 SQLite 文件，`--session-db` 与 `--concurrency > 1` 不兼容。

---

## 每个文件做什么

| 文件 | 在哪跑 | 作用 |
|---|---|---|
| `docker/Dockerfile` | 构建时 | Python 3.11 + 官方 SWE-bench 仓库 + `datasets` + docker CLI |
| `docker/run.sh` / `run.ps1` | 宿主机 | 进 harness 容器的入口，挂载 Docker socket 和工作目录 |
| `validate_gold.sh` | 容器内 | 用 gold 补丁自检链路 |
| `select_instances.py` | 容器内 | 抽样，写 `instances.json`，剔除全部 oracle 字段 |
| `run_agent.py` | **宿主机** | 检出仓库 + 驱动 `coding-web` + 提取 patch |
| `evaluate.sh` | 容器内 | 调用官方 `run_evaluation` |

---

## 怎么读结果

- `resolved` 的实例数就是通过数。**注意分母**：`model_patch` 为空的实例会被 harness
  静默剔除，不会出现在报告里。所以报告里的实例数可能少于你提交的条数，别把 15 当成分母。
- 如果某个实例没进报告，先看 `logs/agent/<instance_id>.json` 的 `stop` 字段：
  `agent_end` 是正常结束，`turn_budget` / `timeout` 是被预算掐断，`api_key_required` 是
  凭据没配好，`connection_closed` 是服务崩了。
- `patch_bytes` 为 0 通常意味着 Agent 什么都没改，或者改动全被测路径过滤掉了
  （见下面的 `--keep-tests`）。

---

## 需要注意的事

- **Agent 没有沙箱。** `coding-web` 的 `bash` 工具就是一个不受限制的 shell，会继承你的环境变量
  （包括你 export 的 API key）。**建议把第 2 步放进 WSL2 或一次性虚拟机里跑。**
- **本期 Agent 跑不了仓库的测试。** 它只能读代码和推理，所以这个分数是**下限**，
  不是模型的真实上限。让它在容器里跑测试是下一步（见「后续」）。
- **`--max-turns` 和 `--timeout` 是唯一的安全阀。** 产品本身没有回合上限，`agent/loop.py`
  是 `while True`。预算设大了就是真金白银，第一次先用小样本估单价。
- **patch 默认剔除测试文件。** 官方打分时会用 gold `test_patch` 覆盖测试文件，所以对测试的改动
  本来就没用；而如果模型 patch 和 gold 改了同一个文件，可能导致 gold patch 应用失败，
  这条实例直接记 0 分。想看全部改动加 `--keep-tests`。
- **新增文件必须不被 `.gitignore` 忽略。** patch 是通过 `git add -A` + `git diff --cached`
  得到的，被忽略的文件不会进 patch。
- **Windows 上的 CRLF。** `run_agent.py` 强制 `core.autocrlf=false` 检出；这是 patch 能被应用
  的关键，不要绕过它。`--dry-run` 里的「工作区干净」断言就是防这个的。Agent 侧的写文件工具也已
  一并修好，见下面「顺带修复的产品缺陷」。
- **有些实例在这个环境下根本评不了，别把它们的失败算在 Agent 头上。** 最典型的是
  `psf/requests`：它的测试依赖真实网络，`TARPIT = "http://10.255.255.1"` 假设「连不可路由
  地址会挂住直到超时」，但在容器里是立刻失败，于是 `test_connect_timeout` 与
  `test_total_timeout_connect` 反向断言失败。**用 gold patch 实测确认过**：这两个测试
  在 gold 上同样挂。判断方法就是拿 `--predictions_path gold` 跑一遍该实例，gold 也
  `resolved=0` 的话，这条实例的分数就没有意义。
- **别改 `run_agent.py` 去驱动 CLI。** `coding` CLI 的 print mode 目前是坏的：
  `cli.py:49` import 了一个不存在的 `coding.ai.registry.get_all_models`，异常被吞掉后永远走
  fallback 分支，`base_url` 被硬编码成 OpenAI 官方地址，`-m/-p` 和 `--api-key` 全部失效。
  这是个独立的真实缺陷，值得单独修。

---

## 后续（Phase 2，本期未实现）

让 Agent 能跑仓库自己的测试。做法是在共享的检出目录上保留 `read` / `write` / `edit`，
但把 `bash` 替换成一个执行 `docker exec -w <workdir> <container> bash -lc <cmd>` 的工具，
打到该实例的官方镜像上。这依赖 Linux 的 bind mount 语义，所以应该跑在 WSL2 里。

---

## 与官方文档的差异

`README_CN.md` 有两处已经过时，本目录以源码为准：

- 官方文档写 `--dataset_name princeton-nlp/SWE-bench_Lite`，但 `run_evaluation.py` 的
  argparse 默认值已经是 `SWE-bench/SWE-bench_Lite`。本目录统一用新组织名。
- 官方文档提到的 `swebench/inference/README.md` 已经 404，仓库里没有 `inference` 目录了。

另外文档说镜像需要 ≥120GB，容易让人以为要本地构建；实际 `create_container()` 是
`images.get()` 失败才 `images.pull()`，即**拉取预构建镜像**，只有传 `--task-repo` 才会构建。

---

## 顺带修复的产品缺陷

搭这个 harness 的过程中发现两个**独立的真实缺陷**，已一并修掉。原计划说「本期不改产品代码」，
这两处属于例外，因为不修的话在 Windows 上跑出来的 patch 是坏的。

### 1. 写文件工具会把整个文件改成 CRLF（严重）

`packages/coding/src/coding/core/tools/write.py` 和 `edit.py` 用
`Path.write_text(content, encoding="utf-8")` 落盘。这个调用的默认 `newline=None` 会把字符串里的
`\n` 翻译成 `os.linesep`，于是：

- Linux/macOS 上写 `\n`，和仓库一致，没问题；
- **Windows 上写 `\r\n`**，而 git 里存的是 LF，结果 `git diff` 把整个文件报成改动，
  产出的 patch 在 Linux 上 `git apply` 必定失败。

更要命的是 `edit.py` 第 66–69 行**特意**把行尾统一成了 `\n`，紧接着的写入又把它们全部变回 CRLF，
等于白做。同一份代码在不同平台上产生不同字节，本身就是 bug。

修法是给两处 `write_text` 加 `newline=""`，让 Windows 与 Linux 行为一致。
并补了 `tests/test_tools.py::test_write_keeps_lf_line_endings` 和
`test_edit_keeps_lf_line_endings` 两个回归测试。

### 2. CLI 的 print mode 完全失效（未修，仅记录）

`packages/coding/src/coding/cli.py:49` 写了 `from coding.ai.registry import get_all_models`，
但 `ai/registry.py` 里没有这个函数（只有 `get_api_provider` / `register_api_provider`）。
`ImportError` 被第 91 行的 `except Exception` 吞掉，于是**永远**走 fallback 分支：
`base_url` 被硬编码成 `https://api.openai.com/v1`，`-m` / `-p` 的模糊匹配和 settings 解析全部失效，
`--api-key` 从未被读取。

本目录不依赖 CLI，所以没有修。但它会让任何想用 `coding -m xxx` 的人踩坑，值得单独处理。
