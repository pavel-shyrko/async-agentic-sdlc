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
    DocumentationUpdate,
    TechLeadContract,
    TopologyNode,
    BehaviorExample,
    GlobalPipelineContext,
    QATestSuite,
    ReviewReport,
    WorkspacePaths,
    BatchState,
    DevOpsManifests,
)


class DocumentationUpdateModelTests(unittest.TestCase):
    """The TechWriter's structured output round-trips its three cumulative-document fields."""

    def test_round_trips_document_fields(self) -> None:
        adr = "# Architecture State\n\n## Invariants\n- Streaming: row-by-row only.\n"
        readme = "# My Project\n\nDoes a thing.\n"
        changelog = "# Changelog\n\n## [Unreleased]\n### Added\n- Initial.\n"
        update = DocumentationUpdate(
            architecture_document=adr, readme=readme, changelog=changelog, usage_guide="# Usage\n",
        )
        self.assertEqual(update.architecture_document, adr)
        self.assertEqual(update.readme, readme)
        self.assertEqual(update.changelog, changelog)
        self.assertEqual(update.usage_guide, "# Usage\n")

    def test_usage_guide_defaults_to_empty(self) -> None:
        # usage_guide is authored only on the final ticket; it must be optional (default "") so every
        # earlier ticket's structured response validates without it.
        update = DocumentationUpdate(architecture_document="# a", readme="# b", changelog="# c")
        self.assertEqual(update.usage_guide, "")

    def test_core_doc_fields_are_required(self) -> None:
        with self.assertRaises(ValidationError):
            DocumentationUpdate(architecture_document="# only adr")


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

    def test_acceptance_examples_default_to_empty(self) -> None:
        # Back-compat: legacy contracts/checkpoints without the oracle field stay valid (empty list).
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
        self.assertEqual(TechLeadContract(**payload).acceptance_examples, [])

    def test_acceptance_examples_round_trip(self) -> None:
        # The behavioral oracle parses as structured BehaviorExample objects (input → expected | raises).
        payload = {
            "files_to_modify": ["src/core/calc.py"],
            "topology_contract": [
                {"file_path": "src/core/calc.py", "exports": ["is_prime"], "depends_on": []}
            ],
            "instruction": "Implement prime sieve.",
            "function_signatures": "def is_prime(n: int) -> bool",
            "acceptance_examples": [
                {"input": "is_prime(2)", "expected": "True"},
                {"input": "is_prime(-1.0)", "raises": "TypeError"},
            ],
            "strict_type_validation_rules": "bool must raise TypeError",
            "techlead_reasoning": "Guard against bool subtype of int.",
            "environment_id": "python-3.12-core",
        }
        contract = TechLeadContract(**payload)
        self.assertEqual(len(contract.acceptance_examples), 2)
        self.assertIsInstance(contract.acceptance_examples[0], BehaviorExample)
        self.assertEqual(contract.acceptance_examples[0].expected, "True")
        self.assertEqual(contract.acceptance_examples[1].raises, "TypeError")
        self.assertEqual(contract.acceptance_examples[1].expected, "")  # output OR error, defaults empty

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


class ReviewReportPayloadValidatorTests(unittest.TestCase):
    """The routing-coherence validator (`_require_routing_coherence`) code-enforces the feedback-channel
    invariant the prompt alone could not: BACKLOG #17 (a rejection MUST carry an actionable payload), #18
    (the converse — an approved side must NOT carry a payload, so the router never feeds a defect-free
    channel), and #11 (a production rejection must cite verbatim evidence). instructor re-prompts the
    Reviewer on the resulting ValueError instead of the loop silently burning the retry budget."""

    _base = dict(code_quality_analysis="a", test_integrity_analysis="b", log_verification_analysis="c")
    _cite = "AssertionError: expected 0 got 1 (writer.py:42)"

    def test_rejecting_code_without_dev_payload_raises(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewReport(**self._base, code_quality_approved=False, test_integrity_approved=True,
                         dev_diagnostic_payload="", qa_diagnostic_payload="")

    def test_rejecting_tests_without_qa_payload_raises(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewReport(**self._base, code_quality_approved=True, test_integrity_approved=False,
                         dev_diagnostic_payload="", qa_diagnostic_payload="")

    def test_whitespace_only_payload_is_treated_as_empty(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewReport(**self._base, code_quality_approved=True, test_integrity_approved=False,
                         qa_diagnostic_payload="   \n ")

    def test_rejection_with_payload_passes(self) -> None:
        ok = ReviewReport(**self._base, code_quality_approved=False, test_integrity_approved=False,
                          dev_diagnostic_payload="fix prod", qa_diagnostic_payload="fix tests",
                          dev_evidence_citation="AssertionError: expected 0 got 1 (writer.py:42)")
        self.assertFalse(ok.code_quality_approved)
        self.assertFalse(ok.test_integrity_approved)

    def test_full_approval_needs_no_payloads(self) -> None:
        ok = ReviewReport(**self._base, code_quality_approved=True, test_integrity_approved=True)
        self.assertTrue(ok.code_quality_approved)
        self.assertEqual(ok.qa_diagnostic_payload, "")

    # --- #18 converse: an approved side must NOT carry a payload ---
    def test_approved_code_with_dev_payload_raises(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewReport(**self._base, code_quality_approved=True, test_integrity_approved=True,
                         dev_diagnostic_payload="sneaky note on approved code")

    def test_approved_tests_with_qa_payload_raises(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewReport(**self._base, code_quality_approved=True, test_integrity_approved=True,
                         qa_diagnostic_payload="sneaky note on approved tests")

    # --- #11: a production rejection must cite verbatim evidence ---
    def test_rejecting_code_without_evidence_citation_raises(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewReport(**self._base, code_quality_approved=False, test_integrity_approved=True,
                         dev_diagnostic_payload="fix prod", dev_evidence_citation="")

    def test_rejecting_code_with_evidence_citation_passes(self) -> None:
        ok = ReviewReport(**self._base, code_quality_approved=False, test_integrity_approved=True,
                          dev_diagnostic_payload="fix prod", dev_evidence_citation=self._cite)
        self.assertFalse(ok.code_quality_approved)
        self.assertEqual(ok.dev_evidence_citation, self._cite)

    def test_rejecting_tests_only_needs_no_evidence_citation(self) -> None:
        # A test-only rejection leaves production approved, so no production evidence is required.
        ok = ReviewReport(**self._base, code_quality_approved=True, test_integrity_approved=False,
                          qa_diagnostic_payload="rewrite the suite")
        self.assertFalse(ok.test_integrity_approved)
        self.assertEqual(ok.dev_evidence_citation, "")


class BehaviorExampleModelTests(unittest.TestCase):
    """The behavioral oracle is language-neutral DATA (no code), with expected OR raises, both optional."""

    def test_round_trips_and_defaults(self) -> None:
        ex = BehaviorExample(input="write_csv([])")
        self.assertEqual(ex.expected, "")
        self.assertEqual(ex.raises, "")
        ex2 = BehaviorExample(input="write_csv([])", expected="\\r\\n")
        self.assertEqual(ex2.expected, "\\r\\n")


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
        # Arrange — two providers with distinct token/cost footprints (+ plane/time, E5).
        tel = PipelineTelemetry()
        tel.record("TechLead", 100, 20, 0.0003, provider="gemini", plane="development", duration_seconds=1.5)
        tel.record("QA Agent", 50, 10, 0.0002, provider="gemini", plane="development", duration_seconds=2.0)
        tel.record("Developer Agent", 1000, 200, 0.1328, provider="claude", cache_read_tokens=50_000,
                   plane="development", duration_seconds=4.0)
        # Act
        bp = tel.by_provider()
        report = tel.finops_report(budget_usd=Decimal("1.00"))  # money-only signature (E5)
        # Assert — per-provider aggregation (cache excluded from token totals).
        self.assertEqual(bp["gemini"]["tokens"], 180)
        self.assertEqual(bp["gemini"]["cost_usd"], Decimal("0.0005"))
        self.assertEqual(bp["claude"]["tokens"], 1200)
        self.assertEqual(bp["claude"]["cost_usd"], Decimal("0.1328"))
        # Assert — tokens reported (no token budget anymore), cache surfaced separately.
        self.assertEqual(report["total_tokens"], 1380)
        self.assertNotIn("budget_tokens", report)       # token budget removed (money-only)
        self.assertNotIn("budget_used_pct", report)
        self.assertEqual(report["total_cache_read_tokens"], 50_000)
        # Assert — USD budget is the sole gate: $0.1333 / $1.00 = 13.33%.
        self.assertEqual(report["budget_usd"], Decimal("1.000000"))
        self.assertAlmostEqual(report["budget_used_pct_usd"], 13.33)
        self.assertIn("gemini", report["by_provider"])
        self.assertEqual(report["by_agent"]["Developer Agent"]["provider"], "claude")
        # Assert — time + per-plane rollup (E5).
        self.assertAlmostEqual(report["total_duration_seconds"], 7.5)
        self.assertEqual(report["by_plane"]["development"]["tokens"], 1380)
        self.assertEqual(report["by_plane"]["development"]["calls"], 3)
        self.assertAlmostEqual(float(report["by_plane"]["development"]["duration_seconds"]), 7.5)

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

    def test_record_phase_accumulates_infra_and_real_wall(self) -> None:
        # Infra phases (docker gates / SAST / git) carry wall-clock ONLY — no tokens/cost — and feed the
        # real end-to-end TOTAL the FinOps summary now reports (it previously counted LLM time only).
        tel = PipelineTelemetry()
        tel.record("Developer Agent", 100, 20, Decimal("0.05"), provider="claude", duration_seconds=10.0)
        tel.record_phase("build", 1.5)
        tel.record_phase("qa+sast", 130.0)
        tel.record_phase("build", 0.5)  # a gate re-run coalesces into the same slot
        # LLM time is unchanged; infra is tracked separately and bumps the wall-clock total.
        self.assertAlmostEqual(tel.total_duration_seconds, 10.0)
        self.assertAlmostEqual(tel.total_infra_seconds, 132.0)   # 1.5 + 130.0 + 0.5
        self.assertAlmostEqual(tel.total_wall_seconds, 142.0)    # LLM + infra = real wall-clock
        self.assertEqual(tel.by_phase["build"].calls, 2)
        self.assertAlmostEqual(tel.by_phase["build"].duration_seconds, 2.0)
        self.assertEqual(tel.by_phase["qa+sast"].calls, 1)
        # Infra phases spend NO money/tokens — the breaker stays money-only, unaffected.
        self.assertEqual(tel.total_cost_usd, Decimal("0.05"))
        self.assertEqual(tel.total_tokens, 120)

    def test_finops_report_carries_infra_and_wall_and_by_phase(self) -> None:
        tel = PipelineTelemetry()
        tel.record("QA Agent", 50, 10, Decimal("0.01"), provider="gemini", duration_seconds=2.0)
        tel.record_phase("lint", 3.0)
        report = tel.finops_report(budget_usd=Decimal("1.00"))
        self.assertAlmostEqual(report["total_duration_seconds"], 2.0)
        self.assertAlmostEqual(report["total_infra_seconds"], 3.0)
        self.assertAlmostEqual(report["total_wall_seconds"], 5.0)
        self.assertEqual(report["by_phase"]["lint"]["calls"], 1)
        self.assertAlmostEqual(report["by_phase"]["lint"]["duration_seconds"], 3.0)

    def test_by_phase_survives_checkpoint_round_trip(self) -> None:
        ctx = GlobalPipelineContext(pr_description="x")
        ctx.telemetry.record_phase("qa+sast", 42.0)
        restored = GlobalPipelineContext.model_validate_json(ctx.model_dump_json())
        self.assertAlmostEqual(restored.telemetry.total_infra_seconds, 42.0)
        self.assertEqual(restored.telemetry.by_phase["qa+sast"].calls, 1)
        self.assertAlmostEqual(restored.telemetry.total_wall_seconds, 42.0)


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
            # A rejection must carry guidance (the payload-on-rejection validator); empty when approved.
            qa_diagnostic_payload="" if test_integrity_approved else "regenerate the suite",
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
        # E5 — application-wide accounting defaults.
        self.assertEqual(batch.app_telemetry.total_cost_usd, Decimal("0"))
        self.assertFalse(batch.nexus_merged)
        self.assertIsNone(batch.budget_marker)
        self.assertIsNone(batch.released_tag)            # E6 — no release cut yet

    def test_app_telemetry_and_markers_survive_round_trip(self) -> None:
        # E5 — the running application spend + resume markers must persist for --resume re-budgeting.
        with TemporaryDirectory() as td:
            path = Path(td) / "reports" / "batch_state.json"
            batch = BatchState(project_slug="p", nexus_run="001_nexus_plan",
                               tickets=["TASK-01", "TASK-02"], completed=["TASK-01"],
                               nexus_merged=True, budget_marker="App budget exhausted before 'TASK-02'.",
                               released_tag="v1.3.0")
            batch.app_telemetry.record("Developer Agent", 1000, 200, "0.42",
                                       provider="claude", plane="development", duration_seconds=5.0)
            batch.save_checkpoint(path)

            loaded = BatchState.load_checkpoint(path)
            self.assertTrue(loaded.nexus_merged)
            self.assertEqual(loaded.budget_marker, "App budget exhausted before 'TASK-02'.")
            self.assertEqual(loaded.released_tag, "v1.3.0")   # E6 — release marker survives --resume
            self.assertEqual(loaded.app_telemetry.total_cost_usd, Decimal("0.42"))
            self.assertAlmostEqual(loaded.app_telemetry.total_duration_seconds, 5.0)
            self.assertEqual(loaded.app_telemetry.by_plane()["development"]["calls"], 1)


class PipelineTelemetryMergeTests(unittest.TestCase):
    """E5 — merge() folds a run's telemetry into the application-wide accumulator (totals + per-agent)."""

    def test_merge_sums_totals_and_coalesces_agents(self) -> None:
        app = PipelineTelemetry()
        app.record("Developer Agent", 100, 20, "0.10", provider="claude", plane="development", duration_seconds=1.0)

        ticket = PipelineTelemetry()
        ticket.record("Developer Agent", 200, 40, "0.20", provider="claude", plane="development", duration_seconds=2.0)
        ticket.record("QA Agent", 50, 10, "0.01", provider="gemini", plane="development", duration_seconds=0.5)

        app.merge(ticket)
        # Totals sum across both telemetries.
        self.assertEqual(app.total_cost_usd, Decimal("0.31"))
        self.assertEqual(app.total_tokens, 100 + 20 + 200 + 40 + 50 + 10)
        self.assertAlmostEqual(app.total_duration_seconds, 3.5)
        # Same-named agent coalesces; a new agent is added.
        self.assertEqual(app.by_agent["Developer Agent"].calls, 2)
        self.assertEqual(app.by_agent["Developer Agent"].cost_usd, Decimal("0.30"))
        self.assertIn("QA Agent", app.by_agent)

    def test_merge_folds_infra_phases_and_wall(self) -> None:
        app = PipelineTelemetry()
        app.record_phase("build", 1.0)
        app.record_phase("qa+sast", 100.0)
        ticket = PipelineTelemetry()
        ticket.record_phase("build", 2.0)        # same phase coalesces across runs
        ticket.record_phase("git:clone", 5.0)    # a new phase is added
        app.merge(ticket)
        self.assertAlmostEqual(app.total_infra_seconds, 108.0)
        self.assertEqual(app.by_phase["build"].calls, 2)
        self.assertAlmostEqual(app.by_phase["build"].duration_seconds, 3.0)
        self.assertIn("git:clone", app.by_phase)
        self.assertAlmostEqual(app.total_wall_seconds, 108.0)  # no LLM time recorded here → wall == infra


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
