from src.shared.core.observability import log
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS, SAST_IMAGE, SAST_CMD
from src.shared.core.docker_adapter import execute_in_sandbox, run_in_image

# ==========================================
# PARALLEL RUNTIME GATES (Sandboxed execution)
# ==========================================
# Commands come from the static SUPPORTED_ENVIRONMENTS registry and run inside the canonical,
# hardened sandbox image for the ticket's environment_id — no host tooling, no hardcoded runtime.
async def run_qa_unit_tests(environment_id: str, repo_root: str) -> tuple[bool, list[str]]:
    """Functional-test gate. Dependency restore runs FIRST with network ON (project deps can't be
    baked into the image); the tests themselves then run with network OFF (isolated execution)."""
    spec = SUPPORTED_ENVIRONMENTS[environment_id]
    log_lines: list[str] = []

    setup_cmd = spec.get("setup_cmd")
    if setup_cmd:
        log.debug(f"Restoring dependencies [{environment_id}] (network ON): {setup_cmd}")
        rc, out, err = await execute_in_sandbox(environment_id, setup_cmd, repo_root, network="bridge")
        log_lines += (out + "\n" + err).strip().splitlines()
        if rc != 0:
            log.debug(f"Dependency restore failed with exit code: {rc}")
            return False, ["🚨 Dependency restore failed:"] + log_lines

    test_cmd = spec["test_cmd"]
    log.debug(f"Executing QA runtime gate [{environment_id}] (network OFF): {test_cmd}")
    returncode, stdout, stderr = await execute_in_sandbox(environment_id, test_cmd, repo_root, network="none")
    log_lines += (stdout + "\n" + stderr).strip().splitlines()
    log.debug(f"QA Runtime Gate completed with exit code: {returncode}")
    return returncode == 0, log_lines


async def run_security_scan(environment_id: str, repo_root: str) -> tuple[bool, list[str]]:
    """Generic SAST gate: one Semgrep image scans every language. Network ON only to fetch rulesets —
    Semgrep analyses source, it does not execute the project code."""
    log.debug(f"Executing SAST security gate [{environment_id}] via {SAST_IMAGE}: {SAST_CMD}")
    returncode, stdout, stderr = await run_in_image(SAST_IMAGE, SAST_CMD, repo_root, network="bridge")
    log_lines = (stdout + "\n" + stderr).strip().splitlines()
    if returncode == 0 and not log_lines:
        log_lines = ["SAST execution passed. Zero vulnerabilities identified."]
    log.debug(f"SAST Security Gate completed with exit code: {returncode}")
    return returncode == 0, log_lines
