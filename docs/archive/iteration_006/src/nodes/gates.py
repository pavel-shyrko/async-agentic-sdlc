import os
import sys
import asyncio
import subprocess

from src.core.observability import log
from src.utils.subprocess_helpers import stream_subprocess_output

# ==========================================
# PARALLEL RUNTIME GATES (Subprocess execution)
# ==========================================
async def run_qa_unit_tests(artifacts_base_abs: str) -> tuple[bool, list[str]]:
    # Mount framework code read-only and the agent sandbox read-write — never the whole cwd.
    # The artifacts base maps to a FIXED in-container path, so any PIPELINE_ARTIFACTS_BASE works.
    # Discover ALL per-module test files instead of a single module — QA generates a tree autonomously.
    test_command = (
        "export PYTHONPATH=$PYTHONPATH:/workspace/artifacts/code:/workspace/artifacts/tests; "
        "python3 -m unittest discover -s /workspace/artifacts/tests -p 'test_*.py'"
    )
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{artifacts_base_abs}:/workspace/artifacts:rw",
        "-w", "/workspace",
        "python:3.11-slim",
        "bash", "-c", test_command
    ]

    log.debug(f"Executing QA runtime gate: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_buffer, stderr_buffer = [], []

    await asyncio.gather(
        stream_subprocess_output("docker-qa-stdout", proc.stdout, stdout_buffer, verbose_to_console=False),
        stream_subprocess_output("docker-qa-stderr", proc.stderr, stderr_buffer, verbose_to_console=False)
    )
    await proc.wait()

    # Combine stdout and stderr outputs
    total_log = stdout_buffer + stderr_buffer
    log.debug(f"QA Runtime Gate completed with exit code: {proc.returncode}")
    return (proc.returncode == 0), total_log

async def run_security_scan(files: list[str]) -> tuple[bool, list[str]]:
    # Guard block to prevent Bandit from hanging or crashing
    if not files or not all(isinstance(f, str) and f.strip() for f in files):
        log.warning("SAST Error: No target execution files specified in contract.")
        return False, ["SAST Error: No target execution files specified in contract."]

    cmd = [sys.executable, "-m", "bandit", "-q", "-r"] + files
    log.debug(f"Executing SAST security gate: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_buffer, stderr_buffer = [], []

    await asyncio.gather(
        stream_subprocess_output("bandit-stdout", proc.stdout, stdout_buffer, verbose_to_console=False),
        stream_subprocess_output("bandit-stderr", proc.stderr, stderr_buffer, verbose_to_console=False)
    )
    await proc.wait()

    total_log = stdout_buffer + stderr_buffer
    if proc.returncode == 0 and not "".join(total_log).strip():
        total_log = ["Bandit execution passed. Zero vulnerabilities identified."]

    log.debug(f"SAST Security Gate completed with exit code: {proc.returncode}")
    return (proc.returncode == 0), total_log
