import os
import json
import asyncio
from decimal import Decimal
# subprocess: only PIPE/DEVNULL constants with fixed-argument exec, never shell=True.
import subprocess  # nosec B404

from src.shared.core.config import CLAUDE_CLI_BIN
from src.shared.core.observability import log

# ==========================================
# ASYNC STREAM CONSUMER UTILITY
# ==========================================
async def stream_subprocess_output(
    prefix: str, stream: asyncio.StreamReader, buffer: list,
    verbose_to_console: bool = False, on_activity=None,
):
    while True:
        line = await stream.readline()
        if not line:
            break
        if on_activity is not None:
            on_activity()                     # feed the inactivity watchdog on every received line
        decoded = line.decode(errors="replace").rstrip()
        buffer.append(decoded)

        # verbose_to_console=True surfaces lines on the console (INFO); otherwise file-only (DEBUG)
        if verbose_to_console:
            log.info(f"{prefix} {decoded}")
        else:
            log.debug(f"{prefix} {decoded}")


def _humanize_stream_event(line: str) -> str | None:
    """Render a single ``--output-format stream-json`` event line as a short progress string, or
    ``None`` to skip it (system/user/result events and unparseable lines stay out of the console).

    Surfaces what the operator needs to SEE the agent working: assistant text (truncated) and the
    tool calls it makes (e.g. ``→ Write src/main.go``). Never raises — visibility is best-effort.
    """
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or obj.get("type") != "assistant":
        return None
    content = (obj.get("message") or {}).get("content") or []
    parts: list[str] = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = " ".join((block.get("text") or "").split())
            if text:
                parts.append(text[:200] + ("…" if len(text) > 200 else ""))
        elif btype == "tool_use":
            name = block.get("name", "tool")
            inp = block.get("input") or {}
            target = inp.get("file_path") or inp.get("path") or inp.get("command") or ""
            target = " ".join(str(target).split())[:80]
            parts.append(f"→ {name} {target}".rstrip())
    return " | ".join(parts) if parts else None


async def stream_claude_stdout(stream: asyncio.StreamReader, raw_buffer: list, on_activity=None):
    """Consume the Claude CLI stream-json stdout: keep every raw line (for usage parsing) and surface
    a condensed, human-readable progress line per assistant event so the session is never a silent
    black box."""
    while True:
        line = await stream.readline()
        if not line:
            break
        if on_activity is not None:
            on_activity()
        decoded = line.decode(errors="replace").rstrip()
        raw_buffer.append(decoded)
        summary = _humanize_stream_event(decoded)
        if summary:
            log.info(f"   [Developer Agent] {summary}")

# ==========================================
# CLAUDE CLI INVOCATION (sandbox-contained)
# ==========================================
def _assert_within_root(files: list[str], allowed_root: str) -> None:
    """Rejects any target path that resolves outside the allowed sandbox root."""
    root = os.path.abspath(allowed_root)
    for f in files:
        abs_path = os.path.abspath(f)
        # os.sep guard avoids false-accepts like /home/app vs /home/app-evil
        if abs_path != root and not abs_path.startswith(root + os.sep):
            log.error(f"🚨 SECURITY: write blocked — '{f}' resolves outside {root} ({abs_path}).")
            raise ValueError(f"Out-of-sandbox write blocked: {f}")

def _find_result_envelope(stdout: str) -> dict | None:
    """Locate the Claude CLI result envelope in stdout.

    Handles BOTH output shapes: ``--output-format stream-json`` emits newline-delimited JSON events,
    the LAST of which is ``{"type":"result", ...}`` carrying usage/cost; the legacy
    ``--output-format json`` emits a single (possibly pretty-printed) object. Scans line-by-line for
    the last ``type == "result"`` object, then falls back to a whole-string parse for the single-blob
    form. Returns the envelope dict or ``None``.
    """
    envelope = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("type") == "result":
            envelope = obj
    if envelope is not None:
        return envelope
    try:
        obj = json.loads(stdout.strip())
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def parse_claude_usage(stdout: str) -> dict | None:
    """Extract token usage + cost from the Claude CLI result envelope.

    Returns ``{"input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens",
    "cost_usd"}`` or ``None`` on any parse/shape failure (never raises). Works for both the streaming
    (JSONL) and legacy single-blob output formats via ``_find_result_envelope``. The cache components
    are kept SEPARATE from fresh ``input_tokens`` on purpose: the agentic CLI re-sends its prompt every
    internal turn, so ``cache_read_input_tokens`` dominates the raw count while costing ~10% of fresh
    input. Folding them together would inflate the token budget with cheap cache reads; the caller
    excludes cache from the budget total and counts ``cost_usd`` as the authoritative spend signal.
    """
    envelope = _find_result_envelope(stdout)
    if envelope is None:
        log.debug("Failed to locate Claude usage envelope in CLI output.")
        return None
    try:
        usage = envelope.get("usage") or {}
        input_tokens = int(usage.get("input_tokens", 0))          # fresh, uncached prompt tokens only
        cache_write_tokens = int(usage.get("cache_creation_input_tokens", 0))
        cache_read_tokens = int(usage.get("cache_read_input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        # Authoritative cost from the CLI; via str() so the exact reported value enters Decimal.
        cost_usd = Decimal(str(envelope.get("total_cost_usd", envelope.get("cost_usd", 0)) or 0))
        return {
            "input_tokens": input_tokens,
            "cache_write_tokens": cache_write_tokens,
            "cache_read_tokens": cache_read_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        }
    except (ValueError, TypeError, AttributeError) as e:
        log.debug(f"Failed to parse Claude usage envelope: {e}")
        return None


# StreamReader buffer ceiling — a single stream-json event line (e.g. a large tool result) can be
# big; 8 MiB keeps asyncio's default 64 KiB readline limit from raising LimitOverrunError mid-stream.
_STREAM_LIMIT = 8 * 1024 * 1024


async def run_claude_cli(
    prompt: str, files: list[str], allowed_root: str,
    model: str | None = None, effort: str | None = None,
    timeout: float | None = None, idle_timeout: float | None = None,
) -> tuple[int, dict | None]:
    """Launches the Claude CLI against sandbox-contained files and streams its output.

    The child runs with ``cwd=allowed_root`` (the run's sandbox repo) so the inner Claude Code loads
    the SANDBOX project context — its own ``.git`` bounds project-root detection, keeping the
    orchestrator's ``CLAUDE.md``/``.claude/`` (which live in a parent directory) out of scope.

    The executable is ``CLAUDE_CLI_BIN`` (env-overridable) so a WSL run can target the Linux binary
    rather than resolving to a Windows ``claude.exe`` across the interop boundary. ``model``
    (``--model``) and ``effort`` (``--effort``, reasoning level) are forwarded to the CLI when
    provided. The CLI runs with ``--output-format stream-json --verbose`` so the agent's events arrive
    live: each assistant text/tool-use is surfaced to the console as it happens (no silent black box),
    while every raw line is captured for usage parsing. Returns ``(returncode, usage)`` where
    ``usage`` is the parsed token/cost dict from the final ``type:"result"`` event, or ``None`` if it
    could not be parsed.

    Two independent kill switches keep a stalled ``claude`` from hanging the orchestrator; on either,
    the child is killed AND reaped (no ``<defunct>`` zombie) and ``(124, None)`` is returned:
      - ``idle_timeout`` (seconds) — the watchdog: kill if NO output arrives for this long (a
        stalled/rate-limited API call produces silence; catches it well before the hard cap).
      - ``timeout`` (seconds) — hard wall-clock backstop on the whole session.
    ``None`` disables the corresponding guard.
    """
    _assert_within_root(files, allowed_root)
    cmd = [CLAUDE_CLI_BIN, "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    cmd += ["--dangerously-skip-permissions"] + files
    log.debug(f"Executing Developer Subprocess: {' '.join(cmd)}")
    # Anchor the inner Claude Code to the SANDBOX repo (allowed_root). The cloned run repo has its own
    # `.git`, which bounds Claude's upward project-root detection, so it loads the sandbox's
    # CLAUDE.md/.claude — NOT the orchestrator's `.claude/`/CLAUDE.md sitting in a parent directory.
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        limit=_STREAM_LIMIT, cwd=allowed_root,
    )

    loop = asyncio.get_event_loop()
    state = {"last": loop.time(), "killed": None}

    def _touch() -> None:
        state["last"] = loop.time()

    async def _watchdog() -> None:
        # Kill the child if it goes silent for longer than idle_timeout. Disabled when idle_timeout is None.
        if not idle_timeout:
            return
        step = min(idle_timeout, 15)
        while True:
            await asyncio.sleep(step)
            if loop.time() - state["last"] > idle_timeout:
                state["killed"] = f"no output for {idle_timeout}s (likely stalled/rate-limited API)"
                proc.kill()
                return

    stdout_buffer, stderr_buffer = [], []
    reader = asyncio.gather(
        stream_claude_stdout(proc.stdout, stdout_buffer, on_activity=_touch),
        stream_subprocess_output("   [Developer Agent][STDERR]", proc.stderr, stderr_buffer,
                                 verbose_to_console=True, on_activity=_touch),
    )
    watchdog = asyncio.create_task(_watchdog())
    try:
        # Stream readers return on pipe EOF (child exit, incl. watchdog kill); the hard cap is a backstop.
        await asyncio.wait_for(reader, timeout=timeout)
    except asyncio.TimeoutError:
        state["killed"] = state["killed"] or f"hard timeout {timeout}s"
        proc.kill()
    finally:
        watchdog.cancel()
        try:
            await watchdog
        except asyncio.CancelledError:
            pass

    await proc.wait()                  # reap — no <defunct> zombie
    if state["killed"]:
        log.error(f"🚨 Developer CLI killed: {state['killed']}.")
        return 124, None
    usage = parse_claude_usage("\n".join(stdout_buffer))
    return proc.returncode, usage
