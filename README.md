# coding

一个用 Python 编写的 AI 编程助手（coding agent）：与厂商无关的 LLM 流式输出、带文件与 Shell 工具的有状态 agent 循环、一个 CLI，以及一个浏览器 UI。

重构自原始项目 https://github.com/badlogic/pi-mono。

## 项目结构

单一包 `packages/coding`，作为 `uv` workspace 成员发布。

| 模块 | 作用 |
|------|------|
| `coding.ai` | 基于 OpenAI 兼容 API 的 LLM 流式输出，以及厂商预设和环境变量密钥查找 |
| `coding.agent` | 有状态 agent 循环：工具执行、运行中干预、后续消息 |
| `coding.core` | 编程助手：工具、会话、上下文压缩、扩展、设置、工具审批 |
| `coding.web` | FastAPI + WebSocket UI，会话由 SQLite 支撑 |
| `coding.cli` | 命令行入口 |

`coding.cli` 和 `coding.web` 把 `coding.core` 的会话接到 `coding.agent` 循环上，后者通过 `coding.ai` 进行流式输出。每个模块只依赖该链条中排在它之前的模块。

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

CLI，打印模式（非交互式——目前还没有 REPL）：

```bash
coding "summarise this repository"
```

Web UI：

```bash
coding-web                      # http://127.0.0.1:8000
```

Web UI 故意绑定到回环地址：这些工具赋予它的文件系统访问权限与 CLI 相同，因此对外暴露必须显式指定 `--host`。

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

## 扩展

扩展是一个 `.py` 文件（或一个包目录），暴露一个接收扩展 API 的工厂函数：

```python
def extension(coding):
    coding.on("tool_call", block_dangerous_commands)
```

它们的发现顺序为 `~/.coding/extensions/`，然后是 `<project>/.coding/extensions/`，最后是任何显式配置的路径。

## 许可证

MIT License。Copyright (c) Vamsi Kurama.
