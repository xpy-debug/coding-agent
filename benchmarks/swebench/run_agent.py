"""Generate SWE-bench patches by driving the coding-web agent over its WebSocket.

Runs on the host with the coding-web virtualenv. It does NOT import the coding
package: it talks to `coding-web` exactly the way the browser UI does, so what
gets measured is the web agent's real code path.

Two product facts shape this file:

* `AgentManager` takes its workspace from the server process's own cwd (and only
  a persisted DB setting can override it), and there is no `set_workspace`
  message in the protocol. So each instance gets its own server process, started
  with `cwd=<checkout>` and a throwaway database.
* The agent loop has no turn cap, so the budget and the wall-clock timeout here
  are the only thing standing between a confused run and a large bill.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

HEALTH_TIMEOUT = 90.0
ABORT_GRACE = 30.0
BOOT_POLL = 0.25
CONFIGURE_TIMEOUT = 120.0
# How long to let the server persist a session after the socket closes. It saves
# as part of its disconnect handling, so stopping the process immediately would
# drop the conversation and leave nothing to browse.
SESSION_PERSIST_TIMEOUT = 15.0

# Test-looking paths are dropped from the patch. Grading replaces the test files
# with the gold test patch, so these changes are discarded regardless, and a
# model patch touching the same file risks making the gold patch fail to apply,
# which scores the instance zero no matter how good the fix was.
TEST_PATH_RE = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$")

PROMPT_TEMPLATE = """\
You are fixing a real bug in the {repo} repository. The repository is checked out at \
commit {base_commit}, and it is your current working directory.

Here is the issue report:

<issue>
{problem_statement}
</issue>

Modify the repository's source code so that the issue is resolved.

Rules:
- Change only non-test source files. Do not create, modify, or delete tests.
- Never run `git commit`, `git checkout`, `git reset`, `git stash`, or anything else \
that rewrites history or discards files.
- Stay inside the repository directory.
- This project's dependencies are probably not installed, so you will not be able to \
run its test suite. Do not spend more than one or two attempts trying; read the code \
and reason instead.
- Make the smallest change that fixes the root cause.
- When you are done, reply with a short summary of what you changed and why.
"""


# --- Process helpers -------------------------------------------------------


def run_cmd(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed ({proc.returncode}):\n{proc.stderr.strip()}")
    return proc


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_cmd(["git", "-C", str(repo), *args])


# --- Repository preparation ------------------------------------------------


def ensure_mirror(repo: str, cache_dir: Path) -> Path:
    """Keep one bare mirror per repository so runs do not re-download django."""
    mirror = cache_dir / (repo.replace("/", "__") + ".git")
    if (mirror / "HEAD").is_file():
        return mirror
    mirror.parent.mkdir(parents=True, exist_ok=True)
    print(f"    cloning mirror for {repo} (first time, this takes a while)")
    run_cmd(["git", "clone", "--mirror", "--quiet", f"https://github.com/{repo}.git", str(mirror)])
    return mirror


def remove_tree(path: Path) -> None:
    """Delete a directory tree, read-only files included.

    git marks its object files read-only. On Windows a plain rmtree fails partway
    through on them and leaves the directory behind, and the next `git clone`
    then refuses a non-empty destination. Clearing the read-only bit and retrying
    is what lets an already-attempted instance be re-run.
    """

    def clear_readonly(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onexc=clear_readonly)


def checkout_instance(instance: dict, work_dir: Path, cache_dir: Path) -> Path:
    """Clone the instance's repo at its base commit into a clean working tree.

    `core.autocrlf=false` is load-bearing on Windows. With the default, checkout
    rewrites every file to CRLF and `git diff` then reports the entire repository
    as changed, producing a patch that can never apply. `core.symlinks=false`
    keeps the tree clean where creating symlinks needs privileges we may lack.
    """
    dest = work_dir / instance["instance_id"]
    if dest.exists():
        remove_tree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    mirror = ensure_mirror(instance["repo"], cache_dir)
    run_cmd(
        [
            "git",
            "clone",
            "--quiet",
            "--no-checkout",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.eol=lf",
            "-c",
            "core.symlinks=false",
            str(mirror),
            str(dest),
        ]
    )
    git(dest, "checkout", "--quiet", instance["base_commit"])

    # A checkout that starts dirty would pollute every patch extracted from it.
    dirty = git(dest, "status", "--porcelain").stdout.strip()
    if dirty:
        raise RuntimeError(f"working tree is dirty right after checkout:\n{dirty[:2000]}")
    return dest


def extract_patch(checkout: Path, drop_tests: bool) -> tuple[str, list[str], list[str]]:
    """Return the working tree's diff, minus test files."""
    git(checkout, "add", "-A")
    changed = [line for line in git(checkout, "diff", "--cached", "--name-only").stdout.splitlines() if line.strip()]
    if drop_tests:
        kept = [path for path in changed if not TEST_PATH_RE.search(path)]
        skipped = [path for path in changed if TEST_PATH_RE.search(path)]
    else:
        kept, skipped = changed, []
    if not kept:
        return "", kept, skipped
    patch = git(checkout, "diff", "--cached", "--", *kept).stdout
    return patch, kept, skipped


# --- coding-web process ----------------------------------------------------


def find_free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 200):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"no free port in [{preferred}, {preferred + 200})")


@dataclass
class Server:
    proc: subprocess.Popen
    port: int

    def stop(self) -> None:
        if self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=15)


def start_server(server_cmd: list[str], checkout: Path, port: int, db_path: Path, log_path: Path) -> Server:
    # Both paths must be absolute. The child runs with cwd=checkout, so a
    # relative --db would have the server create its database *inside the
    # repository* rather than using the seeded one, which both loses the stored
    # credentials and drops a stray file into the diff.
    db_path = db_path.resolve()
    log_path = log_path.resolve()
    cmd = [*server_cmd, "--port", str(port), "--db", str(db_path), "--log-level", "warning"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Redirected to a file rather than a pipe: nobody drains a pipe here, and a
    # full buffer would block the server mid-run.
    with open(log_path, "a", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cmd, cwd=str(checkout), stdout=log, stderr=subprocess.STDOUT)
    return Server(proc=proc, port=port)


def wait_health(server: Server, log_path: Path) -> None:
    url = f"http://127.0.0.1:{server.port}/api/health"
    deadline = time.monotonic() + HEALTH_TIMEOUT
    while time.monotonic() < deadline:
        if server.proc.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:] if log_path.is_file() else ""
            raise RuntimeError(f"coding-web exited with code {server.proc.returncode}:\n{tail}")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(BOOT_POLL)
    raise RuntimeError(f"coding-web was not healthy within {HEALTH_TIMEOUT:.0f}s")


# --- WebSocket driving -----------------------------------------------------


@dataclass
class RunResult:
    stop: str = "unknown"
    turns: int = 0
    tool_calls: int = 0
    errors: list[str] = field(default_factory=list)
    assistant_chars: int = 0
    seconds: float = 0.0


async def _read_until(ws, stop_types: set[str], timeout: float) -> list[dict]:
    frames: list[dict] = []
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"timed out waiting for {sorted(stop_types)}")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            continue
        frames.append(frame)
        if frame.get("type") in stop_types:
            return frames


async def drain_initial(ws, timeout: float = 30.0) -> dict:
    """Consume the state/models/sessions frames the server pushes on connect.

    Returns the two frames we care about. `models` tells us what the server can
    already reach, which is how a seeded database lets us skip credential setup.
    """
    frames = await _read_until(ws, {"sessions"}, timeout)
    models = next((f for f in frames if f.get("type") == "models"), {})
    state = next((f for f in frames if f.get("type") == "state"), {})
    return {"models": models, "state": state}


def registered_models(models_frame: dict) -> set[tuple[str, str]]:
    """Every (provider, model id) the server already knows about."""
    return {
        (provider.get("name", ""), model.get("id", ""))
        for provider in models_frame.get("providers") or []
        for model in provider.get("models") or []
    }


def active_model(state_frame: dict) -> tuple[str, str] | None:
    model = state_frame.get("model") or {}
    if not model.get("id"):
        return None
    return (model.get("provider", ""), model.get("id", ""))


async def configure_model(
    ws,
    *,
    provider: str,
    model_id: str,
    api_key: str,
    base_url: str,
    available: set[tuple[str, str]],
    current: tuple[str, str] | None,
) -> None:
    """Install credentials if needed, then make the requested model active.

    When the server already knows the model (a database seeded with stored
    credentials, say), there is nothing to install and we go straight to
    selecting it.
    """
    if (provider, model_id) not in available:
        if base_url:
            await ws.send(json.dumps({"type": "set_endpoint", "baseUrl": base_url, "key": api_key}))
        else:
            await ws.send(json.dumps({"type": "set_api_key", "provider": provider, "key": api_key, "baseUrl": ""}))
        frames = await _read_until(ws, {"state", "error"}, CONFIGURE_TIMEOUT)
        for frame in frames:
            if frame.get("type") == "error":
                raise RuntimeError(f"configuring the endpoint failed: {frame.get('message')}")

    if current == (provider, model_id):
        return

    await ws.send(json.dumps({"type": "set_model", "provider": provider, "modelId": model_id}))
    frames = await _read_until(ws, {"state", "error"}, CONFIGURE_TIMEOUT)
    for frame in frames:
        if frame.get("type") == "error":
            raise RuntimeError(f"selecting the model failed: {frame.get('message')}")


async def drive(ws, prompt: str, *, max_turns: int, timeout: float, verbose: bool) -> RunResult:
    """Send the prompt and supervise the run to completion."""
    result = RunResult()
    started = time.monotonic()
    await ws.send(json.dumps({"type": "prompt", "text": prompt}))

    abort_reason: str | None = None
    abort_sent_at: float | None = None

    while True:
        now = time.monotonic()
        if abort_reason is None and now - started > timeout:
            abort_reason = "timeout"
            abort_sent_at = now
            await ws.send(json.dumps({"type": "abort"}))
        elif abort_sent_at is not None and now - abort_sent_at > ABORT_GRACE:
            result.stop = f"{abort_reason}_no_agent_end"
            result.seconds = now - started
            return result

        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
        except TimeoutError:
            continue
        except ConnectionClosed:
            result.stop = "connection_closed"
            result.seconds = time.monotonic() - started
            return result

        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            continue

        kind = frame.get("type")
        if kind == "turn_end":
            result.turns += 1
            if verbose:
                print(f"    turn {result.turns}")
            if result.turns >= max_turns and abort_reason is None:
                abort_reason = "turn_budget"
                abort_sent_at = time.monotonic()
                await ws.send(json.dumps({"type": "abort"}))
        elif kind == "tool_start":
            result.tool_calls += 1
            if verbose:
                print(f"    tool: {frame.get('toolName')}")
        elif kind == "message_end":
            message = frame.get("message") or {}
            if message.get("role") == "assistant":
                for block in message.get("content") or []:
                    if block.get("type") == "text":
                        result.assistant_chars += len(block.get("text") or "")
        elif kind in ("error", "api_key_required"):
            result.errors.append(str(frame.get("message") or f"api key required for {frame.get('provider')}"))
            result.stop = kind
            result.seconds = time.monotonic() - started
            return result
        elif kind == "agent_end":
            result.stop = abort_reason or "agent_end"
            result.seconds = time.monotonic() - started
            return result


# --- Orchestration ---------------------------------------------------------


@dataclass
class Options:
    server_cmd: list[str]
    provider: str
    model: str
    api_key: str
    base_url: str
    model_name: str
    max_turns: int
    timeout: float
    concurrency: int
    base_port: int
    exclude_tests: bool
    work_dir: Path
    cache_dir: Path
    logs_dir: Path
    seed_db: Path | None
    session_db: Path
    verbose: bool


def _drop_workspace_setting(db_path: Path) -> None:
    """Remove the persisted workspace override from a database."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("delete from settings where key = 'workspace'")
        conn.commit()
    finally:
        conn.close()


def prepare_db(seed_db: Path | None, dst: Path) -> None:
    """Create the session database, optionally seeded from an existing one.

    Seeding is how stored credentials and a previously configured endpoint get
    reused without the API key ever passing through the command line. The
    `workspace` row is dropped: that setting outranks the server's own cwd, and
    the whole design depends on the cwd deciding the workspace.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        # Already seeded. A database shared across a batch accumulates every
        # run's session, so re-seeding would throw that history away.
        _drop_workspace_setting(dst)
        return
    if seed_db is None:
        return

    source = sqlite3.connect(f"file:{seed_db}?mode=ro", uri=True)
    target = sqlite3.connect(dst)
    try:
        # The backup API rather than a file copy: it reads through the WAL, so
        # a database with unflushed pages still copies consistently.
        source.backup(target)
        target.execute("delete from settings where key = 'workspace'")
        target.commit()
    finally:
        target.close()
        source.close()


def _session_exists(db_path: Path, session_id: str) -> bool:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute("select 1 from session_metadata where id = ?", (session_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


async def wait_for_session(db_path: Path, session_id: str, timeout: float) -> bool:
    """Wait until the server has written this run's session to the database.

    Returns False if it never lands, which is not fatal for the patch but does
    mean the conversation will be missing from the UI.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if await asyncio.to_thread(_session_exists, db_path, session_id):
                return True
        except sqlite3.Error:
            pass
        await asyncio.sleep(BOOT_POLL)
    return False


async def run_one(instance: dict, opts: Options, port: int) -> dict:
    """Check out, drive one agent run, and return the prediction record."""
    iid = instance["instance_id"]
    record: dict = {"instance_id": iid, "model_name_or_path": opts.model_name, "model_patch": ""}
    meta: dict = {"instance_id": iid, "instance": {"repo": instance["repo"], "base_commit": instance["base_commit"]}}

    started = time.monotonic()
    checkout = await asyncio.to_thread(checkout_instance, instance, opts.work_dir, opts.cache_dir)
    meta["checkout_seconds"] = round(time.monotonic() - started, 1)

    # One session database for the whole batch, so the conversations can be
    # browsed afterwards: coding-web --db <session_db> lists every run in the
    # sidebar. Requires --concurrency 1; SQLite writers would contend otherwise.
    db_path = opts.session_db.resolve()
    log_path = (opts.logs_dir / f"{iid}.server.log").resolve()
    await asyncio.to_thread(prepare_db, opts.seed_db, db_path)

    server = await asyncio.to_thread(start_server, opts.server_cmd, checkout, port, db_path, log_path)
    try:
        await asyncio.to_thread(wait_health, server, log_path)
        prompt = PROMPT_TEMPLATE.format(
            repo=instance["repo"],
            base_commit=instance["base_commit"],
            problem_statement=instance["problem_statement"],
        )
        async with connect(f"ws://127.0.0.1:{port}/ws", max_size=None, open_timeout=30) as ws:
            initial = await drain_initial(ws)
            session_id = str(initial["state"].get("sessionId") or "")
            await configure_model(
                ws,
                provider=opts.provider,
                model_id=opts.model,
                api_key=opts.api_key,
                base_url=opts.base_url,
                available=registered_models(initial["models"]),
                current=active_model(initial["state"]),
            )
            result = await drive(ws, prompt, max_turns=opts.max_turns, timeout=opts.timeout, verbose=opts.verbose)

        # If the socket dropped, the server may have died rather than closed the
        # connection. Its exit code is the only clue left after the fact -- a
        # silent death with no traceback usually means the OS killed it, which
        # is what memory pressure looks like on Windows.
        exit_code = server.proc.poll()
        if exit_code is not None:
            meta["server_exit_code"] = exit_code

        # The socket is closed, and the server persists the session as part of
        # its disconnect handling. Let that land before stopping the process.
        persisted = True
        if session_id:
            persisted = await wait_for_session(db_path, session_id, SESSION_PERSIST_TIMEOUT)
        meta.update(
            stop=result.stop,
            session_id=session_id,
            session_saved=persisted,
            turns=result.turns,
            tool_calls=result.tool_calls,
            errors=result.errors,
            assistant_chars=result.assistant_chars,
            agent_seconds=round(result.seconds, 1),
        )
    except Exception as exc:
        # One bad instance must not kill the rest of the batch.
        meta["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await asyncio.to_thread(server.stop)

    patch, kept, skipped = await asyncio.to_thread(extract_patch, checkout, opts.exclude_tests)
    record["model_patch"] = patch
    meta.update(files=kept, skipped_tests=skipped, patch_bytes=len(patch))
    meta["total_seconds"] = round(time.monotonic() - started, 1)
    return {"record": record, "meta": meta}


async def main_async(instances: list[dict], opts: Options, out_path: Path, limit: int | None) -> int:
    if limit is not None:
        instances = instances[:limit]

    done = load_done(out_path)
    pending = [inst for inst in instances if inst["instance_id"] not in done]
    if done:
        print(f"Resuming: {len(done)} instance(s) already in {out_path}")
    if not pending:
        print("Nothing to do.")
        return 0

    print(f"Running {len(pending)} instance(s), concurrency={opts.concurrency}\n")
    semaphore = asyncio.Semaphore(opts.concurrency)
    write_lock = asyncio.Lock()
    failures = 0

    async def worker(index: int, instance: dict) -> None:
        nonlocal failures
        iid = instance["instance_id"]
        port = find_free_port(opts.base_port + index * 3)
        async with semaphore:
            print(f"[{iid}] start ({instance['repo']}) port={port}")
            try:
                outcome = await run_one(instance, opts, port)
            except Exception as exc:
                # A crash here is infrastructure, not a model answer; count it,
                # keep the traceback (the message alone is rarely enough to act
                # on) and keep going so one bad instance cannot sink the batch.
                failures += 1
                detail = traceback.format_exc()
                print(f"[{iid}] FAILED: {type(exc).__name__}: {exc}")
                print(f"    traceback -> {opts.logs_dir / f'{iid}.crash.log'}")
                (opts.logs_dir / f"{iid}.crash.log").write_text(detail, encoding="utf-8")
                return
            async with write_lock:
                with out_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(outcome["record"]) + "\n")
                (opts.logs_dir / f"{iid}.json").write_text(
                    json.dumps(outcome["meta"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
            patch_kb = len(outcome["record"]["model_patch"]) / 1024
            meta = outcome["meta"]
            files = len(meta.get("files") or [])
            if "error" in meta:
                print(f"[{iid}] done: ERROR {meta['error'][:140]} files={files} patch={patch_kb:.1f}KB")
            else:
                print(
                    f"[{iid}] done: {meta.get('stop')} "
                    f"turns={meta.get('turns')} tools={meta.get('tool_calls')} "
                    f"files={files} patch={patch_kb:.1f}KB"
                )

    await asyncio.gather(*(worker(i, inst) for i, inst in enumerate(pending)))
    return failures


def load_done(out_path: Path) -> set[str]:
    """Instance IDs already present in the predictions file, for resuming."""
    if not out_path.is_file():
        return set()
    done: set[str] = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            done.add(json.loads(line)["instance_id"])
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return done


# --- CLI -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drive the coding-web agent over SWE-bench instances and write predictions.jsonl.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--instances", default="instances.json", help="instances.json from select_instances.py")
    parser.add_argument("--out", default="predictions.jsonl", help="Predictions file to append to")
    parser.add_argument("--work-dir", default=".work", help="Where repositories are checked out")
    parser.add_argument("--cache-dir", default=".cache/repos", help="Bare mirror cache, one per repository")
    parser.add_argument("--logs-dir", default="logs/agent", help="Per-instance run metadata and server logs")
    parser.add_argument(
        "--session-db",
        default="logs/agent/sessions.db",
        help=(
            "Session database shared by the whole batch. Browse the conversations with "
            "'coding-web --db <this file>' (needs --concurrency 1)"
        ),
    )

    parser.add_argument("--provider", default="openai", help="Provider id (ignored when --base-url is set)")
    parser.add_argument("--model", required=False, help="Model id, e.g. gpt-4.1")
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key. Falls back to the provider's env var, then CODING_API_KEY.",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Custom OpenAI-compatible endpoint. Sets the model via the 'custom' provider.",
    )
    parser.add_argument(
        "--seed-db",
        default=None,
        help=(
            "Existing coding-web database to copy per instance. Reuses stored provider "
            "credentials and the configured endpoint, so --api-key is not needed "
            "(default: ~/.coding/web-ui.db is used when it exists and no key is given)"
        ),
    )
    parser.add_argument("--model-name", default="coding-web", help="Value written to model_name_or_path")

    parser.add_argument("--max-turns", type=int, default=40, help="Abort the run after this many turns")
    parser.add_argument("--timeout", type=float, default=1200.0, help="Wall-clock seconds per instance")
    parser.add_argument("--concurrency", type=int, default=1, help="Instances in flight at once")
    parser.add_argument("--base-port", type=int, default=8300, help="First port tried for coding-web")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N instances")
    parser.add_argument("--instance-ids", nargs="*", default=None, help="Only run these instance IDs")
    parser.add_argument(
        "--server-cmd",
        default=None,
        help="Command that starts coding-web (default: '<python> -m coding.web.main')",
    )
    parser.add_argument(
        "--keep-tests",
        action="store_true",
        help="Do NOT strip test files from the patch (off by default, and rarely what you want)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only check out the repositories and verify the trees are clean. Starts no agent.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print turns and tool calls as they happen")
    return parser


def resolve_api_key(provider: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    from_env = os.environ.get(f"{provider.upper()}_API_KEY") or os.environ.get("CODING_API_KEY")
    return from_env or ""


def main() -> int:
    args = build_parser().parse_args()

    if not args.model and not args.base_url:
        print("Need --model (and usually --api-key), or --base-url for a custom endpoint.", file=sys.stderr)
        return 2

    # Reuse whatever the UI already stored rather than asking for the key again.
    # Only when nothing was passed explicitly, so an explicit key always wins.
    seed_db: Path | None = None
    if args.seed_db:
        seed_db = Path(args.seed_db).expanduser()
        if not seed_db.is_file():
            print(f"--seed-db {seed_db} does not exist.", file=sys.stderr)
            return 2
    elif not args.api_key and not args.base_url:
        default_db = Path.home() / ".coding" / "web-ui.db"
        if default_db.is_file():
            seed_db = default_db

    instances_path = Path(args.instances)
    if not instances_path.is_file():
        print(
            f"{instances_path} not found. Generate it first:\n  ./docker/run.sh python select_instances.py --count 15",
            file=sys.stderr,
        )
        return 2
    instances = json.loads(instances_path.read_text(encoding="utf-8"))
    if args.instance_ids:
        wanted = set(args.instance_ids)
        instances = [i for i in instances if i["instance_id"] in wanted]
        if not instances:
            print("None of --instance-ids are in the instances file.", file=sys.stderr)
            return 2

    server_cmd = args.server_cmd.split() if args.server_cmd else [sys.executable, "-m", "coding.web.main"]

    opts = Options(
        server_cmd=server_cmd,
        provider="custom" if args.base_url else args.provider,
        model=args.model or "",
        api_key=resolve_api_key(args.provider, args.api_key),
        base_url=args.base_url,
        model_name=args.model_name,
        max_turns=args.max_turns,
        timeout=args.timeout,
        concurrency=max(1, args.concurrency),
        base_port=args.base_port,
        exclude_tests=not args.keep_tests,
        work_dir=Path(args.work_dir),
        cache_dir=Path(args.cache_dir),
        logs_dir=Path(args.logs_dir),
        seed_db=seed_db,
        session_db=Path(args.session_db),
        verbose=args.verbose,
    )
    opts.logs_dir.mkdir(parents=True, exist_ok=True)

    if args.concurrency > 1:
        print(
            "Warning: --concurrency > 1 with a shared --session-db makes the servers "
            "contend for one SQLite file; sessions may be dropped.",
            file=sys.stderr,
        )

    if args.dry_run:
        return run_dry(instances, opts, args.limit)

    if seed_db is not None:
        print(f"Reusing credentials from {seed_db}")
    elif not opts.api_key and not opts.base_url:
        print(
            f"Warning: no API key resolved for provider '{args.provider}'. The run will stop at 'api_key_required'.",
            file=sys.stderr,
        )

    failures = asyncio.run(main_async(instances, opts, Path(args.out), args.limit))
    total = len(instances) if args.limit is None else min(args.limit, len(instances))
    print(f"\nDone. {total - failures}/{total} instances produced a record -> {args.out}")
    print("Next (grading needs Docker and your key is not involved):")
    print("  ./docker/run.sh ./evaluate.sh")
    return 0


def run_dry(instances: list[dict], opts: Options, limit: int | None) -> int:
    """Checkout-only pass: proves cloning and clean-tree detection work."""
    if limit is not None:
        instances = instances[:limit]
    bad = 0
    for instance in instances:
        iid = instance["instance_id"]
        try:
            checkout = checkout_instance(instance, opts.work_dir, opts.cache_dir)
            dirty = git(checkout, "status", "--porcelain").stdout.strip()
            if dirty:
                bad += 1
                print(f"[{iid}] DIRTY TREE:\n{dirty[:500]}")
            else:
                print(f"[{iid}] clean checkout at {instance['base_commit'][:10]}")
        except Exception as exc:
            bad += 1
            print(f"[{iid}] FAILED: {type(exc).__name__}: {exc}")
    print(f"\n{len(instances) - bad}/{len(instances)} clean.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
