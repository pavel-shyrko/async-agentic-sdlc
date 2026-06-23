"""Unit tests for the Arbiter node + verdict model: it classifies a stuck cycle, stores the verdict on
the context, and records telemetry like every other Gemini agent."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("GEMINI_API_KEY", "test-key")

from pydantic import ValidationError

from src.development.agents import arbiter as arbiter_mod
from src.development.agents.arbiter import run_arbiter_node
from src.shared.core.models import (
    ArbiterVerdict, TechLeadContract, ReviewReport, GlobalPipelineContext, WorkspacePaths,
)


class ArbiterVerdictModelTests(unittest.TestCase):
    def test_rejects_unknown_route(self) -> None:
        with self.assertRaises(ValidationError):
            ArbiterVerdict(root_cause_class="contract_conflict", route="frobnicate", reasoning="x")

    def test_directive_defaults_empty(self) -> None:
        v = ArbiterVerdict(root_cause_class="production_bug", route="developer", reasoning="x")
        self.assertEqual(v.contract_amendment_directive, "")


class RunArbiterNodeTests(unittest.IsolatedAsyncioTestCase):
    def _ctx(self, base: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(logs_dir=base / "logs", reports_dir=base / "reports", repo_dir=base)
        ctx = GlobalPipelineContext(
            pr_description="p", workspace_paths=paths, test_code_snapshot="tests",
            production_code_snapshot={"src/x.py": "code"},
        )
        ctx.contract = TechLeadContract(
            files_to_modify=["src/x.py"], instruction="i", function_signatures="f",
            strict_type_validation_rules="s", techlead_reasoning="r", topology_contract=[],
            environment_id="python-3.12-core",
        )
        ctx.review_report = ReviewReport(
            code_quality_analysis="conflict", test_integrity_analysis="ok",
            log_verification_analysis="loop", code_quality_approved=False, test_integrity_approved=True,
            dev_diagnostic_payload="fix", qa_diagnostic_payload="",
        )
        return ctx

    async def test_stores_verdict_and_records_telemetry(self) -> None:
        with TemporaryDirectory() as td:
            ctx = self._ctx(Path(td))
            verdict = ArbiterVerdict(
                root_cause_class="contract_conflict", route="contract",
                reasoning="overlapping raises, no precedence",
                contract_amendment_directive="declare error precedence",
            )
            raw = SimpleNamespace(usage_metadata=None)

            async def _fake_llm(role, model, messages):
                self.assertEqual(role, "arbiter")
                return verdict, raw

            with (
                mock.patch.object(arbiter_mod, "run_structured_llm", new=_fake_llm),
                mock.patch.object(arbiter_mod, "log_token_usage") as log_usage,
                mock.patch.object(arbiter_mod, "build_agent_context", new=mock.AsyncMock(return_value="")),
            ):
                await run_arbiter_node(ctx, gate_output="boom", prev_dev_trace="prior fix")

            self.assertIs(ctx.arbiter_verdict, verdict)
            log_usage.assert_called_once()
            # telemetry recorded under the canonical agent label
            self.assertEqual(log_usage.call_args.args[1], "Arbiter Agent")


if __name__ == "__main__":
    unittest.main()
