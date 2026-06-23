"""Unit tests for the SDLC contract models and workspace bootstrap.

Filesystem is fully isolated: every WorkspacePaths construction either patches
``Path.mkdir`` or targets a TemporaryDirectory, so the suite never writes to the repo.
"""
import unittest
from decimal import Decimal
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import mock
from pydantic import ValidationError

from src.shared.core.models import (
    PipelineTelemetry,
    ArchitectureUpdate,
    TechLeadContract,
    TopologyNode,
    GlobalPipelineContext,
    QATestSuite,
    ReviewReport,
    WorkspacePaths,
    BatchState,
    DevOpsManifests,
)


class ArchitectureUpdateModelTests(unittest.TestCase):
    """The TechWriter's structured output round-trips its single cumulative-document field."""

    def test_round_trips_document_field(self) -> None:
        doc = "# Architecture State\n\n## Invariants\n- Streaming: row-by-row only.\n"
        update = ArchitectureUpdate(updated_architecture_document=doc)
        self.assertEqual(update.updated_architecture_document, doc)

    def test_document_field_is_required(self) -> None:
        with self.assertRaises(ValidationError):
            ArchitectureUpdate()


class QATestSuiteFenceCleaningTests(unittest.TestCase):
    """Validator ``clean_markdown_fences`` must strip LLM markdown artifacts."""

    def test_strips_python_language_fence(self) -> None:
        # Arrange
        raw = "```python\nprint('hi')\n```"
        # Act
        suite = QATestSuite(new_test_code=raw)
        # Assert
        self.assertEqual(suite.new_test_code, "print('hi')")

    def test_language_fence_is_case_insensitive(self) -> None:
        # Arrange
        raw = "```PYTHON\nimport os\n```"
        # Act
        suite = QATestSuite(new_test_code=raw)
        # Assert
        self.assertEqual(suite.new_test_code, "import os")

    def test_strips_bare_fence_without_language(self) -> None:
        # Arrange
        raw = "```\nx = 1\n```"
        # Act
        suite = QATestSuite(new_test_code=raw)
        # Assert
        self.assertEqual(suite.new_test_code, "x = 1")

    def test_tolerates_trailing_whitespace_after_language_tag(self) -> None:
        # Arrange
        raw = "```python   \ndef f():\n    return 1\n```"
        # Act
        suite = QATestSuite(new_test_code=raw)
        # Assert
        self.assertEqual(suite.new_test_code, "def f():\n    return 1")

    def test_trims_blank_edges_when_no_fence_present(self) -> None:
        # Arrange
        raw = "\n\n   value = 42   \n\n"
        # Act
        suite = QATestSuite(new_test_code=raw)
        # Assert
        self.assertEqual(suite.new_test_code, "value = 42")

    def test_clean_code_passes_through_unchanged(self) -> None:
        # Arrange
        raw = "def add(a: int, b: int) -> int:\n    return a + b"
        # Act
        suite = QATestSuite(new_test_code=raw)
        # Assert
        self.assertEqual(suite.new_test_code, raw)

    def test_internal_fence_like_text_is_preserved(self) -> None:
        # Arrange — only edge fences are stripped, not interior content.
        raw = "s = '```not a fence```'"
        # Act
        suite = QATestSuite(new_test_code=raw)
        # Assert
        self.assertEqual(suite.new_test_code, "s = '```not a fence```'")


class WorkspacePathsTests(unittest.TestCase):
    """Workspace bootstrap requires explicit paths and creates the work tree on disk."""

    @staticmethod
    def _explicit(base: Path) -> dict[str, Path]:
        return {
            "logs_dir": base / "logs",
            "reports_dir": base / "reports",
            "repo_dir": base,
        }

    def test_bare_construction_is_rejected(self) -> None:
        # No implicit fallback tree — every path must be supplied (via `for_run` in production).
        with self.assertRaises(ValidationError):
            WorkspacePaths()

    def test_post_init_creates_each_dir_recursively_and_idempotently(self) -> None:
        # Arrange / Act
        with mock.patch.object(Path, "mkdir") as mkdir:
            WorkspacePaths(**self._explicit(Path("/tmp/sandbox")))
        # Assert — every directory is created with parents + exist_ok.
        self.assertTrue(mkdir.call_args_list)
        for call in mkdir.call_args_list:
            self.assertEqual(call, mock.call(parents=True, exist_ok=True))

    def test_explicit_paths_are_honoured(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            fields = self._explicit(Path(td))
            # Act
            paths = WorkspacePaths(**fields)
            # Assert — paths are stored verbatim and the meta dirs materialise on disk.
            self.assertEqual(paths.repo_dir, fields["repo_dir"])
            for d in (paths.logs_dir, paths.reports_dir):
                self.assertTrue(d.is_dir())


class WorkspacePathsForRunTests(unittest.TestCase):
    """Git-anchored mapping resolves absolute paths and blocks traversal escapes."""

    def _make_run(self, base: Path) -> tuple[Path, Path]:
        run_dir = base / "run_abc"
        repo_dir = run_dir / "repo"
        repo_dir.mkdir(parents=True)
        return run_dir, repo_dir

    def test_maps_repo_root_and_meta_state_outside_clone(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            run_dir, repo_dir = self._make_run(Path(td))
            # Act
            paths = WorkspacePaths.for_run(run_dir, repo_dir)
            # Assert — repo root is the clone; logs/reports stay outside it. Source/test layout is
            # no longer fixed here (contract-/profile-driven), so no code_dir/tests_dir to map.
            self.assertEqual(paths.repo_dir, repo_dir.resolve())
            self.assertEqual(paths.logs_dir, (run_dir / "logs").resolve())
            self.assertEqual(paths.reports_dir, (run_dir / "reports").resolve())
            self.assertFalse(paths.logs_dir.is_relative_to(repo_dir.resolve()))


class ContractModelTests(unittest.TestCase):
    """Pydantic contracts parse expected payloads and defaults."""

    def test_techlead_contract_round_trips_fields(self) -> None:
        # Arrange
        payload = {
            "files_to_modify": ["src/core/calc.py"],
            "topology_contract": [
                {"file_path": "src/core/calc.py", "exports": ["is_prime"], "depends_on": []}
            ],
            "instruction": "Implement prime sieve.",
            "function_signatures": "def is_prime(n: int) -> bool",
            "strict_type_validation_rules": "bool must raise TypeError",
            "techlead_reasoning": "Guard against bool subtype of int.",
            "environment_id": "python-3.12-core",
        }
        # Act
        contract = TechLeadContract(**payload)
        # Assert
        self.assertEqual(contract.files_to_modify, ["src/core/calc.py"])
        self.assertIn("TypeError", contract.strict_type_validation_rules)
        # shared_context is optional and defaults to empty (keeps legacy payloads/checkpoints valid).
        self.assertEqual(contract.shared_context, "")

    def test_shared_context_round_trips_when_supplied(self) -> None:
        payload = {
            "files_to_modify": ["src/core/calc.py"],
            "topology_contract": [
                {"file_path": "src/core/calc.py", "exports": ["is_prime"], "depends_on": []}
            ],
            "instruction": "Implement prime sieve.",
            "shared_context": "A CLI tool that reports whether a number is prime.",
            "function_signatures": "def is_prime(n: int) -> bool",
            "strict_type_validation_rules": "bool must raise TypeError",
            "techlead_reasoning": "Guard against bool subtype of int.",
            "environment_id": "python-3.12-core",
        }
        contract = TechLeadContract(**payload)
        self.assertEqual(contract.shared_context, "A CLI tool that reports whether a number is prime.")

    def test_leading_slash_paths_are_normalized_to_repo_relative(self) -> None:
        # Regression: blueprint topology uses leading slashes (`/.gitignore`, `/cmd/app/main.go`).
        # Joined onto repo_dir they go ABSOLUTE and escape the write sandbox / read as missing.
        payload = {
            "files_to_modify": ["/.gitignore", "/cmd/app/main.go", "go.mod", ".\\nested\\x.go"],
            "topology_contract": [
                {"file_path": "/cmd/app/main.go", "exports": ["main"], "depends_on": []}
            ],
            "instruction": "noop",
            "function_signatures": "func main()",
            "strict_type_validation_rules": "noop",
            "techlead_reasoning": "noop",
            "environment_id": "go-1.23-cli",
        }
        contract = TechLeadContract(**payload)
        self.assertEqual(
            contract.files_to_modify,
            [".gitignore", "cmd/app/main.go", "go.mod", "nested/x.go"],
        )
        # Joining the normalized path onto a root now stays INSIDE the root.
        self.assertFalse(str(Path("/repo") / contract.files_to_modify[0]).endswith(":/.gitignore"))
        self.assertEqual(contract.topology_contract[0].file_path, "cmd/app/main.go")

    def test_traversal_path_is_rejected(self) -> None:
        payload = {
            "files_to_modify": ["../../etc/passwd"],
            "topology_contract": [
                {"file_path": "src/x.py", "exports": [], "depends_on": []}
            ],
            "instruction": "noop",
            "function_signatures": "noop",
            "strict_type_validation_rules": "noop",
            "techlead_reasoning": "noop",
            "environment_id": "python-3.12-core",
        }
        with self.assertRaises(ValidationError):
            TechLeadContract(**payload)

    def test_topology_contract_is_required(self) -> None:
        # Omitting the language-neutral dependency graph must fail validation (strict SSOT).
        payload = {
            "files_to_modify": ["src/core/calc.py"],
            "instruction": "noop",
            "function_signatures": "def is_prime(n: int) -> bool",
            "strict_type_validation_rules": "noop",
            "techlead_reasoning": "noop",
            "environment_id": "python-3.12-core",
        }
        with self.assertRaises(ValidationError):
            TechLeadContract(**payload)

    def test_topology_node_round_trips_fields(self) -> None:
        node = TopologyNode(
            file_path="src/geometry/shapes.py",
            exports=["Circle"],
            depends_on=["src/math_utils/validation.py:validate_positive"],
        )
        self.assertEqual(node.file_path, "src/geometry/shapes.py")
        self.assertEqual(node.exports, ["Circle"])
        self.assertEqual(node.depends_on, ["src/math_utils/validation.py:validate_positive"])

    def test_review_report_requires_explicit_approval_flags(self) -> None:
        # Arrange / Act
        report = ReviewReport(
            code_quality_analysis="clean",
            test_integrity_analysis="no softening",
            log_verification_analysis="bandit clean",
            code_quality_approved=True,
            test_integrity_approved=False,
            qa_diagnostic_payload="tighten assertions",
        )
        # Assert
        self.assertTrue(report.code_quality_approved)
        self.assertFalse(report.test_integrity_approved)

    def test_global_context_applies_defaults(self) -> None:
        # Arrange / Act
        ctx = GlobalPipelineContext(pr_description="add prime util")
        # Assert
        self.assertEqual(ctx.base_branch, "main")
        self.assertIsNone(ctx.contract)
        self.assertIsNone(ctx.review_report)
        self.assertEqual(ctx.production_code_snapshot, {})
        self.assertEqual(ctx.current_attempt, 1)
        # Unbound until the orchestrator maps a git-anchored session via `for_run`.
        self.assertIsNone(ctx.workspace_paths)
        self.assertIsInstance(ctx.telemetry, PipelineTelemetry)
        self.assertEqual(ctx.telemetry.total_tokens, 0)


class PipelineTelemetryTests(unittest.TestCase):
    """Cumulative token/cost accounting feeding the Financial Circuit Breaker."""

    def test_record_accumulates_per_agent_and_global_totals(self) -> None:
        # Arrange
        tel = PipelineTelemetry()
        # Act — two TechLead calls and one Developer call.
        tel.record("TechLead", 100, 20, 0.0)
        tel.record("TechLead", 50, 10, 0.0)
        tel.record("Developer Agent", 1000, 200, 0.05)
        # Assert — global totals.
        self.assertEqual(tel.total_tokens, 100 + 20 + 50 + 10 + 1000 + 200)
        self.assertEqual(tel.total_cost_usd, Decimal("0.05"))  # exact — no float drift
        # Assert — per-agent breakdown.
        tl = tel.by_agent["TechLead"]
        self.assertEqual((tl.input_tokens, tl.output_tokens, tl.total_tokens, tl.calls), (150, 30, 180, 2))
        dev = tel.by_agent["Developer Agent"]
        self.assertEqual((dev.total_tokens, dev.calls), (1200, 1))
        self.assertEqual(dev.cost_usd, Decimal("0.05"))

    def test_cache_tokens_are_excluded_from_budget_total(self) -> None:
        # Arrange — a Claude call dominated by cheap cache reads, like the agentic CLI produces.
        tel = PipelineTelemetry()
        # Act
        tel.record(
            "Developer Agent", 100, 20, Decimal("0.14"), provider="claude",
            cache_read_tokens=200_000, cache_write_tokens=8_000,
        )
        # Assert — the budget total counts only fresh input + output; cache is tracked but NOT budgeted.
        self.assertEqual(tel.total_tokens, 120)                 # 100 + 20, cache excluded
        self.assertEqual(tel.total_cache_read_tokens, 200_000)
        self.assertEqual(tel.total_cache_write_tokens, 8_000)
        dev = tel.by_agent["Developer Agent"]
        self.assertEqual((dev.total_tokens, dev.cache_read_tokens, dev.cache_write_tokens), (120, 200_000, 8_000))
        self.assertEqual(tel.total_cost_usd, Decimal("0.14"))   # money is the real spend signal

    def test_by_provider_and_finops_report(self) -> None:
        # Arrange — two providers with distinct token/cost footprints.
        tel = PipelineTelemetry()
        tel.record("TechLead", 100, 20, 0.0003, provider="gemini")
        tel.record("QA Agent", 50, 10, 0.0002, provider="gemini")
        tel.record("Developer Agent", 1000, 200, 0.1328, provider="claude", cache_read_tokens=50_000)
        # Act
        bp = tel.by_provider()
        report = tel.finops_report(budget_tokens=10_000, budget_usd=Decimal("1.00"))
        # Assert — per-provider aggregation (cache excluded from token totals).
        self.assertEqual(bp["gemini"]["tokens"], 180)
        self.assertEqual(bp["gemini"]["cost_usd"], Decimal("0.0005"))
        self.assertEqual(bp["claude"]["tokens"], 1200)
        self.assertEqual(bp["claude"]["cost_usd"], Decimal("0.1328"))
        # Assert — token budget math (1380 / 10000 = 13.8%), cache surfaced separately.
        self.assertEqual(report["total_tokens"], 1380)
        self.assertEqual(report["budget_tokens"], 10_000)
        self.assertAlmostEqual(report["budget_used_pct"], 13.8)
        self.assertEqual(report["total_cache_read_tokens"], 50_000)
        # Assert — USD budget is the primary signal: $0.1333 / $1.00 = 13.33%.
        self.assertEqual(report["budget_usd"], Decimal("1.000000"))
        self.assertAlmostEqual(report["budget_used_pct_usd"], 13.33)
        self.assertIn("gemini", report["by_provider"])
        self.assertEqual(report["by_agent"]["Developer Agent"]["provider"], "claude")

    def test_telemetry_survives_checkpoint_round_trip(self) -> None:
        # Arrange
        ctx = GlobalPipelineContext(pr_description="x")
        ctx.telemetry.record("Developer Agent", 1000, 200, 0.05)
        # Act — serialize and reload (the resume path uses model_validate_json).
        restored = GlobalPipelineContext.model_validate_json(ctx.model_dump_json())
        # Assert — the budget signal is preserved across persistence.
        self.assertEqual(restored.telemetry.total_tokens, 1200)
        self.assertEqual(restored.telemetry.total_cost_usd, Decimal("0.05"))
        self.assertEqual(restored.telemetry.by_agent["Developer Agent"].calls, 1)

    def test_old_checkpoint_without_telemetry_loads_with_default(self) -> None:
        # Arrange — a checkpoint payload predating the telemetry field.
        ctx = GlobalPipelineContext(pr_description="x")
        payload = ctx.model_dump()
        payload.pop("telemetry", None)
        # Act — load it back (backward-compatibility: default_factory fills the gap).
        restored = GlobalPipelineContext.model_validate(payload)
        # Assert
        self.assertIsInstance(restored.telemetry, PipelineTelemetry)
        self.assertEqual(restored.telemetry.total_tokens, 0)


class NeedsTestRegenerationTests(unittest.TestCase):
    """Initial recovery decision: regenerate tests on rejection or when no snapshot exists."""

    def _context(self, **kwargs) -> GlobalPipelineContext:
        return GlobalPipelineContext(pr_description="x", **kwargs)

    def _report(self, *, test_integrity_approved: bool) -> ReviewReport:
        return ReviewReport(
            code_quality_analysis="",
            test_integrity_analysis="",
            log_verification_analysis="",
            code_quality_approved=True,
            test_integrity_approved=test_integrity_approved,
            dev_diagnostic_payload="",
        )

    def test_rejected_tests_force_regeneration_even_with_snapshot(self) -> None:
        ctx = self._context(
            test_code_snapshot="assert True",
            review_report=self._report(test_integrity_approved=False),
        )
        self.assertTrue(ctx.needs_test_regeneration())

    def test_no_report_no_snapshot_regenerates(self) -> None:
        ctx = self._context()
        self.assertTrue(ctx.needs_test_regeneration())

    def test_no_report_with_snapshot_skips(self) -> None:
        ctx = self._context(test_code_snapshot="assert True")
        self.assertFalse(ctx.needs_test_regeneration())

    def test_approved_tests_with_snapshot_skips(self) -> None:
        ctx = self._context(
            test_code_snapshot="assert True",
            review_report=self._report(test_integrity_approved=True),
        )
        self.assertFalse(ctx.needs_test_regeneration())


class GlobalContextCheckpointTests(unittest.TestCase):
    """Checkpoint save/load APIs must persist and restore full context state."""

    def test_checkpoint_round_trip_preserves_core_fields(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                logs_dir=base / "logs",
                reports_dir=base / "reports",
                repo_dir=base,
            )
            ctx = GlobalPipelineContext(
                pr_description="ship checkpoint support",
                base_branch="main",
                workspace_paths=paths,
                production_code_snapshot={"src/m.py": "print('ok')"},
                test_code_snapshot="assert True",
                error_trace="none",
            )
            checkpoint = paths.reports_dir / "checkpoint.json"

            # Act
            ctx.save_checkpoint(checkpoint)
            loaded = GlobalPipelineContext.load_checkpoint(checkpoint)

            # Assert
            self.assertEqual(loaded.pr_description, "ship checkpoint support")
            self.assertEqual(loaded.production_code_snapshot, {"src/m.py": "print('ok')"})
            self.assertEqual(loaded.test_code_snapshot, "assert True")
            self.assertEqual(loaded.error_trace, "none")

    def test_workspace_paths_round_trip_back_to_path_instances(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                logs_dir=base / "logs",
                reports_dir=base / "reports",
                repo_dir=base,
            )
            checkpoint = base / "checkpoint.json"
            GlobalPipelineContext(pr_description="p", workspace_paths=paths).save_checkpoint(checkpoint)

            # Act
            loaded = GlobalPipelineContext.load_checkpoint(checkpoint)

            # Assert
            self.assertIsInstance(loaded.workspace_paths.repo_dir, Path)
            self.assertIsInstance(loaded.workspace_paths.logs_dir, Path)
            self.assertIsInstance(loaded.workspace_paths.reports_dir, Path)

    def test_load_checkpoint_raises_for_invalid_json(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            checkpoint = Path(td) / "checkpoint.json"
            checkpoint.write_text("{broken json", encoding="utf-8")

            # Act / Assert
            with self.assertRaises(ValidationError):
                GlobalPipelineContext.load_checkpoint(checkpoint)


class BatchStateCheckpointTests(unittest.TestCase):
    """E3 batch checkpoint: persists which tickets of a Nexus plan have merged, for resume."""

    def test_round_trip_preserves_progress(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "reports" / "batch_state.json"
            BatchState(
                project_slug="my-proj", nexus_run="001_nexus_plan",
                tickets=["TASK-01", "TASK-02", "TASK-03"],
                completed=["TASK-01"], failed="TASK-02",
            ).save_checkpoint(path)

            loaded = BatchState.load_checkpoint(path)
            self.assertEqual(loaded.kind, "batch")
            self.assertEqual(loaded.project_slug, "my-proj")
            self.assertEqual(loaded.tickets, ["TASK-01", "TASK-02", "TASK-03"])
            self.assertEqual(loaded.completed, ["TASK-01"])
            self.assertEqual(loaded.failed, "TASK-02")

    def test_defaults_are_empty(self) -> None:
        batch = BatchState(project_slug="p", nexus_run="001_nexus_plan")
        self.assertEqual(batch.tickets, [])
        self.assertEqual(batch.completed, [])
        self.assertIsNone(batch.failed)


class DevOpsManifestsModelTests(unittest.TestCase):
    """E4 DevOps output: round-trips its fields; the archetype is a closed enum; Dockerfile is optional."""

    def test_round_trip_web_service(self) -> None:
        m = DevOpsManifests(
            archetype="rest_api",
            dockerfile_content="FROM python:3.12-slim\nCMD [\"python\"]\n",
            workflow_content="name: deploy\non: push\n",
            env_scaffold_content="PORT=8080\n",
            engineering_reasoning="web service → Cloud Run",
        )
        loaded = DevOpsManifests.model_validate_json(m.model_dump_json())
        self.assertEqual(loaded.archetype, "rest_api")
        self.assertEqual(loaded.dockerfile_content, m.dockerfile_content)
        self.assertEqual(loaded.workflow_content, m.workflow_content)

    def test_cli_tool_allows_null_dockerfile(self) -> None:
        m = DevOpsManifests(archetype="cli_tool", workflow_content="name: build\non: push\n",
                            engineering_reasoning="CLI → build matrix")
        self.assertIsNone(m.dockerfile_content)
        self.assertIsNone(m.env_scaffold_content)

    def test_invalid_archetype_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            DevOpsManifests(archetype="lambda", workflow_content="x", engineering_reasoning="r")

    def test_workflow_and_reasoning_are_required(self) -> None:
        with self.assertRaises(ValidationError):
            DevOpsManifests(archetype="rest_api")


if __name__ == "__main__":
    unittest.main()
