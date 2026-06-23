"""Deployment plane — static deploy-manifest gate (E4 deploy-scaffolding).

Host-side (no Docker/sandbox) lint of the CI/CD manifests the DevOps agent generates, run by
``run_devops_scaffold``. Kept beside the scaffold that calls it so the deployment plane owns its own
validation; the development plane's ``gates.py`` owns the build/test/lint/SAST gates."""
from pathlib import Path


# ==========================================
# STATIC DEPLOY-MANIFEST GATE (E4 deploy-scaffolding)
# ==========================================
def run_devops_gate(repo_dir) -> list[str]:
    """Static-lint the generated deploy manifests; return a list of problems (empty list = clean).

    Host-side only (NO Docker/sandbox): the E4 deploy-scaffolding phase writes a GitHub Actions deploy
    workflow (and, for a web service, a Dockerfile) into the finished-app clone, and the most brittle
    failure mode is malformed workflow YAML. Checks: (1) ``.github/workflows/deploy.yml`` exists and
    parses as a YAML mapping; (2) if a ``Dockerfile`` exists, it carries a ``FROM`` and a
    ``CMD``/``ENTRYPOINT`` directive. A non-empty return drives exactly one self-heal retry (the messages
    are fed back to the DevOps agent) before a Hard Halt — see ``run_devops_scaffold``."""
    repo_dir = Path(repo_dir)
    problems: list[str] = []

    workflow = repo_dir / ".github" / "workflows" / "deploy.yml"
    if not workflow.exists():
        problems.append("Missing .github/workflows/deploy.yml — the deploy workflow was not generated.")
    else:
        try:
            import yaml  # local: keeps PyYAML optional for non-devops runs (declared in requirements.txt)
        except ImportError:  # pragma: no cover - PyYAML is a declared dependency
            problems.append("PyYAML is not installed — cannot validate deploy.yml (add PyYAML to requirements).")
        else:
            try:
                parsed = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                if not isinstance(parsed, dict):
                    problems.append("deploy.yml did not parse to a YAML mapping (a top-level workflow object is expected).")
            except yaml.YAMLError as exc:
                problems.append(f"deploy.yml is not valid YAML: {exc}")

    dockerfile = repo_dir / "Dockerfile"
    if dockerfile.exists():
        lines = [ln.strip().upper() for ln in dockerfile.read_text(encoding="utf-8").splitlines()]
        if not any(ln.startswith("FROM ") for ln in lines):
            problems.append("Dockerfile is missing a FROM directive.")
        if not any(ln.startswith("CMD") or ln.startswith("ENTRYPOINT") for ln in lines):
            problems.append("Dockerfile is missing a CMD/ENTRYPOINT directive.")

    return problems
