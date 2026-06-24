# Hardened, async Docker execution adapter. Runs a command inside the canonical image for a
# registered `environment_id` — least-privilege (non-root, no host network, ephemeral container).
import os
import asyncio
# subprocess: only PIPE constants with fixed-argument exec, never shell=True (repo convention).
import subprocess  # nosec B404

from src.shared.core.observability import log
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS
from src.shared.utils.subprocess_helpers import stream_subprocess_output

# Resource caps for every sandbox container (least-privilege; aligns with the QA-sandbox hardening).
# CPUs are env-overridable (config-constant-convention): more cores speed CPU-bound gates — notably the
# semgrep SAST scan (the dominant infra time sink), which parallelises rule-matching across cores, and
# `dotnet build`/`test`. A `--cpus` value above the host's core count is accepted (quota capped by
# hardware), so a higher default is safe. This is a resource CAP only — it does not weaken the
# `--cap-drop ALL` / non-root / `--network none` isolation the qa-sandbox-hardening rule mandates.
_SANDBOX_MEMORY = "2g"
_SANDBOX_PIDS = "512"
_SANDBOX_CPUS = os.environ.get("SANDBOX_CPUS", "4")


def _validate_command(command: str) -> None:
    if not isinstance(command, str) or not command.strip() or any(c in command for c in "\x00\n\r"):
        raise ValueError("Invalid sandbox command: must be a non-empty single-line string.")


async def run_in_image(
    image: str, command: str, repo_path: str, *,
    env: dict | None = None, network: str = "none",
    cache_volume: dict | None = None, cache_writable: bool = False,
) -> tuple[int, str, str]:
    """Run ``command`` inside ``image`` over ``repo_path`` (mounted at /workspace). Returns
    ``(returncode, stdout, stderr)``.

    Hardening: the host NEVER spawns a shell — argv is passed directly to docker; ``sh -c`` runs ONLY
    inside the throwaway (``--rm``), resource-capped (memory/pids/cpus), capability-stripped
    (``--cap-drop ALL``), non-root container with a writable tmpfs ``/tmp``. ``network`` defaults to
    ``none`` (isolated); callers pass ``"bridge"`` only for the dependency-restore / SAST-rule-fetch
    phases. ``env`` injects writable cache/HOME vars so the non-root run never hits ``/.cache`` EPERM.
    ``command`` must be a static registry string (never raw LLM text); control chars are rejected.

    ``cache_volume`` (``{"name", "mount", "env"}``) mounts a PERSISTENT named docker volume for the
    package-download cache, surviving across the separate restore/build/test containers (each gets a
    fresh ``--tmpfs /tmp``, so a /tmp cache is lost between them) AND across runs. It is mounted
    read-only UNLESS ``cache_writable`` — only the network-ON restore phase writes; the adversarial
    test phase gets it ``:ro`` so a hostile test cannot poison the shared cache. Its ``env`` overrides
    the tmpfs cache paths in ``env``. Proxy env (``HTTP(S)_PROXY``/``NO_PROXY``) is propagated from the
    host ONLY during the ``bridge`` phase, so an explicit corporate proxy reaches the feed while the
    isolated test phase stays clean.
    """
    _validate_command(command)
    merged_env = {**(env or {}), **((cache_volume or {}).get("env") or {})}
    cmd = [
        "docker", "run", "--rm",
        "--network", network,
        "--memory", _SANDBOX_MEMORY, "--pids-limit", _SANDBOX_PIDS, "--cpus", _SANDBOX_CPUS,
        "--cap-drop", "ALL",
        "--tmpfs", "/tmp:rw,exec",                 # nosec B108 — in-container tmpfs scratch, not a host temp path
    ]
    if cache_volume:
        # Insert BEFORE the /workspace mount so the image/sh/command tail stays at argv[-4:].
        suffix = "" if cache_writable else ":ro"
        cmd += ["-v", f"{cache_volume['name']}:{cache_volume['mount']}{suffix}"]
    cmd += ["-v", f"{repo_path}:/workspace", "-w", "/workspace"]
    # Egress proxy is only meaningful (and only safe) on the network-ON restore/SAST phase.
    if network == "bridge":
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"):
            if var in os.environ:
                cmd += ["--env", f"{var}={os.environ[var]}"]
    for key, value in merged_env.items():
        cmd += ["--env", f"{key}={value}"]
    # os.getuid/getgid are POSIX-only. On POSIX hosts (incl. WSL) run as the calling user so files
    # written into the mounted volume are NOT root-owned. On win32, Docker Desktop maps ownership.
    if hasattr(os, "getuid"):
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
    cmd += [image, "sh", "-c", command]

    log.debug(f"Executing sandbox [{image} | net={network}]: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_buffer, stderr_buffer = [], []
    await asyncio.gather(
        stream_subprocess_output("docker-stdout", proc.stdout, stdout_buffer, verbose_to_console=False),
        stream_subprocess_output("docker-stderr", proc.stderr, stderr_buffer, verbose_to_console=False),
    )
    await proc.wait()
    log.debug(f"Sandbox [{image}] completed with exit code: {proc.returncode}")
    return proc.returncode, "\n".join(stdout_buffer), "\n".join(stderr_buffer)


async def execute_in_sandbox(
    environment_id: str, command: str, repo_path: str, network: str = "none",
    cache_writable: bool = False,
) -> tuple[int, str, str]:
    """Execute ``command`` in the image registered for ``environment_id``, injecting that env's
    ``sandbox_env`` (writable HOME/caches) and its persistent ``cache_volume`` (if declared). Thin
    wrapper over ``run_in_image``. ``cache_writable`` is set by callers ONLY for the network-ON
    restore phase, so the package cache is writable there and read-only everywhere else."""
    if environment_id not in SUPPORTED_ENVIRONMENTS:
        raise ValueError(
            f"Unsupported environment_id '{environment_id}'. "
            f"Choose one of: {sorted(SUPPORTED_ENVIRONMENTS)}."
        )
    spec = SUPPORTED_ENVIRONMENTS[environment_id]
    return await run_in_image(
        spec["image"], command, repo_path, env=spec.get("sandbox_env"), network=network,
        cache_volume=spec.get("cache_volume"), cache_writable=cache_writable,
    )
