# coding agent

一个用 Python 编写的 AI 编程助手（coding agent）：与厂商无关的 LLM 流式输出、带文件与 Shell 工具的有状态 agent 循环，以及一个浏览器 UI,根据SWE-bench Lite构建回归测试集（评测集选择中低难度评测样例）。


## 项目结构

单一包 `packages/coding`，作为 `uv` workspace 成员发布。

| 模块 | 作用 |
|------|------|
| `coding.ai` | 基于 OpenAI 兼容 API 的 LLM 流式输出，以及厂商预设和环境变量密钥查找 |
| `coding.agent` | 有状态 agent 循环：工具执行、运行中干预、后续消息 |
| `coding.core` | 编程助手：工具、会话、上下文压缩、扩展、设置、工具审批 |
| `coding.web` | FastAPI + WebSocket UI，会话由 SQLite 支撑 |

`coding.web` 把 `coding.core` 的会话接到 `coding.agent` 循环上，后者通过 `coding.ai` 进行流式输出。每个模块只依赖该链条中排在它之前的模块。

## 工具

`bash`、`read`、`write`、`edit`、`grep`、`find`、`ls`。

高风险调用可以先征得用户同意。当 `approvalMode` 设为 `ask` 时，Shell 命令、工作区外的写入以及未识别的工具会在运行前询问；只读工具则永不询问。拒绝会作为错误工具结果返回给模型，因此运行会继续而不是中断。Web UI 会在工具卡片上渲染允许/拒绝控件。

## 快速开始

需要 Python 3.14+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone <repo> && cd coding
uv sync --all-packages
```

`--all-packages` 很重要：workspace 根目录是一个虚拟项目，因此单纯的 `uv sync` 会把该包及其依赖从环境中清除掉。

运行测试：

```bash
uv run pytest packages/coding/tests
```

## 运行

Web UI：

```bash
coding-web                      # http://127.0.0.1:8000
```

Web UI 故意绑定到回环地址：这些工具赋予它的文件系统访问权限与直接在本地运行相同，因此对外暴露必须显式指定 `--host`。

## 状态存放位置

| 路径 | 内容 |
|------|------|
| `~/.coding/settings.json` | 全局设置 |
| `<project>/.coding/settings.json` | 项目设置，覆盖全局设置 |
| `~/.coding/sessions/<encoded-cwd>/` | 会话记录 |
| `~/.coding/extensions/`、`<project>/.coding/extensions/` | 扩展 |
| `~/.coding/models.json` | 自定义模型定义 |
| `~/.coding/web-ui.db` | Web UI 会话、厂商密钥、审批模式 |

API 密钥从厂商对应的环境变量读取（`OPENAI_API_KEY`、`DEEPSEEK_API_KEY`、`GROQ_API_KEY` 等），或通过 Web UI 的设置对话框存储。自定义的 OpenAI 兼容端点回退到 `CODING_API_KEY`。

## 回归测试集与消融实验

### 回归测试集

基于 SWE-bench Lite 选取 100 道评测样例构建回归评测集，以中低难度样例为主，用于验证 agent 在真实代码修复任务上的基础能力，以及版本迭代过程中的性能回归情况。

### 消融实验：上下文模块

针对上下文记忆压缩与摘要模块设计消融对比实验，设置两组对照：

- **当前版本**：启用记忆压缩与摘要的完整版本
- **无压缩版本**：移除记忆压缩与摘要模块，保留原始完整上下文

两组分别在同一回归评测集上各运行 2 遍，取平均值进行对比，评估维度如下：

| 评估维度 | 说明 |
|---------|------|
| 评测得分 | SWE-bench 任务解决率 |
| Token 消耗 | 单次任务平均 token 用量 |
| 运行时间 | 单次任务平均耗时 |

> **当前状态**：实验仍在进行中，已完成少量样例的初步运行，完整 100 道评测集尚未全部跑完，后续将补充完整数据与对比结论。



