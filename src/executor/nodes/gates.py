from src.shared.core.observability import log
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS
from src.shared.core.docker_adapter import execute_in_sandbox

# ==========================================
# PARALLEL RUNTIME GATES (Sandboxed execution)
# ==========================================
# Both gates resolve their command from the static SUPPORTED_ENVIRONMENTS registry and run it
# inside the canonical, hardened Docker image for the ticket's environment_id. No host-level
# tooling and no hardcoded runtime — the ticket's selected stack drives image + command.
async def run_qa_unit_tests(environment_id: str, repo_root: str) -> tuple[bool, list[str]]:
    test_cmd = SUPPORTED_ENVIRONMENTS[environment_id]["test_cmd"]
    log.debug(f"Executing QA runtime gate [{environment_id}]: {test_cmd}")
    returncode, stdout, stderr = await execute_in_sandbox(environment_id, test_cmd, repo_root)
    log_lines = (stdout + "\n" + stderr).strip().splitlines()
    log.debug(f"QA Runtime Gate completed with exit code: {returncode}")
    return returncode == 0, log_lines


async def run_security_scan(environment_id: str, repo_root: str) -> tuple[bool, list[str]]:
    sast_cmd = SUPPORTED_ENVIRONMENTS[environment_id]["sast_cmd"]
    log.debug(f"Executing SAST security gate [{environment_id}]: {sast_cmd}")
    returncode, stdout, stderr = await execute_in_sandbox(environment_id, sast_cmd, repo_root)
    log_lines = (stdout + "\n" + stderr).strip().splitlines()
    if returncode == 0 and not log_lines:
        log_lines = ["SAST execution passed. Zero vulnerabilities identified."]
    log.debug(f"SAST Security Gate completed with exit code: {returncode}")
    return returncode == 0, log_lines
