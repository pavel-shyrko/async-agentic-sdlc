"""Unit tests for the E4 DevOps deploy-scaffolding node and its static-lint gate.

Hermetic: the LLM boundary and the `git add` subprocess are mocked, so the node test exercises the
read/classify/write/stage logic against a real TemporaryDirectory; the gate test runs pure host-side
validation (YAML well-formedness + Dockerfile directives) with no Docker/sandbox.
"""
import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock

# devops imports src.shared.core.config at import time, which builds the genai client.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.deployment.agents import devops
from src.deployment.provision.gates import run_devops_gate
from src.shared.core.models import DevOpsManifests, GlobalPipelineContext, WorkspacePaths
from src.shared.utils.llm import _relocate_jinja_system_messages


def _ctx(repo: Path) -> GlobalPipelineContext:
    paths = WorkspacePaths(logs_dir=repo / "logs", reports_dir=repo / "reports", repo_dir=repo)
    return GlobalPipelineContext(pr_description="scaffold deployment", base_branch="main", workspace_paths=paths)


class RunDevopsNodeTests(unittest.IsolatedAsyncioTestCase):
    """The node writes the deploy manifests into the clone and stages them for the atomic commit."""

    async def test_web_service_writes_dockerfile_workflow_and_stages(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = _ctx(repo)
            manifests = DevOpsManifests(
                archetype="rest_api",
                dockerfile_content="FROM python:3.12-slim\nUSER nobody\nCMD [\"python\", \"app.py\"]\n",
                workflow_content="name: deploy\non:\n  push:\n    branches: [main]\n",
                env_scaffold_content="PORT=8080\n",
                engineering_reasoning="stateless web service → Cloud Run",
            )
            fake = (manifests, SimpleNamespace(usage_metadata=None))
            with (
                mock.patch.object(devops, "run_structured_llm", new=AsyncMock(return_value=fake)) as llm,
                mock.patch.object(devops.subprocess, "run") as git_run,
            ):
                await devops.run_devops_node(ctx, blueprint_text="a REST API", repo_map="app.py")

            # All three manifests written verbatim into the clone.
            self.assertEqual((repo / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8"),
                             manifests.workflow_content)
            self.assertEqual((repo / "Dockerfile").read_text(encoding="utf-8"), manifests.dockerfile_content)
            self.assertEqual((repo / ".env.example").read_text(encoding="utf-8"), manifests.env_scaffold_content)
            # Staged together so finalize_transaction's atomic commit includes them.
            git_run.assert_called_once()
            self.assertEqual(
                git_run.call_args.args[0],
                ["git", "add", ".github/workflows/deploy.yml", "Dockerfile", ".env.example"],
            )
            self.assertEqual(git_run.call_args.kwargs["cwd"], str(repo))
            # Against the devops role + DevOpsManifests schema; result stored on ctx.
            self.assertEqual(llm.call_args.args[0], "devops")
            self.assertIs(llm.call_args.args[1], DevOpsManifests)
            self.assertEqual(ctx.devops_manifests.archetype, "rest_api")

    async def test_cli_tool_writes_no_dockerfile(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = _ctx(repo)
            manifests = DevOpsManifests(
                archetype="cli_tool",
                dockerfile_content=None,                 # a CLI has no runtime container
                workflow_content="name: build\non:\n  push: {}\n",
                env_scaffold_content=None,
                engineering_reasoning="CLI → build/release matrix, no Cloud Run",
            )
            fake = (manifests, SimpleNamespace(usage_metadata=None))
            with (
                mock.patch.object(devops, "run_structured_llm", new=AsyncMock(return_value=fake)),
                mock.patch.object(devops.subprocess, "run") as git_run,
            ):
                await devops.run_devops_node(ctx, blueprint_text="a CLI tool", repo_map="main.py")

            self.assertTrue((repo / ".github" / "workflows" / "deploy.yml").is_file())
            self.assertFalse((repo / "Dockerfile").exists())       # hard rule: no Dockerfile for a CLI
            self.assertFalse((repo / ".env.example").exists())
            self.assertEqual(git_run.call_args.args[0], ["git", "add", ".github/workflows/deploy.yml"])

    async def test_retry_feeds_gate_feedback_into_prompt(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = _ctx(repo)
            captured: dict[str, str] = {}

            def _capture(role, model, messages):
                captured["user"] = messages[1]["content"]
                return (DevOpsManifests(archetype="rest_api", workflow_content="name: x\non: push\n",
                                        engineering_reasoning="r"),
                        SimpleNamespace(usage_metadata=None))

            with (
                mock.patch.object(devops, "run_structured_llm", new=AsyncMock(side_effect=_capture)),
                mock.patch.object(devops.subprocess, "run"),
            ):
                await devops.run_devops_node(ctx, blueprint_text="b", repo_map="m",
                                             gate_feedback="- deploy.yml is not valid YAML: bad indent")

            self.assertIn("deploy.yml is not valid YAML", captured["user"])

    async def test_ci_commands_injected_into_prompt(self) -> None:
        # The canonical env commands (the SSOT the CI must run verbatim) reach the user prompt under a
        # neutral section label — the instruction text lives in devops.md (system prompt), not user content.
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = _ctx(repo)
            captured: dict[str, str] = {}

            def _capture(role, model, messages):
                captured["user"] = messages[1]["content"]
                return (DevOpsManifests(archetype="cli_tool", workflow_content="name: x\non: push\n",
                                        engineering_reasoning="r"),
                        SimpleNamespace(usage_metadata=None))

            with (
                mock.patch.object(devops, "run_structured_llm", new=AsyncMock(side_effect=_capture)),
                mock.patch.object(devops.subprocess, "run"),
            ):
                await devops.run_devops_node(
                    ctx, blueprint_text="b", repo_map="m",
                    environment_ids="python-3.12-core",
                    ci_commands="- environment_id: python-3.12-core\n    lint_cmd: ruff check --no-cache . && ruff format --check .",
                )

            self.assertIn("ruff check --no-cache", captured["user"])
            self.assertIn("=== CANONICAL PROJECT COMMANDS ===", captured["user"])


class RunDevopsGateTests(unittest.TestCase):
    """Static lint: deploy.yml must be well-formed YAML; a Dockerfile (if present) needs FROM + CMD."""

    def _write(self, repo: Path, workflow: str | None = None, dockerfile: str | None = None) -> None:
        if workflow is not None:
            wf = repo / ".github" / "workflows" / "deploy.yml"
            wf.parent.mkdir(parents=True, exist_ok=True)
            wf.write_text(workflow, encoding="utf-8")
        if dockerfile is not None:
            (repo / "Dockerfile").write_text(dockerfile, encoding="utf-8")

    def test_clean_web_service_passes(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            self._write(repo, workflow="name: deploy\non:\n  push:\n    branches: [main]\n",
                        dockerfile="FROM python:3.12-slim\nCMD [\"python\", \"app.py\"]\n")
            self.assertEqual(run_devops_gate(repo), [])

    def test_clean_cli_passes_without_dockerfile(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            self._write(repo, workflow="name: build\non:\n  push: {}\n")   # no Dockerfile is fine for a CLI
            self.assertEqual(run_devops_gate(repo), [])

    def test_malformed_yaml_is_flagged(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            # A tab-indented mapping under a key is invalid YAML.
            self._write(repo, workflow="name: deploy\non:\n\tpush: bad\n")
            problems = run_devops_gate(repo)
            self.assertTrue(any("not valid YAML" in p for p in problems), problems)

    def test_missing_workflow_is_flagged(self) -> None:
        with TemporaryDirectory() as td:
            problems = run_devops_gate(Path(td))
            self.assertTrue(any("Missing .github/workflows/deploy.yml" in p for p in problems), problems)

    def test_dockerfile_missing_directives_is_flagged(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            self._write(repo, workflow="name: deploy\non:\n  push: {}\n",
                        dockerfile="RUN echo hi\n")   # no FROM, no CMD/ENTRYPOINT
            problems = run_devops_gate(repo)
            self.assertTrue(any("FROM" in p for p in problems), problems)
            self.assertTrue(any("CMD/ENTRYPOINT" in p for p in problems), problems)

    def test_web_service_without_public_invoker_is_flagged(self) -> None:
        # A Cloud Run web service whose workflow never grants unauthenticated invocation is the 403-class
        # defect — the archetype-aware gate flags it (registry: rest_api → gcp-cloud-run, requires invoker).
        with TemporaryDirectory() as td:
            repo = Path(td)
            self._write(repo, workflow="name: deploy\non:\n  push:\n    branches: [main]\n",
                        dockerfile="FROM python:3.12-slim\nCMD [\"python\", \"app.py\"]\n")
            problems = run_devops_gate(repo, archetype="rest_api")
            self.assertTrue(any("public invocation" in p for p in problems), problems)

    def test_web_service_with_allow_unauthenticated_passes(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            wf = ("name: deploy\non:\n  push:\n    branches: [main]\n"
                  "jobs:\n  deploy:\n    steps:\n      - uses: google-github-actions/deploy-cloudrun@v2\n"
                  "        with:\n          service: ${{ github.event.repository.name }}\n"
                  "          flags: '--allow-unauthenticated'\n")
            self._write(repo, workflow=wf, dockerfile="FROM python:3.12-slim\nCMD [\"python\", \"app.py\"]\n")
            self.assertEqual(run_devops_gate(repo, archetype="rest_api"), [])

    def test_web_service_with_iam_binding_passes(self) -> None:
        # The alternate idiom: an explicit allUsers → roles/run.invoker IAM binding satisfies the gate too.
        with TemporaryDirectory() as td:
            repo = Path(td)
            wf = ("name: deploy\non: push\n"
                  "jobs:\n  deploy:\n    steps:\n"
                  "      - run: gcloud run deploy ${{ github.event.repository.name }} --image=img\n"
                  "      - run: gcloud run services add-iam-policy-binding ${{ github.event.repository.name }} "
                  "--member=allUsers --role=roles/run.invoker\n")
            self._write(repo, workflow=wf, dockerfile="FROM x\nCMD [\"x\"]\n")
            self.assertEqual(run_devops_gate(repo, archetype="rest_api"), [])

    def test_services_update_allow_unauthenticated_is_always_flagged(self) -> None:
        # `gcloud run services update --allow-unauthenticated` is NOT a valid gcloud command — exits 2.
        # The gate must flag it unconditionally, even when a valid IAM binding is also present.
        with TemporaryDirectory() as td:
            repo = Path(td)
            # Workflow has both the correct IAM binding AND the invalid services update step (the real bug).
            wf = (
                "name: deploy\non:\n  push:\n    branches: [main]\n"
                "jobs:\n  deploy:\n    steps:\n"
                "      - uses: google-github-actions/deploy-cloudrun@v2\n"
                "        with:\n          service: ${{ github.event.repository.name }}\n"
                "          flags: '--allow-unauthenticated'\n"
                "      - run: gcloud run services add-iam-policy-binding ${{ github.event.repository.name }}"
                " --member=allUsers --role=roles/run.invoker\n"
                "      - env:\n          SERVICE: ${{ github.event.repository.name }}\n"
                "        run: gcloud run services update \"$SERVICE\" --region=us-central1"
                " --project=my-proj --allow-unauthenticated\n"
            )
            self._write(repo, workflow=wf, dockerfile="FROM python:3.12-slim\nCMD [\"python\", \"app.py\"]\n")
            problems = run_devops_gate(repo, archetype="rest_api")
            self.assertTrue(
                any("services update" in p and "--allow-unauthenticated" in p for p in problems),
                problems,
            )

    def test_services_update_allow_unauthenticated_alone_also_flagged_as_no_public_access(self) -> None:
        # When `services update --allow-unauthenticated` is the ONLY "grant" (no valid flag, no IAM binding),
        # the gate should fire BOTH the invalid-command error AND the missing-public-access error.
        with TemporaryDirectory() as td:
            repo = Path(td)
            wf = (
                "name: deploy\non:\n  push:\n    branches: [main]\n"
                "jobs:\n  deploy:\n    steps:\n"
                "      - uses: google-github-actions/deploy-cloudrun@v2\n"
                "        with:\n          service: ${{ github.event.repository.name }}\n"
                "      - env:\n          SERVICE: ${{ github.event.repository.name }}\n"
                "        run: gcloud run services update \"$SERVICE\" --allow-unauthenticated\n"
            )
            self._write(repo, workflow=wf, dockerfile="FROM python:3.12-slim\nCMD [\"python\", \"app.py\"]\n")
            problems = run_devops_gate(repo, archetype="rest_api")
            self.assertTrue(
                any("services update" in p and "--allow-unauthenticated" in p for p in problems),
                problems,
            )
            self.assertTrue(any("public invocation" in p for p in problems), problems)

    def test_hardcoded_service_name_is_flagged(self) -> None:
        # The overwrite-collision guard: a static service name (no repo-context derivation) lets one app
        # clobber another's Cloud Run service. A public, well-formed workflow is still flagged for naming.
        with TemporaryDirectory() as td:
            repo = Path(td)
            wf = ("name: deploy\non:\n  push:\n    branches: [main]\n"
                  "jobs:\n  deploy:\n    steps:\n      - uses: google-github-actions/deploy-cloudrun@v2\n"
                  "        with:\n          service: fastapi-echo-service\n"
                  "          flags: '--allow-unauthenticated'\n")
            self._write(repo, workflow=wf, dockerfile="FROM python:3.12-slim\nCMD [\"python\", \"app.py\"]\n")
            problems = run_devops_gate(repo, archetype="rest_api")
            self.assertTrue(any("hardcodes" in p and "service name" in p for p in problems), problems)

    def test_manifest_deploy_with_flag_only_is_flagged(self) -> None:
        # The 403 hole the user hit: a service.yaml manifest deploy (`gcloud run services replace`) where
        # `--allow-unauthenticated` is present but inert — IAM lives outside the spec, so the flag is a
        # false-positive. The gate must demand the explicit allUsers→run.invoker binding in manifest mode.
        with TemporaryDirectory() as td:
            repo = Path(td)
            wf = ("name: deploy\non:\n  push:\n    branches: [main]\n"
                  "jobs:\n  deploy:\n    steps:\n"
                  "      - run: gcloud run services replace service.yaml --region=europe-central2\n"
                  "      - uses: google-github-actions/deploy-cloudrun@v2\n"
                  "        with:\n          flags: '--allow-unauthenticated'\n")
            self._write(repo, workflow=wf, dockerfile="FROM python:3.12-slim\nCMD [\"python\", \"app.py\"]\n")
            problems = run_devops_gate(repo, archetype="rest_api")
            self.assertTrue(any("manifest" in p and "allUsers" in p for p in problems), problems)

    def test_manifest_deploy_with_iam_binding_passes(self) -> None:
        # Same manifest deploy, but now with the explicit IAM binding — the mode-independent grant passes.
        with TemporaryDirectory() as td:
            repo = Path(td)
            wf = ("name: deploy\non:\n  push:\n    branches: [main]\n"
                  "jobs:\n  deploy:\n    steps:\n"
                  "      - run: gcloud run services replace service.yaml --region=europe-central2\n"
                  "      - run: gcloud run services add-iam-policy-binding ${{ github.event.repository.name }} "
                  "--member=allUsers --role=roles/run.invoker\n")
            self._write(repo, workflow=wf, dockerfile="FROM python:3.12-slim\nCMD [\"python\", \"app.py\"]\n")
            self.assertEqual(run_devops_gate(repo, archetype="rest_api"), [])

    def test_cli_archetype_skips_public_invoker_check(self) -> None:
        # A CLI deploys to GitHub Releases (no public-invoker requirement); a None archetype skips too.
        with TemporaryDirectory() as td:
            repo = Path(td)
            self._write(repo, workflow="name: build\non:\n  push: {}\n")  # no Dockerfile, no grant — fine
            self.assertEqual(run_devops_gate(repo, archetype="cli_tool"), [])
            self.assertEqual(run_devops_gate(repo), [])

    def test_format_built_readme_run_step_is_flagged(self) -> None:
        # The live defect: the README-URL step was assembled via `${{ format(...) }}`, whose literal doubles
        # single quotes ('→'') — the doubling leaked into the shell and broke the printf fallback, appending a
        # stray `##` instead of the URL. The gate forbids any `run:` step built from a format() expression.
        with TemporaryDirectory() as td:
            repo = Path(td)
            wf = ("name: deploy\non:\n  push: {}\n"
                  "jobs:\n  deploy:\n    steps:\n"
                  "      - name: Update README with deployment URL\n"
                  "        run: ${{ format('printf ''##''\\n', steps.deploy.outputs.url) }}\n")
            self._write(repo, workflow=wf)
            problems = run_devops_gate(repo)
            self.assertTrue(any("format(" in p for p in problems), problems)

    def test_url_step_without_seeded_readme_markers_is_flagged(self) -> None:
        # If the workflow injects the URL between markers the README does not carry, the in-place replace is a
        # no-op and the step degrades to its fragile append fallback — the second half of the live defect.
        with TemporaryDirectory() as td:
            repo = Path(td)
            wf = ("name: deploy\non:\n  push: {}\n"
                  "jobs:\n  deploy:\n    steps:\n"
                  "      - name: Update README with deployment URL\n"
                  "        run: |\n"
                  "          grep -q DEPLOYMENT_URL_START README.md\n")
            self._write(repo, workflow=wf)
            (repo / "README.md").write_text("# App\nNo markers here.\n", encoding="utf-8")
            problems = run_devops_gate(repo)
            self.assertTrue(any("DEPLOYMENT_URL_START" in p and "marker" in p for p in problems), problems)

    def test_url_step_with_seeded_readme_markers_passes(self) -> None:
        # The correct shape: a literal `run:` block + the marker pair pre-seeded into README.md → clean.
        with TemporaryDirectory() as td:
            repo = Path(td)
            wf = ("name: deploy\non:\n  push: {}\n"
                  "jobs:\n  deploy:\n    steps:\n"
                  "      - name: Update README with deployment URL\n"
                  "        run: |\n"
                  "          grep -q DEPLOYMENT_URL_START README.md\n")
            self._write(repo, workflow=wf)
            (repo / "README.md").write_text(
                "# App\n## Deployment\n<!-- DEPLOYMENT_URL_START -->\n<!-- DEPLOYMENT_URL_END -->\n",
                encoding="utf-8",
            )
            self.assertEqual(run_devops_gate(repo), [])


class ArchetypeGuidanceTests(unittest.TestCase):
    """The assembled DevOps guidance must carry BOTH the archetype skills (app shape) AND the deploy-target
    PLATFORM skills (deploy mechanics) — the latter registry-driven via deploy_target_skills()."""

    def test_includes_app_shape_and_platform_skills(self) -> None:
        guidance = devops._archetype_guidance()
        self.assertIn("Multi-stage build", guidance)              # rest_api archetype (app shape)
        self.assertIn("allow-unauthenticated", guidance)          # deploy_gcp platform skill (the 403 fix)
        self.assertIn("github.event.repository.name", guidance)   # deploy_gcp: repo-derived service name (no overwrite)
        self.assertIn("workload_identity_provider", guidance)     # deploy_gcp: WIF auth preserved
        self.assertIn("softprops/action-gh-release", guidance)    # deploy_github_release platform skill


class JinjaSystemMessageRelocationTests(unittest.TestCase):
    """Regression for the instructor GenAI guard that rejects {{ }} / {% %} in a SYSTEM message.

    The DevOps agent's prompt teaches GitHub Actions `${{ secrets.* }}` / `${{ vars.* }}` syntax, which
    tripped extract_genai_system_message and crashed E4 deterministically (3 identical retries). The
    run_structured_llm seam relocates such a system message into a user turn — where the marker is
    neither guard-checked nor (absent a Jinja context) rendered — so the literal reaches the model intact.
    """

    def test_clean_messages_pass_through_unchanged(self) -> None:
        msgs = [{"role": "system", "content": "plain instructions, no templates"},
                {"role": "user", "content": "do the thing"}]
        self.assertIs(_relocate_jinja_system_messages(msgs), msgs)   # identity: no-op for marker-free roles

    def test_jinja_system_message_is_demoted_to_user(self) -> None:
        msgs = [{"role": "system", "content": "auth via ${{ secrets.GCP_WIF_PROVIDER }}"},
                {"role": "user", "content": "ship it"}]
        out = _relocate_jinja_system_messages(msgs)
        self.assertEqual(out[0]["role"], "user")                            # demoted off the system role
        self.assertIn("${{ secrets.GCP_WIF_PROVIDER }}", out[0]["content"])  # literal preserved verbatim
        self.assertEqual(out[1], {"role": "user", "content": "ship it"})    # the real user turn untouched
        self.assertFalse(any(m["role"] == "system" for m in out))          # nothing left for the guard
        self.assertIsNot(out, msgs)                                        # original list not mutated

    def test_statement_marker_also_triggers_relocation(self) -> None:
        msgs = [{"role": "system", "content": "loop {% for x in y %}{% endfor %}"}]
        self.assertEqual(_relocate_jinja_system_messages(msgs)[0]["role"], "user")

    def test_real_devops_system_prompt_is_cleared_by_the_seam(self) -> None:
        # The exact system message the node assembles (system prompt + the three archetype skills). Proves
        # the crash trigger is real, and that after the seam no system message would trip instructor's guard.
        system_prompt = f"{devops.get_system_prompt('devops')}\n\n{devops._archetype_guidance()}"
        self.assertRegex(system_prompt, r"{{.*?}}")   # the real prompt genuinely carries the marker
        out = _relocate_jinja_system_messages(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": "go"}]
        )
        self.assertFalse(
            any(m["role"] == "system" and re.search(r"{{.*?}}|{%.*?%}", m["content"]) for m in out)
        )


class ScaffoldBudgetTests(unittest.IsolatedAsyncioTestCase):
    """E5 — the E4 deploy phase enforces the threaded remaining budget and, even when an exhaustion mid
    self-heal raises PipelineHalt, folds its partial spend into the application-wide accumulator (the
    finally-merge) so the batch's app report stays accurate."""

    async def test_budget_halt_midphase_still_merges_partial_spend(self) -> None:
        from decimal import Decimal
        from src.deployment.provision import scaffold
        from src.nexus.runner import PipelineHalt
        from src.shared.core.models import PipelineTelemetry

        with TemporaryDirectory() as td:
            repo = Path(td) / "repo"; (repo).mkdir(parents=True, exist_ok=True)
            reports = Path(td) / "reports"; reports.mkdir(parents=True, exist_ok=True)
            ws = WorkspacePaths(logs_dir=Path(td) / "logs", reports_dir=reports, repo_dir=repo)

            project = mock.MagicMock(); project.slug = "p"; project.repo = "r"; project.base_branch = "main"
            projects = mock.MagicMock(); projects.allocate.return_value = Path(td) / "001_devops"
            cfg = scaffold.RunConfig(description=None, base_branch="main", resume=None, reset_attempts=False, repo="r")
            app_tel = PipelineTelemetry()

            async def _spend(ctx, **_kw):
                # The DevOps generation "spends" $0.50 — over the $0.10 remaining ceiling below.
                ctx.telemetry.record("DevOps Agent", 1000, 200, "0.50", provider="gemini", plane="deployment")

            with (
                mock.patch.object(scaffold, "reconfigure_logging"),
                mock.patch.object(scaffold, "bootstrap_session", new=AsyncMock(return_value=ws)),
                mock.patch.object(scaffold, "_repo_has_source", return_value=True),
                mock.patch.object(scaffold, "generate_repo_map", return_value="map"),
                mock.patch.object(scaffold, "_nexus_environment_ids", return_value=""),
                mock.patch.object(scaffold, "run_devops_node", new=AsyncMock(side_effect=_spend)),
                mock.patch.object(scaffold, "run_devops_gate", return_value=[]),
            ):
                with self.assertRaises(PipelineHalt):
                    await scaffold.run_devops_scaffold(
                        projects, project, cfg, Path(td),
                        budget_usd_ceiling=Decimal("0.10"), app_telemetry=app_tel,
                    )

            # The partial DevOps spend was folded into the application total via the finally-merge…
            self.assertEqual(app_tel.total_cost_usd, Decimal("0.50"))
            self.assertEqual(app_tel.by_plane()["deployment"]["calls"], 1)
            # …and the devops run still wrote its own incident report (auditable spend).
            self.assertTrue((reports / "incident_report.json").exists())


if __name__ == "__main__":
    unittest.main()
