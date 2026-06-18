"""Unit tests for checkpoint/resume orchestration flow."""
import os
import sys
import json
import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import AsyncMock

# orchestrator imports src.shared.core.config at module import time.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.executor import runner as orchestrator
from src.shared.core.models import TechLeadContract, GlobalPipelineContext, ReviewReport, WorkspacePaths


class ParseArgsResumeTests(unittest.TestCase):
    """CLI parser must accept --resume without requiring repo/ticket/description input."""

    def test_resume_does_not_require_repo_or_description(self) -> None:
        # Arrange
        argv = ["orchestrator.py", "--resume", "runs/run_abc/reports/checkpoint.json"]
        # Act
        with mock.patch.object(sys, "argv", argv):
            cfg = orchestrator.parse_args()
        # Assert
        self.assertIsNone(cfg.description)
        self.assertEqual(cfg.base_branch, "main")
        self.assertEqual(cfg.resume, Path("runs/run_abc/reports/checkpoint.json"))
        self.assertFalse(cfg.reset_attempts)

    def test_reset_attempts_flag_is_propagated(self) -> None:
        # Arrange
        argv = ["orchestrator.py", "--resume", "cp.json", "--reset-attempts"]
        # Act
        with mock.patch.object(sys, "argv", argv):
            cfg = orchestrator.parse_args()
        # Assert
        self.assertTrue(cfg.reset_attempts)


class ParseArgsFreshRunTests(unittest.TestCase):
    """Fresh runs require --repo/--ticket and resolve the task description deterministically."""

    def test_missing_repo_and_ticket_errors(self) -> None:
        # Arrange — a bare task with no repo/ticket cannot bootstrap a git-anchored session.
        argv = ["orchestrator.py", "do a thing"]
        # Act / Assert — argparse aborts with exit code 2.
        with mock.patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit) as exit_ctx:
                orchestrator.parse_args()
        self.assertEqual(exit_ctx.exception.code, 2)

    def test_ticket_is_used_as_description_fallback(self) -> None:
        # Arrange — no inline/-f description supplied.
        argv = ["orchestrator.py", "--repo", "git@host:proj.git", "--ticket", "DEMO-1"]
        # Act
        with mock.patch.object(sys, "argv", argv):
            cfg = orchestrator.parse_args()
        # Assert
        self.assertEqual(cfg.repo, "git@host:proj.git")
        self.assertEqual(cfg.ticket, "DEMO-1")
        self.assertEqual(cfg.description, "DEMO-1")
        self.assertIsNone(cfg.resume)

    def test_inline_description_overrides_ticket_fallback(self) -> None:
        # Arrange
        argv = ["orchestrator.py", "build the X", "--repo", "r", "--ticket", "T-9"]
        # Act
        with mock.patch.object(sys, "argv", argv):
            cfg = orchestrator.parse_args()
        # Assert
        self.assertEqual(cfg.description, "build the X")

    def test_push_flag_defaults_false_and_opts_in(self) -> None:
        # Arrange / Act — default off.
        with mock.patch.object(sys, "argv", ["orchestrator.py", "--repo", "r", "--ticket", "T"]):
            self.assertFalse(orchestrator.parse_args().push)
        # Act — explicit opt-in.
        with mock.patch.object(sys, "argv", ["orchestrator.py", "--repo", "r", "--ticket", "T", "--push"]):
            self.assertTrue(orchestrator.parse_args().push)


class ParseArgsProjectVerbsTests(unittest.TestCase):
    """The project-umbrella CLI: --idea (new project), --run <project> -f <ticket>, and
    --resume <project> [N] vs --resume <path>."""

    def _parse(self, *argv):
        with mock.patch.object(sys, "argv", ["orchestrator.py", *argv]):
            return orchestrator.parse_args()

    def test_idea_optionally_captures_repo(self) -> None:
        cfg = self._parse("--idea", "json to csv", "--repo", "git@h:r.git")
        self.assertEqual(cfg.idea, "json to csv")
        self.assertEqual(cfg.repo, "git@h:r.git")

    def test_run_project_requires_ticket(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            self._parse("--run", "my-proj")            # missing -f
        self.assertEqual(ctx.exception.code, 2)

    def test_run_project_maps_ticket_from_dash_f(self) -> None:
        cfg = self._parse("--run", "my-proj", "-f", "TASK-01")
        self.assertEqual((cfg.run_project, cfg.ticket), ("my-proj", "TASK-01"))
        self.assertIsNone(cfg.resume)

    def test_resume_project_without_number(self) -> None:
        cfg = self._parse("--resume", "my-proj")
        self.assertEqual(cfg.resume_project, "my-proj")
        self.assertIsNone(cfg.resume_number)
        self.assertIsNone(cfg.resume)                  # not a path

    def test_resume_project_with_number(self) -> None:
        cfg = self._parse("--resume", "my-proj", "002")
        self.assertEqual((cfg.resume_project, cfg.resume_number), ("my-proj", "002"))

    def test_resume_path_form_still_works(self) -> None:
        cfg = self._parse("--resume", "runs/x/reports/checkpoint.json")
        self.assertEqual(cfg.resume, Path("runs/x/reports/checkpoint.json"))
        self.assertIsNone(cfg.resume_project)


class MainResumeSkipFlowTests(unittest.IsolatedAsyncioTestCase):
    """Resume flow must bypass completed FSM nodes and still checkpoint each cycle."""

    async def test_resume_skips_techlead_and_initial_qa_generation(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                logs_dir=base / "logs",
                reports_dir=base / "reports",
                repo_dir=base,
            )
            ctx = GlobalPipelineContext(
                pr_description="resume run",
                workspace_paths=paths,
                test_code_snapshot="existing tests",
            )
            ctx.contract = TechLeadContract(
                files_to_modify=["src/core/models.py"],
                instruction="noop",
                function_signatures="noop",
                strict_type_validation_rules="noop",
                techlead_reasoning="noop",
                topology_contract=[],
                environment_id="python-3.12-core",
            )

            async def _set_approved_review(*_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock) as techlead,
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_set_approved_review)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
                mock.patch.object(GlobalPipelineContext, "save_checkpoint", autospec=True) as save_checkpoint,
            ):
                # Act
                await orchestrator.main()

            # Assert
            techlead.assert_not_called()
            qa.assert_not_called()
            developer.assert_awaited_once()
            save_checkpoint.assert_called_once_with(ctx, ctx.workspace_paths.reports_dir / "checkpoint.json")

    async def test_invalid_resume_checkpoint_exits_with_code_1(self) -> None:
        # Arrange / Act / Assert
        with (
            mock.patch.object(orchestrator, "check_environment"),
            mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                description=None, base_branch="main", resume=Path("bad.json"), reset_attempts=False)),
            mock.patch.object(GlobalPipelineContext, "load_checkpoint", side_effect=ValueError("invalid")),
        ):
            with self.assertRaises(SystemExit) as exit_ctx:
                await orchestrator.main()

        self.assertEqual(exit_ctx.exception.code, 1)


class MainCheckpointWritePointsTests(unittest.IsolatedAsyncioTestCase):
    """Checkpoint must be persisted at required orchestration milestones."""

    async def test_fresh_run_saves_after_techlead_after_qa_and_end_of_cycle(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                logs_dir=base / "logs",
                reports_dir=base / "reports",
                repo_dir=base,
            )

            async def _set_approved_review(ctx: GlobalPipelineContext, *_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "RUNS_BASE", base),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description="fresh run", base_branch="main", resume=None, reset_attempts=False,
                    repo="dummy-repo", ticket="DEMO-1")),
                mock.patch.object(orchestrator, "bootstrap_session", new=AsyncMock(return_value=paths)),
                mock.patch.object(GlobalPipelineContext, "save_checkpoint", autospec=True) as save_checkpoint,
                mock.patch.object(orchestrator, "run_techlead_node", new=AsyncMock(side_effect=lambda c: setattr(c, "contract", TechLeadContract(
                    files_to_modify=["src/core/models.py"],
                    instruction="noop",
                    function_signatures="noop",
                    strict_type_validation_rules="noop",
                    techlead_reasoning="noop",
                    topology_contract=[],
                    environment_id="python-3.12-core",
                )))),
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "tests"))),
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_set_approved_review)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "GlobalPipelineContext", wraps=GlobalPipelineContext) as wrapped_ctx_cls,
            ):
                # Ensure freshly created context uses isolated reports dir for deterministic assertion.
                wrapped_ctx_cls.return_value = GlobalPipelineContext(pr_description="fresh run", base_branch="main", workspace_paths=paths)

                # Act
                await orchestrator.main()

            # Assert
            checkpoint_path = paths.reports_dir / "checkpoint.json"
            self.assertEqual(save_checkpoint.call_count, 3)
            expected_calls = [
                mock.call(wrapped_ctx_cls.return_value, checkpoint_path),
                mock.call(wrapped_ctx_cls.return_value, checkpoint_path),
                mock.call(wrapped_ctx_cls.return_value, checkpoint_path),
            ]
            self.assertEqual(save_checkpoint.call_args_list, expected_calls)

    async def test_resume_without_tests_runs_qa_and_saves_twice_in_success_cycle(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                logs_dir=base / "logs",
                reports_dir=base / "reports",
                repo_dir=base,
            )
            ctx = GlobalPipelineContext(pr_description="resume run", workspace_paths=paths)
            ctx.contract = TechLeadContract(
                files_to_modify=["src/core/models.py"],
                instruction="noop",
                function_signatures="noop",
                strict_type_validation_rules="noop",
                techlead_reasoning="noop",
                topology_contract=[],
                environment_id="python-3.12-core",
            )

            async def _set_approved_review(*_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock) as techlead,
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "new tests"))) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_set_approved_review)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
                mock.patch.object(GlobalPipelineContext, "save_checkpoint", autospec=True) as save_checkpoint,
            ):
                # Act
                await orchestrator.main()

            # Assert
            techlead.assert_not_called()
            qa.assert_awaited_once()
            checkpoint_path = ctx.workspace_paths.reports_dir / "checkpoint.json"
            self.assertEqual(save_checkpoint.call_count, 2)
            self.assertEqual(save_checkpoint.call_args_list, [
                mock.call(ctx, checkpoint_path),
                mock.call(ctx, checkpoint_path),
            ])

    async def test_failing_first_cycle_and_passing_second_still_saves_each_cycle_end(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                logs_dir=base / "logs",
                reports_dir=base / "reports",
                repo_dir=base,
            )

            review_calls = {"count": 0}

            async def _review_reject_then_approve(ctx: GlobalPipelineContext, *_args, **_kwargs) -> None:
                review_calls["count"] += 1
                if review_calls["count"] == 1:
                    ctx.review_report = ReviewReport(
                        code_quality_analysis="needs fix",
                        test_integrity_analysis="ok",
                        log_verification_analysis="qa failed",
                        code_quality_approved=False,
                        test_integrity_approved=True,
                        dev_diagnostic_payload="fix implementation",
                    )
                    return
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="all green",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "RUNS_BASE", base),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description="fresh run", base_branch="main", resume=None, reset_attempts=False,
                    repo="dummy-repo", ticket="DEMO-1")),
                mock.patch.object(orchestrator, "bootstrap_session", new=AsyncMock(return_value=paths)),
                mock.patch.object(GlobalPipelineContext, "save_checkpoint", autospec=True) as save_checkpoint,
                mock.patch.object(orchestrator, "run_techlead_node", new=AsyncMock(side_effect=lambda c: setattr(c, "contract", TechLeadContract(
                    files_to_modify=["src/core/models.py"],
                    instruction="noop",
                    function_signatures="noop",
                    strict_type_validation_rules="noop",
                    techlead_reasoning="noop",
                    topology_contract=[],
                    environment_id="python-3.12-core",
                )))),
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "tests"))) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_review_reject_then_approve)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(side_effect=[(False, ["fail"]), (True, [])])),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "GlobalPipelineContext", wraps=GlobalPipelineContext) as wrapped_ctx_cls,
            ):
                # Ensure freshly created context uses isolated reports dir for deterministic assertion.
                wrapped_ctx_cls.return_value = GlobalPipelineContext(pr_description="fresh run", base_branch="main", workspace_paths=paths)

                # Act
                await orchestrator.main()

            # Assert
            checkpoint_path = paths.reports_dir / "checkpoint.json"
            self.assertEqual(developer.await_count, 2)
            self.assertEqual(qa.await_count, 1)
            self.assertEqual(save_checkpoint.call_count, 4)
            self.assertEqual(save_checkpoint.call_args_list, [
                mock.call(wrapped_ctx_cls.return_value, checkpoint_path),
                mock.call(wrapped_ctx_cls.return_value, checkpoint_path),
                mock.call(wrapped_ctx_cls.return_value, checkpoint_path),
                mock.call(wrapped_ctx_cls.return_value, checkpoint_path),
            ])


class ResumeFsmRecoveryTests(unittest.IsolatedAsyncioTestCase):
    """Resume must rebuild ephemeral FSM flags from the persisted review/attempt state."""

    async def test_resume_with_rejected_tests_regenerates_qa(self) -> None:
        # Arrange â€” checkpoint reflects a prior cycle where the Reviewer rejected the
        # test suite, so QA must regenerate even though test_code_snapshot is non-empty.
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                logs_dir=base / "logs",
                reports_dir=base / "reports",
                repo_dir=base,
            )
            ctx = GlobalPipelineContext(
                pr_description="resume after rejection",
                workspace_paths=paths,
                test_code_snapshot="stale test suite",
                current_attempt=2,
            )
            ctx.contract = TechLeadContract(
                files_to_modify=["src/core/models.py"],
                instruction="noop",
                function_signatures="noop",
                strict_type_validation_rules="noop",
                techlead_reasoning="noop",
                topology_contract=[],
                environment_id="python-3.12-core",
            )
            ctx.review_report = ReviewReport(
                code_quality_analysis="ok",
                test_integrity_analysis="loophole detected",
                log_verification_analysis="ok",
                code_quality_approved=True,
                test_integrity_approved=False,
                qa_diagnostic_payload="rewrite tests",
            )

            async def _approve(*_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock) as techlead,
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "fresh tests"))) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
            ):
                # Act
                await orchestrator.main()

            # Assert
            techlead.assert_not_called()
            qa.assert_awaited_once()
            self.assertEqual(ctx.test_code_snapshot, "fresh tests")

    async def test_resume_starts_from_persisted_attempt_counter(self) -> None:
        # Arrange â€” a checkpoint persisted at end of cycle 2 (counter pre-incremented to 3)
        # must yield a single remaining cycle so the original retry budget is preserved.
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                logs_dir=base / "logs",
                reports_dir=base / "reports",
                repo_dir=base,
            )
            ctx = GlobalPipelineContext(
                pr_description="resume late",
                workspace_paths=paths,
                test_code_snapshot="approved tests",
                current_attempt=3,
            )
            ctx.contract = TechLeadContract(
                files_to_modify=["src/core/models.py"],
                instruction="noop",
                function_signatures="noop",
                strict_type_validation_rules="noop",
                techlead_reasoning="noop",
                topology_contract=[],
                environment_id="python-3.12-core",
            )
            ctx.review_report = ReviewReport(
                code_quality_analysis="needs fix",
                test_integrity_analysis="ok",
                log_verification_analysis="ok",
                code_quality_approved=False,
                test_integrity_approved=True,
                dev_diagnostic_payload="fix prod",
            )

            async def _approve(*_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
            ):
                # Act
                await orchestrator.main()

            # Assert
            qa.assert_not_called()
            self.assertEqual(developer.await_count, 1)
            self.assertEqual(ctx.current_attempt, 4)

    async def test_resume_with_exhausted_attempts_triggers_circuit_breaker(self) -> None:
        # Arrange â€” counter past the retry budget must short-circuit straight to the
        # circuit breaker without invoking any agent.
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                logs_dir=base / "logs",
                reports_dir=base / "reports",
                repo_dir=base,
            )
            ctx = GlobalPipelineContext(
                pr_description="resume exhausted",
                workspace_paths=paths,
                test_code_snapshot="tests",
                current_attempt=4,
            )
            ctx.contract = TechLeadContract(
                files_to_modify=["src/core/models.py"],
                instruction="noop",
                function_signatures="noop",
                strict_type_validation_rules="noop",
                techlead_reasoning="noop",
                topology_contract=[],
                environment_id="python-3.12-core",
            )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock) as techlead,
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new_callable=AsyncMock) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
            ):
                with self.assertRaises(SystemExit) as exit_ctx:
                    await orchestrator.main()

            # Assert
            self.assertEqual(exit_ctx.exception.code, 1)
            techlead.assert_not_called()
            qa.assert_not_called()
            developer.assert_not_called()
            reviewer.assert_not_called()

    async def test_reset_attempts_flag_restores_full_retry_budget(self) -> None:
        # Arrange — checkpoint is past the retry budget AND has rejected tests, so
        # the only way QA gets a fresh attempt is via --reset-attempts.
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                logs_dir=base / "logs",
                reports_dir=base / "reports",
                repo_dir=base,
            )
            ctx = GlobalPipelineContext(
                pr_description="resume with reset",
                workspace_paths=paths,
                test_code_snapshot="stale tests",
                current_attempt=4,
            )
            ctx.contract = TechLeadContract(
                files_to_modify=["src/core/models.py"],
                instruction="noop",
                function_signatures="noop",
                strict_type_validation_rules="noop",
                techlead_reasoning="noop",
                topology_contract=[],
                environment_id="python-3.12-core",
            )
            ctx.review_report = ReviewReport(
                code_quality_analysis="ok",
                test_integrity_analysis="brittle assertions",
                log_verification_analysis="ok",
                code_quality_approved=True,
                test_integrity_approved=False,
                qa_diagnostic_payload="rewrite tests without string matching",
            )

            async def _approve(*_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=True)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock) as techlead,
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "fresh tests"))) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
            ):
                # Act
                await orchestrator.main()

            # Assert
            techlead.assert_not_called()
            qa.assert_awaited_once()
            # Tests rejected / production code approved → DAG bypass skips the Developer entirely
            # (single cycle, so the mock has no prior history to confuse assert_not_called).
            developer.assert_not_called()
            # After the single successful cycle the persisted counter advances from 1 to 2.
            self.assertEqual(ctx.current_attempt, 2)


class DeadlockGuardTests(unittest.IsolatedAsyncioTestCase):
    """A hard gate FAILED + Reviewer approving BOTH sides is unfixable & unprogressable — the run
    must fail fast on the FIRST cycle, not loop to the circuit breaker (BACKLOG #16)."""

    async def test_gate_fail_with_both_approved_aborts_on_first_cycle(self) -> None:
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                logs_dir=base / "logs", reports_dir=base / "reports", repo_dir=base,
            )
            ctx = GlobalPipelineContext(
                pr_description="resume", workspace_paths=paths, test_code_snapshot="tests",
            )
            ctx.contract = TechLeadContract(
                files_to_modify=["src/converter.py"], instruction="noop", function_signatures="noop",
                strict_type_validation_rules="noop", techlead_reasoning="noop",
                topology_contract=[], environment_id="python-3.12-core",
            )

            async def _approve_both(*_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok", test_integrity_analysis="ok",
                    log_verification_analysis="runner sys.path issue, not a code defect",
                    code_quality_approved=True, test_integrity_approved=True,
                    dev_diagnostic_payload="", qa_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve_both)) as reviewer,
                # Hard gate FAILS on an unfixable import error; SAST passes.
                mock.patch.object(orchestrator, "run_qa_unit_tests",
                                  new=AsyncMock(return_value=(False, ["E   ModuleNotFoundError: No module named 'src'"]))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock) as finalize,
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
            ):
                with self.assertRaises(SystemExit) as exit_ctx:
                    await orchestrator.main()

            self.assertEqual(exit_ctx.exception.code, 1)
            # Fail-fast: aborted DURING cycle 1 — the Developer/Reviewer each ran exactly once, never looped.
            developer.assert_awaited_once()
            reviewer.assert_awaited_once()
            finalize.assert_not_called()
            # Incident report written by the fast-fail abort.
            self.assertTrue((paths.reports_dir / "incident_report.json").exists())


class BootstrapSessionTests(unittest.IsolatedAsyncioTestCase):
    """Session bootstrap must shallow-clone, branch, map paths, and re-anchor logging."""

    async def test_shallow_clone_branch_and_workspace_mapping(self) -> None:
        # Arrange — the caller owns run_dir (logging is re-anchored by main(), not bootstrap).
        with TemporaryDirectory() as td:
            cfg = orchestrator.RunConfig(
                description="d", base_branch="main", resume=None, reset_attempts=False,
                repo="some-repo", ticket="DEMO-1",            )
            run_dir = Path(td) / "run_test"
            proc = mock.MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            with mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)) as exec_mock:
                # Act
                paths = await orchestrator.bootstrap_session(cfg, run_dir)

            # Assert — three git subprocesses: shallow clone, feature-branch checkout, base-branch fetch.
            self.assertEqual(exec_mock.call_count, 3)
            clone_args = exec_mock.call_args_list[0].args
            self.assertEqual(clone_args[:5], ("git", "clone", "--depth", "1", "some-repo"))
            # Interactive credential prompts are disabled so a private repo fails fast, never hangs.
            self.assertEqual(exec_mock.call_args_list[0].kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            checkout_args = exec_mock.call_args_list[1].args
            self.assertIn("checkout", checkout_args)
            self.assertIn("-b", checkout_args)
            self.assertIn("feat/ticket-DEMO-1", checkout_args)
            # The base branch is force-fetched into a LOCAL ref (refspec) AFTER checkout so the snapshot diff resolves it.
            fetch_args = exec_mock.call_args_list[2].args
            self.assertIn("fetch", fetch_args)
            self.assertIn("main:main", fetch_args)
            # Assert — workspace anchored under the caller's run_dir; meta-state (logs/reports) outside the clone.
            self.assertEqual(paths.repo_dir.name, "repo")
            self.assertEqual(paths.logs_dir, (run_dir / "logs").resolve())
            self.assertEqual(paths.reports_dir, (run_dir / "reports").resolve())

    async def test_clone_failure_aborts_with_exit_1(self) -> None:
        # Arrange — git clone returns non-zero; the run must abort and surface the child's stderr.
        with TemporaryDirectory() as td:
            cfg = orchestrator.RunConfig(
                description="d", base_branch="main", resume=None, reset_attempts=False,
                repo="bad-repo", ticket="T",            )
            proc = mock.MagicMock()
            proc.returncode = 128
            proc.communicate = AsyncMock(return_value=(b"", b"fatal: repository not found"))
            with (
                mock.patch.object(orchestrator, "RUNS_BASE", Path(td)),
                mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "log") as mock_log,
            ):
                # Act / Assert
                with self.assertRaises(SystemExit) as exit_ctx:
                    await orchestrator.bootstrap_session(cfg, Path(td) / "run_test")
            self.assertEqual(exit_ctx.exception.code, 1)
            # The child's stderr must reach the operator's error log (requirement #3).
            logged = " ".join(str(c) for c in mock_log.error.call_args_list)
            self.assertIn("repository not found", logged)

    async def test_clone_timeout_kills_process_and_exits_1(self) -> None:
        # Arrange — the network clone exceeds its timeout; the child must be killed AND reaped
        # (kill alone would leave a <defunct> zombie in the OS process table).
        with TemporaryDirectory() as td:
            cfg = orchestrator.RunConfig(
                description="d", base_branch="main", resume=None, reset_attempts=False,
                repo="slow-repo", ticket="T",            )
            proc = mock.MagicMock()
            proc.kill = mock.MagicMock()
            proc.wait = AsyncMock()
            # Plain (non-coroutine) return so the patched wait_for leaves no un-awaited coroutine.
            proc.communicate = mock.MagicMock(return_value=None)
            with (
                mock.patch.object(orchestrator, "RUNS_BASE", Path(td)),
                mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
                mock.patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)),
                mock.patch.object(orchestrator, "reconfigure_logging"),
            ):
                # Act / Assert
                with self.assertRaises(SystemExit) as exit_ctx:
                    await orchestrator.bootstrap_session(cfg, Path(td) / "run_test")
            self.assertEqual(exit_ctx.exception.code, 1)
            proc.kill.assert_called_once()
            proc.wait.assert_awaited_once()


class HasStagedChangesTests(unittest.IsolatedAsyncioTestCase):
    """The empty-commit guard maps `git diff --cached --quiet` exit codes correctly."""

    async def _run(self, returncode: int, stderr: bytes = b"") -> bool:
        proc = mock.MagicMock()
        proc.returncode = returncode
        proc.communicate = AsyncMock(return_value=(b"", stderr))
        with mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            return await orchestrator._has_staged_changes("/repo")

    async def test_exit_zero_means_index_clean(self) -> None:
        self.assertFalse(await self._run(0))

    async def test_exit_one_means_staged_changes(self) -> None:
        self.assertTrue(await self._run(1))

    async def test_unexpected_exit_aborts(self) -> None:
        with self.assertRaises(SystemExit):
            await self._run(128, b"fatal: not a git repo")


class QaTestCompileGateTests(unittest.IsolatedAsyncioTestCase):
    """The pre-Reviewer QA test-compile gate fast-fail-reroutes a TEST-ONLY compile failure to QA
    (regenerating the suite) without invoking the Reviewer, then proceeds once it compiles."""

    def _ctx(self, base: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(logs_dir=base / "logs", reports_dir=base / "reports", repo_dir=base)
        ctx = GlobalPipelineContext(pr_description="gate run", workspace_paths=paths,
                                    test_code_snapshot="tests")  # top-of-cycle QA skipped
        ctx.contract = TechLeadContract(
            files_to_modify=["src/core/models.py"], instruction="noop", function_signatures="noop",
            strict_type_validation_rules="noop", techlead_reasoning="noop", topology_contract=[],
            environment_id="python-3.12-core",
        )
        return ctx

    async def test_test_only_compile_failure_reroutes_to_qa_then_proceeds(self) -> None:
        with TemporaryDirectory() as td:
            ctx = self._ctx(Path(td))

            async def _set_approved_review(*_a, **_k) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok", test_integrity_analysis="ok", log_verification_analysis="ok",
                    code_quality_approved=True, test_integrity_approved=True, dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock),
                # First call: test-only compile failure; second call (after QA regen): clean.
                mock.patch.object(orchestrator, "run_test_compile_gate",
                                  new=AsyncMock(side_effect=[(False, ["m_test.py:2: unused import"]), (True, [])])) as gate,
                mock.patch.object(orchestrator, "build_failure_is_test_only", return_value=True),
                mock.patch.object(orchestrator, "build_failure_is_environmental", return_value=False),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_set_approved_review)) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
                mock.patch.object(GlobalPipelineContext, "save_checkpoint", autospec=True),
            ):
                await orchestrator.main()

            # The gate ran twice (fail → regen → pass); QA regenerated exactly once on the rebound;
            # the Reviewer ran only AFTER the tests compiled (not on the bounced attempt).
            self.assertEqual(gate.await_count, 2)
            qa.assert_awaited_once()
            reviewer.assert_awaited_once()
            # Rebound feedback is consumed, not leaked into the Reviewer's channels.
            self.assertEqual(ctx.qa_error_trace, "")


class FinalizeTransactionTests(unittest.IsolatedAsyncioTestCase):
    """The success transaction commits the staged delta atomically (and optionally pushes)."""

    def _ctx(self, base: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            logs_dir=base / "logs", reports_dir=base / "reports", repo_dir=base,
        )
        return GlobalPipelineContext(
            pr_description="add two ints", base_branch="main",
            ticket="DEMO-1", workspace_paths=paths,
        )

    async def test_commits_when_index_has_staged_changes(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            ctx = self._ctx(Path(td))
            proc = mock.MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            with (
                mock.patch.object(orchestrator, "get_git_root", new=AsyncMock(return_value="/repo")),
                mock.patch.object(orchestrator, "_has_staged_changes", new=AsyncMock(return_value=True)),
                mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)) as exec_mock,
            ):
                # Act
                await orchestrator.finalize_transaction(ctx, push=False)
            # Assert — a single commit carrying the conventional subject; no push.
            self.assertEqual(exec_mock.call_count, 1)
            commit_cmd = exec_mock.call_args_list[0].args
            self.assertIn("commit", commit_cmd)
            self.assertIn("feat(DEMO-1): add two ints", commit_cmd)
            # Identity is pinned dynamically from the ticket.
            self.assertIn("user.name=AI Agent (DEMO-1)", commit_cmd)
            self.assertIn("user.email=agent-demo-1@sdlc-factory.local", commit_cmd)

    async def test_markdown_heading_description_yields_clean_subject(self) -> None:
        # Arrange — pr_description leads with a markdown heading (the common ticket shape). The
        # subject must strip the leading `#` and must NOT leak any [CURRENT TASK …] template header
        # (that scaffolding now lives in techlead_brief, never pr_description).
        with TemporaryDirectory() as td:
            ctx = self._ctx(Path(td))
            ctx.pr_description = "# Repository initialization and core converter logic\n\nbody"
            ctx.techlead_brief = "[CURRENT TASK — the authoritative scope of this contract]\n# X"
            proc = mock.MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            with (
                mock.patch.object(orchestrator, "get_git_root", new=AsyncMock(return_value="/repo")),
                mock.patch.object(orchestrator, "_has_staged_changes", new=AsyncMock(return_value=True)),
                mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)) as exec_mock,
            ):
                # Act
                await orchestrator.finalize_transaction(ctx, push=False)
            # Assert — clean conventional subject, no heading hash, no template placeholder.
            commit_cmd = exec_mock.call_args_list[0].args
            self.assertIn("feat(DEMO-1): Repository initialization and core converter logic", commit_cmd)
            self.assertNotIn("# Repository initialization and core converter logic", commit_cmd)
            joined = " ".join(str(a) for a in commit_cmd)
            self.assertNotIn("CURRENT TASK", joined)

    async def test_skips_commit_when_index_clean(self) -> None:
        # Arrange — empty-commit guard trips.
        with TemporaryDirectory() as td:
            ctx = self._ctx(Path(td))
            with (
                mock.patch.object(orchestrator, "get_git_root", new=AsyncMock(return_value="/repo")),
                mock.patch.object(orchestrator, "_has_staged_changes", new=AsyncMock(return_value=False)),
                mock.patch("asyncio.create_subprocess_exec", new=AsyncMock()) as exec_mock,
            ):
                # Act
                await orchestrator.finalize_transaction(ctx, push=False)
            # Assert — no commit subprocess at all.
            exec_mock.assert_not_called()

    async def test_push_issues_a_second_subprocess(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            ctx = self._ctx(Path(td))
            proc = mock.MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            with (
                mock.patch.object(orchestrator, "get_git_root", new=AsyncMock(return_value="/repo")),
                mock.patch.object(orchestrator, "_has_staged_changes", new=AsyncMock(return_value=True)),
                mock.patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)) as exec_mock,
            ):
                # Act
                await orchestrator.finalize_transaction(ctx, push=True)
            # Assert — commit then push.
            self.assertEqual(exec_mock.call_count, 2)
            commit_cmd = exec_mock.call_args_list[0].args
            self.assertIn("user.name=AI Agent (DEMO-1)", commit_cmd)
            self.assertIn("user.email=agent-demo-1@sdlc-factory.local", commit_cmd)
            self.assertIn("push", exec_mock.call_args_list[1].args)


class TopBlockCommentScannerTests(unittest.TestCase):
    """_top_block_has_comment: lexical top-of-file scan with safe-skip (None) semantics."""

    @staticmethod
    def _write(td: str, name: str, content: str) -> Path:
        p = Path(td) / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_hash_comment_on_first_line_is_detected(self) -> None:
        with TemporaryDirectory() as td:
            p = self._write(td, "a.py", "# justification\ndef f():\n    return 1\n")
            self.assertIs(orchestrator._top_block_has_comment(p), True)

    def test_comment_within_window_is_detected(self) -> None:
        with TemporaryDirectory() as td:
            body = "\n".join(["x = 1"] * 9 + ["# late but within 15"])
            p = self._write(td, "a.py", body + "\n")
            self.assertIs(orchestrator._top_block_has_comment(p), True)

    def test_code_only_returns_false(self) -> None:
        with TemporaryDirectory() as td:
            p = self._write(td, "a.py", "def f():\n    return 1\n")
            self.assertIs(orchestrator._top_block_has_comment(p), False)

    def test_comment_beyond_window_is_not_detected(self) -> None:
        # A comment on line 16 is outside the 15-line top block → not credited.
        with TemporaryDirectory() as td:
            body = "\n".join(["x = 1"] * 15 + ["# too late"])
            p = self._write(td, "a.py", body + "\n")
            self.assertIs(orchestrator._top_block_has_comment(p), False)

    def test_empty_file_is_ignored(self) -> None:
        with TemporaryDirectory() as td:
            self.assertIsNone(orchestrator._top_block_has_comment(self._write(td, "a.py", "")))

    def test_whitespace_only_file_is_ignored(self) -> None:
        with TemporaryDirectory() as td:
            self.assertIsNone(orchestrator._top_block_has_comment(self._write(td, "a.py", "   \n\n\t\n")))

    def test_binary_file_is_ignored(self) -> None:
        with TemporaryDirectory() as td:
            p = Path(td) / "blob.bin"
            p.write_bytes(b"\x00\x01\x02\xff\xfe# not really text\x00")
            self.assertIsNone(orchestrator._top_block_has_comment(p))

    def test_missing_file_is_ignored(self) -> None:
        with TemporaryDirectory() as td:
            self.assertIsNone(orchestrator._top_block_has_comment(Path(td) / "nope.py"))

    def test_language_agnostic_prefixes_are_detected(self) -> None:
        for lead in ("// c-style", "/* block", "* continuation", '"""docstring', "'''docstring", "<!-- xml/csproj"):
            with TemporaryDirectory() as td:
                p = self._write(td, "a.txt", lead + "\nbody\n")
                self.assertIs(orchestrator._top_block_has_comment(p), True, lead)


class EnforceDocumentationGuardrailTests(unittest.IsolatedAsyncioTestCase):
    """The fast-fail middleware flags only undocumented, newly-created, uncontracted files."""

    @staticmethod
    def _ctx(repo: Path, files_to_modify: list[str], snapshot_keys: list[str]) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            logs_dir=repo / "logs", reports_dir=repo / "reports", repo_dir=repo,
        )
        # The source dir is no longer pre-created by WorkspacePaths (layout is contract-driven); the
        # real Developer CLI mkdir's as it writes, so these tests create the tree they write into.
        (repo / "src").mkdir(parents=True, exist_ok=True)
        ctx = GlobalPipelineContext(pr_description="t", base_branch="main", workspace_paths=paths)
        ctx.contract = TechLeadContract(
            files_to_modify=files_to_modify, instruction="i", function_signatures="s",
            strict_type_validation_rules="r", techlead_reasoning="why",
            environment_id="python-3.12-core",
            topology_contract=[{"file_path": f, "exports": [], "depends_on": []} for f in files_to_modify],
        )
        ctx.production_code_snapshot = {k: "" for k in snapshot_keys}
        return ctx

    async def test_empty_snapshot_is_noop_without_git(self) -> None:
        with TemporaryDirectory() as td:
            ctx = self._ctx(Path(td), ["src/main.py"], [])
            with mock.patch.object(orchestrator, "get_pipeline_snapshot_files", new_callable=AsyncMock) as git:
                self.assertIsNone(await orchestrator.enforce_documentation_guardrail(ctx))
            git.assert_not_awaited()

    async def test_all_contracted_is_noop_without_git(self) -> None:
        with TemporaryDirectory() as td:
            ctx = self._ctx(Path(td), ["src/main.py"], ["src/main.py"])
            with mock.patch.object(orchestrator, "get_pipeline_snapshot_files", new_callable=AsyncMock) as git:
                self.assertIsNone(await orchestrator.enforce_documentation_guardrail(ctx))
            git.assert_not_awaited()

    async def test_uncontracted_new_file_without_comment_is_flagged(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo, ["src/main.py"], ["src/helper.py"])
            (repo / "src" / "helper.py").write_text("def x():\n    return 1\n", encoding="utf-8")
            with mock.patch.object(orchestrator, "get_pipeline_snapshot_files",
                                   new=AsyncMock(return_value=["src/helper.py"])):
                msg = await orchestrator.enforce_documentation_guardrail(ctx)
            self.assertIsNotNone(msg)
            self.assertIn("src/helper.py", msg)
            self.assertIn("SYSTEM GUARDRAIL", msg)

    async def test_uncontracted_new_file_with_comment_passes(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo, ["src/main.py"], ["src/helper.py"])
            (repo / "src" / "helper.py").write_text("# shared math util\ndef x():\n    return 1\n", encoding="utf-8")
            with mock.patch.object(orchestrator, "get_pipeline_snapshot_files",
                                   new=AsyncMock(return_value=["src/helper.py"])):
                self.assertIsNone(await orchestrator.enforce_documentation_guardrail(ctx))

    async def test_modified_preexisting_file_is_not_flagged(self) -> None:
        # Uncontracted but NOT in the git-added set → an edit, not a creation → out of scope (new-only).
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo, ["src/main.py"], ["src/legacy.py"])
            (repo / "src" / "legacy.py").write_text("def x():\n    return 1\n", encoding="utf-8")
            with mock.patch.object(orchestrator, "get_pipeline_snapshot_files",
                                   new=AsyncMock(return_value=[])):  # nothing newly added
                self.assertIsNone(await orchestrator.enforce_documentation_guardrail(ctx))

    async def test_multiple_offenders_are_all_named(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo, ["src/main.py"], ["src/a.py", "src/b.py"])
            (repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
            (repo / "src" / "b.py").write_text("y = 2\n", encoding="utf-8")
            with mock.patch.object(orchestrator, "get_pipeline_snapshot_files",
                                   new=AsyncMock(return_value=["src/a.py", "src/b.py"])):
                msg = await orchestrator.enforce_documentation_guardrail(ctx)
            self.assertIn("src/a.py", msg)
            self.assertIn("src/b.py", msg)

    async def test_contract_file_without_comment_is_exempt(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo, ["src/main.py"], ["src/main.py"])
            (repo / "src" / "main.py").write_text("def x():\n    return 1\n", encoding="utf-8")
            with mock.patch.object(orchestrator, "get_pipeline_snapshot_files", new_callable=AsyncMock) as git:
                self.assertIsNone(await orchestrator.enforce_documentation_guardrail(ctx))
            git.assert_not_awaited()  # contracted-only candidates short-circuit before any git call

    async def test_uncontracted_uncommented_new_source_is_doc_flagged(self) -> None:
        # With the infra-only scope-discipline guardrail retired, the doc guardrail directly polices an
        # uncontracted NEW source file (e.g. glue an entrypoint needs): it must carry a top-of-file
        # justification comment. A bare, commentless one is flagged (not silently exempted).
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo, ["README.md"], ["src/main.py"])  # main.py is uncontracted + new
            (repo / "src").mkdir(parents=True, exist_ok=True)
            (repo / "src" / "main.py").write_text("def x():\n    return 1\n", encoding="utf-8")  # no comment
            with mock.patch.object(orchestrator, "get_pipeline_snapshot_files",
                                   new=AsyncMock(return_value=["src/main.py"])):
                msg = await orchestrator.enforce_documentation_guardrail(ctx)
            self.assertIsNotNone(msg)
            self.assertIn("src/main.py", msg)

    async def test_misplaced_contracted_file_is_not_doc_flagged(self) -> None:
        # Contract wants root `models.py`; the Developer wrote `src/models.py`. The missing-contract
        # reroute owns that case (it issues a precise MOVE instruction), so the doc guardrail must NOT
        # mislabel the misplaced file as 'uncontracted glue needing justification'.
        with TemporaryDirectory() as td:
            repo = Path(td)
            ctx = self._ctx(repo, ["models.py"], ["src/models.py"])  # root models.py never written
            (repo / "src" / "models.py").write_text("def x():\n    return 1\n", encoding="utf-8")
            with mock.patch.object(orchestrator, "get_pipeline_snapshot_files", new_callable=AsyncMock) as git:
                self.assertIsNone(await orchestrator.enforce_documentation_guardrail(ctx))
            git.assert_not_awaited()  # basename excluded before any git call


class DocumentationGuardrailLoopTests(unittest.IsolatedAsyncioTestCase):
    """Loop integration: a free reroute spends no functional budget; the cap triggers a Hard Halt."""

    @staticmethod
    def _resume_ctx(base: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            logs_dir=base / "logs", reports_dir=base / "reports", repo_dir=base,
        )
        ctx = GlobalPipelineContext(
            pr_description="resume run", workspace_paths=paths, test_code_snapshot="existing tests",
        )
        ctx.contract = TechLeadContract(
            files_to_modify=["src/core/models.py"], instruction="noop", function_signatures="noop",
            strict_type_validation_rules="noop", techlead_reasoning="noop",
            environment_id="python-3.12-core",
            topology_contract=[{"file_path": "src/core/models.py", "exports": [], "depends_on": []}],
        )
        return ctx

    async def test_free_reroute_keeps_budget_and_bypasses_reviewer_until_documented(self) -> None:
        # Arrange — guardrail misses once then passes; the miss must reroute the Developer for free.
        with TemporaryDirectory() as td:
            ctx = self._resume_ctx(Path(td))

            async def _approve(*_a, **_k) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok", test_integrity_analysis="ok", log_verification_analysis="ok",
                    code_quality_approved=True, test_integrity_approved=True, dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "enforce_documentation_guardrail",
                                  new=AsyncMock(side_effect=["SYSTEM GUARDRAIL: add comment", None])),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
                mock.patch.object(GlobalPipelineContext, "save_checkpoint", autospec=True) as save_checkpoint,
            ):
                # Act
                await orchestrator.main()

            # Assert
            self.assertEqual(developer.await_count, 2)   # initial call + one free reroute
            reviewer.assert_awaited_once()               # Reviewer reached only after the guardrail passed
            qa.assert_not_called()                       # comment fix never regenerates tests
            self.assertEqual(ctx.current_attempt, 2)     # exactly ONE functional cycle consumed (1 → 2)
            save_checkpoint.assert_called_once()         # only the end-of-cycle save; the free reroute saves nothing
            # The reroute fed the guardrail diagnostic to the Developer as its error context.
            self.assertEqual(developer.await_args_list[1].args[1], "SYSTEM GUARDRAIL: add comment")

    async def test_compile_gate_failure_reroutes_developer_for_free(self) -> None:
        # Arrange — docs pass; the compile gate fails once then passes. The failure must fast-fail
        # reroute the Developer (no functional budget) with the build errors, then proceed.
        with TemporaryDirectory() as td:
            ctx = self._resume_ctx(Path(td))

            async def _approve(*_a, **_k) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok", test_integrity_analysis="ok", log_verification_analysis="ok",
                    code_quality_approved=True, test_integrity_approved=True, dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate",
                                  new=AsyncMock(side_effect=[(False, ["undefined: Foo"]), (True, [])])),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "enforce_documentation_guardrail", new=AsyncMock(return_value=None)),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
            ):
                await orchestrator.main()

            self.assertEqual(developer.await_count, 2)        # initial + one free compile reroute
            reviewer.assert_awaited_once()                    # Reviewer reached only after a clean build
            self.assertEqual(ctx.current_attempt, 2)          # exactly ONE functional cycle consumed
            self.assertIn("undefined: Foo", developer.await_args_list[1].args[1])  # build errors fed back

    async def test_environmental_build_failure_retries_then_proceeds_without_rerouting(self) -> None:
        # Arrange — the compile gate fails with a NETWORK/restore error (NU1301) once, then the cheap
        # retry succeeds. The Developer must NOT be rerouted (a feed blip is not a code defect) and the
        # run proceeds to the Reviewer on the same functional cycle.
        with TemporaryDirectory() as td:
            ctx = self._resume_ctx(Path(td))

            async def _approve(*_a, **_k) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok", test_integrity_analysis="ok", log_verification_analysis="ok",
                    code_quality_approved=True, test_integrity_approved=True, dev_diagnostic_payload="",
                )

            nu1301 = ["/workspace/x.csproj : error NU1301: Unable to load the service index for source https://api.nuget.org/v3/index.json"]
            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate",
                                  new=AsyncMock(side_effect=[(False, nu1301), (True, [])])),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "enforce_documentation_guardrail", new=AsyncMock(return_value=None)),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
            ):
                await orchestrator.main()

            developer.assert_awaited_once()                   # NO reroute — the network blip is not the Developer's fault
            reviewer.assert_awaited_once()                    # retry passed → proceed normally
            self.assertEqual(ctx.current_attempt, 2)          # exactly ONE functional cycle consumed (1 → 2)

    async def test_persistent_environmental_build_failure_halts_without_rerouting(self) -> None:
        # Arrange — the compile gate keeps failing with NU1301 (feed unreachable for the whole run).
        # The retry can't fix a real outage, so the run must FAIL FAST via an environment incident —
        # never rerouting the Developer (which would corrupt the contract) and never reaching the Reviewer.
        with TemporaryDirectory() as td:
            ctx = self._resume_ctx(Path(td))
            nu1301 = ["error NU1301:   Resource temporarily unavailable (api.nuget.org:443)"]
            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(False, nu1301))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "_abort_with_incident", side_effect=SystemExit(1)) as abort,
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "enforce_documentation_guardrail", new=AsyncMock(return_value=None)),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock()) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
            ):
                with self.assertRaises(SystemExit):
                    await orchestrator.main()

            abort.assert_called_once()                        # fail-fast environment incident
            developer.assert_awaited_once()                   # initial pass only — NEVER rerouted to "fix" the network
            reviewer.assert_not_awaited()                     # never reached → no code_quality rejection loop / breaker

    async def test_missing_contracted_file_reroutes_developer_for_free(self) -> None:
        # Arrange — a contracted file (LICENSE) is missing on the first dev pass, present on the second.
        with TemporaryDirectory() as td:
            ctx = self._resume_ctx(Path(td))

            async def _approve(*_a, **_k) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok", test_integrity_analysis="ok", log_verification_analysis="ok",
                    code_quality_approved=True, test_integrity_approved=True, dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", side_effect=[["LICENSE"], []]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "enforce_documentation_guardrail", new=AsyncMock(return_value=None)),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
            ):
                await orchestrator.main()

            self.assertEqual(developer.await_count, 2)        # initial + one free completeness reroute
            reviewer.assert_awaited_once()
            self.assertEqual(ctx.current_attempt, 2)          # one functional cycle consumed
            self.assertIn("LICENSE", developer.await_args_list[1].args[1])  # missing file named in the reroute

    async def test_compile_gate_test_only_failure_does_not_reroute_developer(self) -> None:
        # Arrange — compile gate fails but ONLY on test files (Go package loader parsing `*_test.go`).
        # The Developer must NOT be rerouted (tests are QA-owned); the run falls through to the gates.
        with TemporaryDirectory() as td:
            ctx = self._resume_ctx(Path(td))
            ctx.contract.environment_id = "go-1.23-cli"   # classifier keys off the env's test pattern

            async def _approve(*_a, **_k) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok", test_integrity_analysis="ok", log_verification_analysis="ok",
                    code_quality_approved=True, test_integrity_approved=True, dev_diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(
                    return_value=(False, ["internal/converter/processor_test.go:1:1: expected 'package', found 'import'"]))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "enforce_documentation_guardrail", new=AsyncMock(return_value=None)),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
            ):
                await orchestrator.main()

            developer.assert_awaited_once()   # NOT rerouted for a test-only build failure
            reviewer.assert_awaited_once()    # fell through to the gates/Reviewer

    async def test_cap_exhausted_triggers_hard_halt(self) -> None:
        # Arrange — guardrail keeps missing; after 2 free reroutes the run must hard-halt.
        with TemporaryDirectory() as td:
            ctx = self._resume_ctx(Path(td))

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "enforce_documentation_guardrail",
                                  new=AsyncMock(side_effect=["miss", "miss", "miss"])),
                mock.patch.object(orchestrator, "run_reviewer_node", new_callable=AsyncMock) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
            ):
                # Act / Assert
                with self.assertRaises(SystemExit) as exit_ctx:
                    await orchestrator.main()

            self.assertEqual(exit_ctx.exception.code, 1)
            self.assertEqual(developer.await_count, 3)   # initial + 2 fast-fail reroutes (cap=2)
            reviewer.assert_not_called()                 # Reviewer never reached
            self.assertEqual(ctx.current_attempt, 1)     # no functional-budget retry consumed
            self.assertTrue((ctx.workspace_paths.reports_dir / "incident_report.json").exists())


class FinancialCircuitBreakerTests(unittest.TestCase):
    """The token-budget breaker hard-halts via the incident machinery when spend is exceeded."""

    def _ctx(self, base: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            logs_dir=base / "logs", reports_dir=base / "reports", repo_dir=base,
        )
        return GlobalPipelineContext(pr_description="finops run", workspace_paths=paths)

    def test_trips_and_writes_incident_when_over_budget(self) -> None:
        # Arrange — 1100 cumulative tokens against a 1000 budget.
        with TemporaryDirectory() as td:
            base = Path(td)
            ctx = self._ctx(base)
            ctx.telemetry.record("Developer Agent", 900, 200, 0.5)
            # Act / Assert — breaker fires a non-zero hard-halt.
            with mock.patch.object(orchestrator, "PIPELINE_BUDGET_TOKENS", 1000):
                with self.assertRaises(SystemExit) as exit_ctx:
                    orchestrator.enforce_financial_circuit_breaker(ctx)
            self.assertEqual(exit_ctx.exception.code, 1)
            # Incident report carries the telemetry breakdown for audit.
            report = (base / "reports" / "incident_report.json").read_text(encoding="utf-8")
            self.assertIn("Developer Agent", report)
            self.assertIn("total_tokens", report)

    def test_noop_when_under_budget(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            base = Path(td)
            ctx = self._ctx(base)
            ctx.telemetry.record("TechLead", 10, 5)
            # Act — well under budget: must not raise, must not write an incident.
            with mock.patch.object(orchestrator, "PIPELINE_BUDGET_TOKENS", 1000):
                orchestrator.enforce_financial_circuit_breaker(ctx)
            self.assertFalse((base / "reports" / "incident_report.json").exists())


class TestCollectionTriageHelperTests(unittest.TestCase):
    """Deterministic helpers behind the Reviewer log feed."""

    def test_cap_text_bounds_length(self) -> None:
        capped = orchestrator._cap_text("x" * 20000, max_chars=8000)
        self.assertLessEqual(len(capped), 8000 + len("\n…[truncated]…\n"))
        self.assertIn("[truncated]", capped)

    def test_extract_failure_context_returns_whole_when_short(self) -> None:
        lines = ["a", "b", "c"]
        self.assertEqual(orchestrator._extract_failure_context(lines, max_lines=50), "a\nb\nc")

    def test_extract_failure_context_preserves_buried_import_error(self) -> None:
        # Root ImportError sits near the TOP, buried above a long tail of _FailedTest noise.
        lines = ["ImportError: cannot import name 'JSONConverter'"]
        lines += [f"noise {i}" for i in range(200)]
        out = orchestrator._extract_failure_context(lines, max_lines=50)
        # Marker-aware slice MUST keep the root error origin (a plain tail would have dropped it)…
        self.assertIn("ImportError: cannot import name 'JSONConverter'", out)
        # …and still keep the final summary tail.
        self.assertIn("noise 199", out)
        self.assertIn("…[snip]…", out)

    def test_extract_failure_context_falls_back_to_tail_without_marker(self) -> None:
        lines = [f"line {i}" for i in range(200)]
        out = orchestrator._extract_failure_context(lines, max_lines=50)
        self.assertTrue(out.endswith("line 199"))
        self.assertNotIn("…[snip]…", out)


class TestCollectionTriageRoutingTests(unittest.IsolatedAsyncioTestCase):
    """Dumb pipe: a collection failure flows straight to the Reviewer — the orchestrator never
    purges tests, re-runs QA, or skips the Reviewer based on the test exit code."""

    def _ctx(self, base: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            logs_dir=base / "logs", reports_dir=base / "reports", repo_dir=base,
        )
        ctx = GlobalPipelineContext(
            pr_description="triage run", workspace_paths=paths, test_code_snapshot="existing tests",
        )
        ctx.contract = TechLeadContract(
            files_to_modify=["src/calc.py"], instruction="noop", function_signatures="noop",
            strict_type_validation_rules="noop", techlead_reasoning="noop",
            environment_id="python-3.12-core",
            topology_contract=[{"file_path": "src/calc.py", "exports": [], "depends_on": []}],
        )
        return ctx

    async def test_import_failure_routes_to_developer_not_qa_purge(self) -> None:
        with TemporaryDirectory() as td:
            base = Path(td)
            ctx = self._ctx(base)
            stale = ctx.workspace_paths.repo_dir / "tests" / "test_stale.py"  # python separate-layout root
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_text("import does.not.exist", encoding="utf-8")

            captured = {}

            # Smart Reviewer: cycle 1 sees the ImportError and routes the fix to the Developer
            # (case a — broken production dep), NOT a QA test purge. Cycle 2 (Developer fixed the
            # imports → clean gate) approves and the pipeline completes.
            async def _review(_ctx, _qa_success, qa_log, *_a, **_k) -> None:
                first = "qa_log" not in captured
                captured.setdefault("qa_log", qa_log)
                _ctx.review_report = ReviewReport(
                    code_quality_analysis="x", test_integrity_analysis="x",
                    log_verification_analysis="x",
                    code_quality_approved=not first,      # reject on the import-failure cycle only
                    test_integrity_approved=True,         # tests are fine — never a QA regen
                    dev_diagnostic_payload="" if not first else "Fix the broken import in cli.py.",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "run_build_gate", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "_missing_contract_files", return_value=[]),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_techwriter_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_techlead_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "enforce_documentation_guardrail", new=AsyncMock(return_value=None)),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_review)) as reviewer,
                # Cycle 1 = import (collection) failure; cycle 2 = clean pass after the Developer fix.
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(side_effect=[
                    (False, ["unittest.loader._FailedTest", "ImportError: No module named 'src.base'"]),
                    (True, []),
                ])) as gate,
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
            ):
                await orchestrator.main()

            self.assertEqual(gate.await_count, 2)      # one gate run per cycle — no triage re-run loop
            self.assertEqual(developer.await_count, 2) # cycle 1 + the Reviewer-routed dependency fix
            qa.assert_not_awaited()                    # NOT routed to QA, and no exit-code-driven purge
            self.assertEqual(reviewer.await_count, 2)  # Reviewer reached every cycle (never bypassed)
            self.assertIn("ImportError", captured["qa_log"])  # failing log forwarded to the Reviewer
            self.assertTrue(stale.exists())            # orchestrator did NOT purge the failing test file


class FinOpsReportTests(unittest.TestCase):
    """Per-provider sub-totals string and the persisted finops_report.json."""

    def _ctx(self, base: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            logs_dir=base / "logs", reports_dir=base / "reports", repo_dir=base,
        )
        ctx = GlobalPipelineContext(pr_description="finops", workspace_paths=paths)
        ctx.telemetry.record("TechLead", 100, 20, 0.0003, provider="gemini")
        ctx.telemetry.record("Developer Agent", 1000, 200, 0.1328, provider="claude")
        return ctx

    def test_subtotals_string_names_both_providers(self) -> None:
        with TemporaryDirectory() as td:
            line = orchestrator._finops_subtotals(self._ctx(Path(td)))
        self.assertIn("Gemini est.", line)
        self.assertIn("Claude", line)
        self.assertIn("Σ", line)

    def test_write_finops_report_persists_breakdown(self) -> None:
        with TemporaryDirectory() as td:
            base = Path(td)
            ctx = self._ctx(base)
            with mock.patch.object(orchestrator, "PIPELINE_BUDGET_TOKENS", 10_000):
                orchestrator.write_finops_report(ctx)
            report = json.loads((base / "reports" / "finops_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["total_tokens"], 1320)
        self.assertEqual(report["budget_tokens"], 10_000)
        self.assertIn("gemini", report["by_provider"])
        self.assertIn("claude", report["by_provider"])


class MissingContractFilesTests(unittest.TestCase):
    """`_missing_contract_files` reports contracted production files absent from the working tree."""

    def test_reports_only_missing_non_test_files(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "main.go").write_text("package main\n", encoding="utf-8")  # present
            paths = WorkspacePaths(
                    logs_dir=repo / "logs", reports_dir=repo / "reports", repo_dir=repo,
            )
            contract = TechLeadContract(
                files_to_modify=["main.go", ".gitignore", "LICENSE", "main_test.go"],
                topology_contract=[], instruction="x", function_signatures="x",
                strict_type_validation_rules="x", techlead_reasoning="x",
                environment_id="go-1.23-cli",
            )
            ctx = GlobalPipelineContext(pr_description="t", workspace_paths=paths, contract=contract)

            missing = orchestrator._missing_contract_files(ctx)

            # main.go exists; .gitignore/LICENSE are missing; the *_test.go is QA-owned (excluded).
            self.assertEqual(sorted(missing), [".gitignore", "LICENSE"])


class MisplacedContractFilesTests(unittest.TestCase):
    """`_misplaced_contract_files` locates a same-basename file the Developer wrote at the wrong path."""

    @staticmethod
    def _ctx(repo: Path, files_to_modify: list[str]) -> GlobalPipelineContext:
        paths = WorkspacePaths(logs_dir=repo / "logs", reports_dir=repo / "reports", repo_dir=repo)
        contract = TechLeadContract(
            files_to_modify=files_to_modify, topology_contract=[], instruction="x",
            function_signatures="x", strict_type_validation_rules="x", techlead_reasoning="x",
            environment_id="dotnet-10-sdk",
        )
        return GlobalPipelineContext(pr_description="t", workspace_paths=paths, contract=contract)

    def test_finds_basename_match_under_subdir(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "src").mkdir()
            (repo / "src" / "Program.cs").write_text("// x\n", encoding="utf-8")
            ctx = self._ctx(repo, ["Program.cs"])
            found = orchestrator._misplaced_contract_files(ctx, ["Program.cs"])
            self.assertEqual(found, {"Program.cs": "src/Program.cs"})

    def test_genuinely_absent_file_is_not_misplaced(self) -> None:
        with TemporaryDirectory() as td:
            ctx = self._ctx(Path(td), ["LICENSE"])
            self.assertEqual(orchestrator._misplaced_contract_files(ctx, ["LICENSE"]), {})

    def test_correction_message_distinguishes_move_from_create(self) -> None:
        msg = orchestrator._format_contract_correction({"Program.cs": "src/Program.cs"}, ["LICENSE"])
        self.assertIn("WRONG path", msg)
        self.assertIn("`src/Program.cs` → must be `Program.cs`", msg)
        self.assertIn("did not create", msg)
        self.assertIn("LICENSE", msg)


class LintTestSuiteConsistencyTests(unittest.TestCase):
    """`lint_test_suite_consistency` flags a symbol invoked both static and instance in one suite."""

    def test_flags_static_and_instance_mix(self) -> None:
        snap = (
            "=== FILE: A.cs ===\nvar r = CommandLineOptions.Execute(a, b, c);\n"
            "=== FILE: B.cs ===\nint r = new CommandLineOptions().Execute(a, b, c);\n"
        )
        issues = orchestrator.lint_test_suite_consistency(snap, "Execute(...)")
        self.assertEqual(len(issues), 1)
        self.assertIn("CommandLineOptions.Execute", issues[0])

    def test_consistent_instance_only_suite_passes(self) -> None:
        snap = "var o = new CommandLineOptions();\nint r = o.Execute(a, b, c);\n"
        self.assertEqual(orchestrator.lint_test_suite_consistency(snap, "x"), [])

    def test_consistent_static_only_suite_passes(self) -> None:
        snap = "var r = CommandLineOptions.Execute(a, b, c);\nAssert.Equal(0, r);\n"
        self.assertEqual(orchestrator.lint_test_suite_consistency(snap, "x"), [])

    def test_empty_snapshot_is_noop(self) -> None:
        self.assertEqual(orchestrator.lint_test_suite_consistency("", "x"), [])


class BuildProductionSnapshotTests(unittest.TestCase):
    """The production snapshot must exclude COLOCATED test files (env-aware), not just `tests/`."""

    def setUp(self) -> None:
        import shutil
        if not shutil.which("git"):
            self.skipTest("git binary not available on PATH")

    @staticmethod
    def _git(args: list, cwd: Path) -> None:
        import subprocess
        subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)  # nosec B603 B607

    def _ctx(self, repo: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            logs_dir=repo / "logs", reports_dir=repo / "reports", repo_dir=repo,
        )
        contract = TechLeadContract(
            files_to_modify=["src/x.go"],
            topology_contract=[{"file_path": "src/x.go", "exports": ["X"], "depends_on": []}],
            instruction="impl", function_signatures="func X()",
            strict_type_validation_rules="n/a", techlead_reasoning="trivial",
            environment_id="go-1.23-cli",
        )
        return GlobalPipelineContext(
            pr_description="t", base_branch="main", workspace_paths=paths, contract=contract,
        )

    def test_excludes_colocated_go_test_file(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            self._git(["init"], repo)
            self._git(["config", "user.email", "t@sdlc.local"], repo)
            self._git(["config", "user.name", "t"], repo)
            (repo / "README.md").write_text("seed\n", encoding="utf-8")
            self._git(["add", "."], repo)
            self._git(["commit", "-m", "seed"], repo)
            self._git(["branch", "-M", "main"], repo)
            self._git(["checkout", "-b", "feat"], repo)
            (repo / "src").mkdir()
            (repo / "src" / "x.go").write_text("package x\n", encoding="utf-8")
            (repo / "src" / "x_test.go").write_text("package x\n", encoding="utf-8")  # colocated test

            ctx = self._ctx(repo)
            orchestrator.build_production_snapshot(ctx)

            # Production file captured; colocated *_test.go fenced out of the Developer's snapshot.
            self.assertIn("src/x.go", ctx.production_code_snapshot)
            self.assertNotIn("src/x_test.go", ctx.production_code_snapshot)


if __name__ == "__main__":
    unittest.main()

