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
async def stream_subprocess_output(prefix: str, stream: asyncio.StreamReader, buffer: list, verbose_to_console: bool = False):
    while True:
        line = await stream.readline()
        if not line:
            break
        decoded = line.decode().rstrip()
        buffer.append(decoded)

        # verbose_to_console=True surfaces lines on the console (INFO); otherwise file-only (DEBUG)
        if verbose_to_console:
            log.info(f"{prefix} {decoded}")
        else:
            log.debug(f"{prefix} {decoded}")

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

def parse_claude_usage(stdout: str) -> dict | None:
    """Extract token usage + cost from the Claude CLI ``--output-format json`` result envelope.

    Returns ``{"input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens",
    "cost_usd"}`` or ``None`` on any parse/shape failure (never raises). The cache components are
    kept SEPARATE from fresh ``input_tokens`` on purpose: the agentic CLI re-sends its prompt every
    internal turn, so ``cache_read_input_tokens`` dominates the raw count while costing ~10% of fresh
    input. Folding them together would inflate the token budget with cheap cache reads; the caller
    excludes cache from the budget total and counts ``cost_usd`` as the authoritative spend signal.
    """
    try:
        envelope = json.loads(stdout.strip())
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


async def run_claude_cli(
    prompt: str, files: list[str], allowed_root: str,
    model: str | None = None, effort: str | None = None,
    timeout: float | None = None,
) -> tuple[int, dict | None]:
    """Launches the Claude CLI against sandbox-contained files and captures its output.

    The executable is ``CLAUDE_CLI_BIN`` (env-overridable) so a WSL run can target the Linux binary
    rather than resolving to a Windows ``claude.exe`` across the interop boundary. ``model``
    (``--model``) and ``effort`` (``--effort``, reasoning level) are forwarded to the CLI when
    provided. Returns ``(returncode, usage)`` where ``usage`` is the parsed token/cost dict from the
    ``--output-format json`` result envelope, or ``None`` if it could not be parsed. stdout is a
    single JSON blob (not human-readable), so it is captured for parsing rather than streamed to the
    console; stderr is still surfaced live for diagnostics.

    ``timeout`` (seconds) bounds the whole agentic session: on expiry the child is killed AND reaped
    (no ``<defunct>`` zombie, mirroring the git launcher) and ``(124, None)`` is returned so a
    stalled ``claude`` can never hang the orchestrator. ``None`` means no timeout.
    """
    _assert_within_root(files, allowed_root)
    cmd = [CLAUDE_CLI_BIN, "-p", prompt, "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    cmd += ["--dangerously-skip-permissions"] + files
    log.debug(f"Executing Developer Subprocess: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout_buffer, stderr_buffer = [], []
    try:
        # Stream readers only return on pipe EOF (child exit); bound the wait so a hung child is killed.
        await asyncio.wait_for(
            asyncio.gather(
                stream_subprocess_output("   [Developer Agent][STDOUT]", proc.stdout, stdout_buffer, verbose_to_console=False),
                stream_subprocess_output("   [Developer Agent][STDERR]", proc.stderr, stderr_buffer, verbose_to_console=True),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()              # reap immediately after kill — no <defunct> zombie
        log.error(f"🚨 Developer CLI timed out after {timeout}s (possible interop/stdout hang) — killed.")
        return 124, None
    await proc.wait()
    usage = parse_claude_usage("".join(stdout_buffer))
    return proc.returncode, usage
