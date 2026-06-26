"""Deployment plane — static deploy-manifest gate (E4 deploy-scaffolding).

Host-side (no Docker/sandbox) lint of the CI/CD manifests the DevOps agent generates, run by
``run_devops_scaffold``. Kept beside the scaffold that calls it so the deployment plane owns its own
validation; the development plane's ``gates.py`` owns the build/test/lint/SAST gates."""
import re
from pathlib import Path

from src.shared.core.environments import SUPPORTED_DEPLOY_TARGETS, deploy_target_for_archetype


def _iter_run_scripts(parsed) -> list[str]:
    """Yield every step ``run:`` script string from a parsed GitHub Actions workflow mapping.

    Tolerant of partial/odd shapes (returns what it can): only ``jobs.<job>.steps[*].run`` strings are
    collected. Used to assert no ``run:`` step is assembled from a ``${{ format(...) }}`` expression."""
    scripts: list[str] = []
    if not isinstance(parsed, dict):
        return scripts
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict):
        return scripts
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                scripts.append(step["run"])
    return scripts


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
    invocation — otherwise the live service rejects every anonymous request with HTTP 403; (4) the
    README-URL publish step must NOT be assembled from a ``${{ format(...) }}`` expression (the literal's
    quote-doubling breaks the executed shell), and every URL marker the workflow references must be
    pre-seeded into ``README.md`` (else the in-place replace no-ops into the fragile append fallback).
    ``archetype`` is optional: ``None`` (or a target without the flag) skips the public-invoker check. A non-empty return
    drives exactly one self-heal retry (the messages are fed back to the DevOps agent) before a Hard Halt —
    see ``run_devops_scaffold``."""
    repo_dir = Path(repo_dir)
    problems: list[str] = []

    workflow = repo_dir / ".github" / "workflows" / "deploy.yml"
    workflow_text = ""
    parsed = None
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

    # README-URL publish step contract (both platform skills emit an "Update README with … URL" step that
    # replaces text BETWEEN pre-seeded markers, falling back to an append). Two failure modes, both seen live:
    if workflow_text:
        # (a) A `run:` step assembled via a `${{ format(...) }}` expression is forbidden: a format() string
        # literal escapes every single quote by DOUBLING it ('→''), and that doubling leaks into the executed
        # bash — so the README-URL step's `printf ''\n…''` word-splits the format string and appends a stray
        # `##` line instead of the live URL. Author every `run:` as a literal block and interpolate directly.
        if any("format(" in script for script in _iter_run_scripts(parsed)):
            problems.append(
                "deploy.yml builds a `run:` step via a `${{ format(...) }}` expression: a format() literal "
                "doubles single quotes ('→''), and the doubling leaks into the executed shell, breaking the "
                "README-URL step's printf fallback (it appends a stray `##` instead of the live URL). Author "
                "every `run:` as a literal block (`run: |`) and interpolate `${{ … }}` values directly."
            )
        # (b) The URL step's primary path replaces text BETWEEN markers; if README.md lacks them the replace
        # is a no-op and the step silently degrades to its fragile append fallback. Assert every URL marker
        # the workflow references is pre-seeded into README.md (the Technical Writer seeds README_SCAFFOLD).
        referenced_markers = sorted(set(re.findall(r"[A-Z_]*URL_START", workflow_text)))
        if referenced_markers:
            readme = repo_dir / "README.md"
            readme_text = readme.read_text(encoding="utf-8") if readme.exists() else ""
            for start in referenced_markers:
                end = start.replace("_START", "_END")
                if f"<!-- {start} -->" not in readme_text or f"<!-- {end} -->" not in readme_text:
                    problems.append(
                        f"deploy.yml injects the live URL between the `{start}`/`{end}` markers, but README.md "
                        "lacks that marker pair — the in-place replace is a no-op and the step falls to its "
                        f"append fallback. Pre-seed `<!-- {start} -->` / `<!-- {end} -->` into the README's "
                        "deployment section (the Technical Writer's README scaffold)."
                    )

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
        # `--allow-unauthenticated` only counts as a valid grant when used via the
        # deploy-cloudrun action's `flags:` input (image-deploy mode). The flag does NOT
        # exist on `gcloud run services update` — that command exits 2 at runtime.
        # Check each line so the invalid `services update` form is excluded.
        has_unauth_flag = any(
            "allow-unauthenticated" in line.lower() and "services update" not in line.lower()
            for line in workflow_text.splitlines()
        )
        # Detect the invalid `gcloud run services update --allow-unauthenticated` form and
        # flag it unconditionally — it exits 2 even when a valid IAM binding step is present.
        invalid_update_lines = [
            line.strip()
            for line in workflow_text.splitlines()
            if "services update" in line.lower() and "allow-unauthenticated" in line.lower()
        ]
        if invalid_update_lines:
            problems.append(
                f"deploy.yml uses `gcloud run services update --allow-unauthenticated`, which is "  # nosec B608 — diagnostic string, not a query
                "not a valid command (`--allow-unauthenticated` is not a recognized argument for "
                "`gcloud run services update` — exits 2). Cloud Run's public-access policy lives "
                "in IAM and must be set via `gcloud run services add-iam-policy-binding`. Remove "
                "the invalid step; the `add-iam-policy-binding` step (with --member=allUsers "
                "--role=roles/run.invoker) is the authoritative grant."
            )
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

        # Broken-continuation guard. `has_iam_binding` checks only that the strings "allusers" and
        # "run.invoker" appear anywhere in the file — they will even when `\` continuation backslashes
        # are dropped and `--member`/`--role` execute as separate (invalid) shell lines. Verify that
        # `--member` and `--role` sit on the same logical command as `add-iam-policy-binding`.
        if has_iam_binding:
            lines = workflow_text.splitlines()
            for i, line in enumerate(lines):
                if "add-iam-policy-binding" in line.lower():
                    logical_cmd = line
                    j = i
                    while lines[j].rstrip().endswith("\\") and j + 1 < len(lines):
                        j += 1
                        logical_cmd += " " + lines[j]
                    lc = logical_cmd.lower()
                    if "--member" not in lc or "--role" not in lc:
                        problems.append(
                            f"deploy.yml: `gcloud run services add-iam-policy-binding` is missing "
                            "--member and/or --role on its logical command line. The flags are present "
                            "elsewhere in the file but on unreachable lines — missing `\\` "
                            "line-continuation backslashes cause the shell to run only the first line "
                            "and ignore the rest, producing `argument --member --role: Must be "
                            "specified` (exit 1). Write the full command on a single `run:` line "
                            "(recommended) or ensure every continued line ends with ` \\\\'."
                        )
                    break

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
