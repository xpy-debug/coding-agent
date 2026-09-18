# coding

An AI coding agent written in Python: provider-agnostic LLM streaming, a stateful
agent loop with file and shell tools, a CLI, and a browser UI.

Restructured from the original project at https://github.com/badlogic/pi-mono.

## Layout

A single package, `packages/coding`, published as a `uv` workspace member.

| Module | What it does |
|--------|--------------|
| `coding.ai` | LLM streaming over OpenAI-compatible APIs, plus vendor presets and environment key lookup |
| `coding.agent` | Stateful agent loop: tool execution, mid-run steering, follow-up messages |
| `coding.core` | Coding agent: tools, sessions, context compaction, extensions, settings, tool approval |
| `coding.web` | FastAPI + WebSocket UI with SQLite-backed sessions |
| `coding.cli` | Command-line entry point |

`coding.cli` and `coding.web` wire `coding.core` sessions onto the `coding.agent`
loop, which streams through `coding.ai`. Each module only depends on the ones
listed before it in that chain.

## Tools

`bash`, `read`, `write`, `edit`, `grep`, `find`, `ls`.

High-risk calls can require the user's consent first. With `approvalMode` set to
`ask`, shell commands, writes outside the workspace, and unrecognized tools ask
before running; read-only tools never do. A denial comes back to the model as an
error tool result, so the run continues instead of dying. The web UI renders the
allow/deny controls on the tool card.

## Quick start

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo> && cd coding
uv sync --all-packages
```

`--all-packages` matters: the workspace root is a virtual project, so a plain
`uv sync` prunes the package and its dependencies from the environment.

Run the tests:

```bash
uv run pytest packages/coding/tests
```

## Running

CLI, print mode (non-interactive — there is no REPL yet):

```bash
coding "summarise this repository"
```

Web UI:

```bash
coding-web                      # http://127.0.0.1:8000
```

The web UI is bound to loopback on purpose: the tools give it the same
filesystem access as the CLI, so exposing it must be an explicit `--host`.

## Where state lives

| Path | Contents |
|------|----------|
| `~/.coding/settings.json` | Global settings |
| `<project>/.coding/settings.json` | Project settings, overriding global |
| `~/.coding/sessions/<encoded-cwd>/` | Session transcripts |
| `~/.coding/extensions/`, `<project>/.coding/extensions/` | Extensions |
| `~/.coding/models.json` | Custom model definitions |
| `~/.coding/web-ui.db` | Web UI sessions, provider keys, approval mode |

API keys are read from the provider's environment variable (`OPENAI_API_KEY`,
`DEEPSEEK_API_KEY`, `GROQ_API_KEY`, ...) or stored through the web UI settings
dialog. Custom OpenAI-compatible endpoints fall back to `CODING_API_KEY`.

## Extensions

An extension is a `.py` file (or a package directory) exposing a factory that
receives the extension API:

```python
def extension(coding):
    coding.on("tool_call", block_dangerous_commands)
```

They are discovered in `~/.coding/extensions/`, then
`<project>/.coding/extensions/`, then any explicitly configured paths.

## License

MIT License. Copyright (c) Vamsi Kurama.
