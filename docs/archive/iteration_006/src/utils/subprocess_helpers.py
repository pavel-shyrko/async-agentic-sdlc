import os
import asyncio
import subprocess

from src.core.observability import log

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

async def run_claude_cli(prompt: str, files: list[str], allowed_root: str) -> int:
    """Launches the Claude CLI against sandbox-contained files and streams its output."""
    _assert_within_root(files, allowed_root)
    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"] + files
    log.debug(f"Executing Developer Subprocess: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout_buffer, stderr_buffer = [], []
    await asyncio.gather(
        stream_subprocess_output("   [Developer Agent][STDOUT]", proc.stdout, stdout_buffer, verbose_to_console=True),
        stream_subprocess_output("   [Developer Agent][STDERR]", proc.stderr, stderr_buffer, verbose_to_console=True),
    )
    await proc.wait()
    return proc.returncode
