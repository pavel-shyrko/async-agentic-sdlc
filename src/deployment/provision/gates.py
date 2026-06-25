"""Deployment plane — static deploy-manifest gate (E4 deploy-scaffolding).

Host-side (no Docker/sandbox) lint of the CI/CD manifests the DevOps agent generates, run by
``run_devops_scaffold``. Kept beside the scaffold that calls it so the deployment plane owns its own
validation; the development plane's ``gates.py`` owns the build/test/lint/SAST gates."""
from pathlib import Path

from src.shared.core.environments import SUPPORTED_DEPLOY_TARGETS, deploy_target_for_archetype


# ==========================================
# STATIC DEPLOY-MANIFEST GATE (E4 deploy-scaffolding)
# ==========================================
def run_devops_gate(repo_dir, archetype: str | None = None) -> list[str]:
    """Static-lint the generated deploy manifests; return a list of problems (empty list = clean).

    Host-side only (NO Docker/sandbox): the E4 deploy-scaffolding phase writes a GitHub Actions deploy
    workflow (and, for a web service, a Dockerfile) into the finished-app clone, and the most brittle
    failure mode is malformed workflow YAML. Checks: (1) ``.github/workflows/deploy.yml`` exists and
    parses as a YAML mapping; (2) if a ``Dockerfile`` exists, it carries a ``FROM`` and a
    ``CMD``/``ENTRYPOINT`` directive; (3) when ``archetype`` resolves to a deploy target that requires a
    public-invoker grant (registry-driven, e.g. Cloud Run), the workflow MUST grant unauthenticated
    invocation — otherwise the live service rejects every anonymous request with HTTP 403. ``archetype``
    is optional: ``None`` (or a target without the flag) skips the public-invoker check. A non-empty return
    drives exactly one self-heal retry (the messages are fed back to the DevOps agent) before a Hard Halt —
    see ``run_devops_scaffold``."""
    repo_dir = Path(repo_dir)
    problems: list[str] = []

    workflow = repo_dir / ".github" / "workflows" / "deploy.yml"
    workflow_text = ""
    if not workflow.exists():
        problems.append("Missing .github/workflows/deploy.yml — the deploy workflow was not generated.")
    else:
        workflow_text = workflow.read_text(encoding="utf-8")
        try:
            import yaml  # local: keeps PyYAML optional for non-devops runs (declared in requirements.txt)
        except ImportError:  # pragma: no cover - PyYAML is a declared dependency
            problems.append("PyYAML is not installed — cannot validate deploy.yml (add PyYAML to requirements).")
        else:
            try:
                parsed = yaml.safe_load(workflow_text)
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

    # Public-invoker policy (deploy-target-driven, registry SSOT). For an archetype whose deploy target
    # requires public invocation (Cloud Run), assert the workflow actually grants it. The grant lives in
    # IAM, OUTSIDE the Knative service spec: `--allow-unauthenticated` only takes effect in the action's
    # image-deploy mode, so when the workflow deploys a service.yaml manifest instead (the deploy-cloudrun
    # `metadata:` input or `gcloud run services replace`) that flag is silently dropped and the service
    # stays authenticated-only — only an explicit allUsers→roles/run.invoker binding makes it public there.
    target_id = deploy_target_for_archetype(archetype)
    target_spec = SUPPORTED_DEPLOY_TARGETS.get(target_id or "")
    if target_spec and target_spec.get("requires_public_invoker") and workflow_text:
        lowered = workflow_text.lower()
        has_iam_binding = "allusers" in lowered and "run.invoker" in lowered
        has_unauth_flag = "allow-unauthenticated" in lowered
        # Manifest-deploy mode: `gcloud run services replace`, or a `metadata:` input on the deploy-cloudrun
        # action. There the flag is incompatible/ignored — require the explicit IAM binding.
        uses_manifest_deploy = "services replace" in lowered or (
            "deploy-cloudrun" in lowered and "metadata:" in lowered
        )
        grants_public = has_iam_binding if uses_manifest_deploy else (has_unauth_flag or has_iam_binding)
        if not grants_public:
            if uses_manifest_deploy:
                problems.append(
                    f"deploy.yml deploys a Knative service.yaml manifest to '{target_id}' but never grants "
                    "public invocation via IAM: `--allow-unauthenticated` does NOT apply in manifest-deploy "
                    "mode (the public-access policy lives in IAM, outside the service spec). Add a step that "
                    "binds allUsers to roles/run.invoker (`gcloud run services add-iam-policy-binding "
                    "<service> --member=allUsers --role=roles/run.invoker`) — without it Cloud Run returns "
                    "HTTP 403 for every anonymous request."
                )
            else:
                problems.append(
                    f"deploy.yml does not grant public invocation: a public web service on '{target_id}' must "
                    "allow unauthenticated invocations (pass `flags: '--allow-unauthenticated'` to the "
                    "deploy-cloudrun step, or bind allUsers to roles/run.invoker) — without it Cloud Run "
                    "returns HTTP 403 for every anonymous request."
                )

        # Service-name collision guard. A managed service is keyed by (name, region, project); a hardcoded
        # literal name lets one repo's deploy silently overwrite another's service (a new revision takes over
        # the live URL). The name MUST be derived from the GitHub repository context so every repo gets a
        # distinct, stable service — accept `github.event.repository.name` or `github.repository`.
        derives_name_from_repo = "github.event.repository.name" in lowered or "github.repository" in lowered
        if not derives_name_from_repo:
            problems.append(
                f"deploy.yml hardcodes the '{target_id}' service name instead of deriving it from the "
                "repository context: a static name lets one app overwrite another's service (same name + "
                "region + project = an overwriting revision, not a new service). Derive the service name "
                "from `${{ github.event.repository.name }}` for the deploy step (and the image path)."
            )

    return problems
