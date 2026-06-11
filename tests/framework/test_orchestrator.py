"""Unit tests for checkpoint/resume orchestration flow."""
import os
import sys
import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import AsyncMock

# orchestrator imports src.core.config at module import time.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

import orchestrator
from src.core.models import ArchitectureContract, GlobalPipelineContext, ReviewReport, WorkspacePaths


class ParseArgsResumeTests(unittest.TestCase):
    """CLI parser must accept --resume without requiring repo/ticket/description input."""

    def test_resume_does_not_require_repo_or_description(self) -> None:
        # Arrange
        argv = ["orchestrator.py", "--resume", "artifacts/reports/checkpoint.json"]
        # Act
        with mock.patch.object(sys, "argv", argv):
            cfg = orchestrator.parse_args()
        # Assert
        self.assertIsNone(cfg.description)
        self.assertEqual(cfg.base_branch, "main")
        self.assertEqual(cfg.resume, Path("artifacts/reports/checkpoint.json"))
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
        self.assertEqual(cfg.src_dir, "src/")
        self.assertEqual(cfg.tests_dir, "tests/")
        self.assertIsNone(cfg.resume)

    def test_inline_description_overrides_ticket_fallback(self) -> None:
        # Arrange
        argv = ["orchestrator.py", "build the X", "--repo", "r", "--ticket", "T-9"]
        # Act
        with mock.patch.object(sys, "argv", argv):
            cfg = orchestrator.parse_args()
        # Assert
        self.assertEqual(cfg.description, "build the X")

    def test_src_and_tests_dir_overrides_are_captured(self) -> None:
        # Arrange
        argv = ["orchestrator.py", "--repo", "r", "--ticket", "T", "--src-dir", "app/", "--tests-dir", "spec/"]
        # Act
        with mock.patch.object(sys, "argv", argv):
            cfg = orchestrator.parse_args()
        # Assert
        self.assertEqual(cfg.src_dir, "app/")
        self.assertEqual(cfg.tests_dir, "spec/")

    def test_push_flag_defaults_false_and_opts_in(self) -> None:
        # Arrange / Act — default off.
        with mock.patch.object(sys, "argv", ["orchestrator.py", "--repo", "r", "--ticket", "T"]):
            self.assertFalse(orchestrator.parse_args().push)
        # Act — explicit opt-in.
        with mock.patch.object(sys, "argv", ["orchestrator.py", "--repo", "r", "--ticket", "T", "--push"]):
            self.assertTrue(orchestrator.parse_args().push)


class MainResumeSkipFlowTests(unittest.IsolatedAsyncioTestCase):
    """Resume flow must bypass completed FSM nodes and still checkpoint each cycle."""

    async def test_resume_skips_architect_and_initial_qa_generation(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                code_dir=base / "code",
                tests_dir=base / "tests",
                logs_dir=base / "logs",
                reports_dir=base / "reports",
            )
            ctx = GlobalPipelineContext(
                pr_description="resume run",
                workspace_paths=paths,
                test_code_snapshot="existing tests",
            )
            ctx.contract = {
                "files_to_modify": ["src/core/models.py"],
                "instruction": "noop",
                "function_signatures": "noop",
                "strict_type_validation_rules": "noop",
                "architecture_reasoning": "noop",
            }

            async def _set_approved_review(*_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock) as architect,
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_set_approved_review)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(GlobalPipelineContext, "save_checkpoint", autospec=True) as save_checkpoint,
            ):
                # Act
                await orchestrator.main()

            # Assert
            architect.assert_not_called()
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

    async def test_fresh_run_saves_after_architect_after_qa_and_end_of_cycle(self) -> None:
        # Arrange
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                code_dir=base / "code",
                tests_dir=base / "tests",
                logs_dir=base / "logs",
                reports_dir=base / "reports",
            )

            async def _set_approved_review(ctx: GlobalPipelineContext, *_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description="fresh run", base_branch="main", resume=None, reset_attempts=False,
                    repo="dummy-repo", ticket="DEMO-1")),
                mock.patch.object(orchestrator, "bootstrap_session", new=AsyncMock(return_value=paths)),
                mock.patch.object(GlobalPipelineContext, "save_checkpoint", autospec=True) as save_checkpoint,
                mock.patch.object(orchestrator, "run_architect_node", new=AsyncMock(side_effect=lambda c: setattr(c, "contract", {
                    "files_to_modify": ["src/core/models.py"],
                    "instruction": "noop",
                    "function_signatures": "noop",
                    "strict_type_validation_rules": "noop",
                    "architecture_reasoning": "noop",
                }))),
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "tests"))),
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_set_approved_review)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
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
                code_dir=base / "code",
                tests_dir=base / "tests",
                logs_dir=base / "logs",
                reports_dir=base / "reports",
            )
            ctx = GlobalPipelineContext(pr_description="resume run", workspace_paths=paths)
            ctx.contract = {
                "files_to_modify": ["src/core/models.py"],
                "instruction": "noop",
                "function_signatures": "noop",
                "strict_type_validation_rules": "noop",
                "architecture_reasoning": "noop",
            }

            async def _set_approved_review(*_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock) as architect,
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "new tests"))) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_set_approved_review)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
                mock.patch.object(GlobalPipelineContext, "save_checkpoint", autospec=True) as save_checkpoint,
            ):
                # Act
                await orchestrator.main()

            # Assert
            architect.assert_not_called()
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
                code_dir=base / "code",
                tests_dir=base / "tests",
                logs_dir=base / "logs",
                reports_dir=base / "reports",
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
                        diagnostic_payload="fix implementation",
                    )
                    return
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="all green",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description="fresh run", base_branch="main", resume=None, reset_attempts=False,
                    repo="dummy-repo", ticket="DEMO-1")),
                mock.patch.object(orchestrator, "bootstrap_session", new=AsyncMock(return_value=paths)),
                mock.patch.object(GlobalPipelineContext, "save_checkpoint", autospec=True) as save_checkpoint,
                mock.patch.object(orchestrator, "run_architect_node", new=AsyncMock(side_effect=lambda c: setattr(c, "contract", {
                    "files_to_modify": ["src/core/models.py"],
                    "instruction": "noop",
                    "function_signatures": "noop",
                    "strict_type_validation_rules": "noop",
                    "architecture_reasoning": "noop",
                }))),
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "tests"))) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_review_reject_then_approve)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(side_effect=[(False, ["fail"]), (True, [])])),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
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
                code_dir=base / "code",
                tests_dir=base / "tests",
                logs_dir=base / "logs",
                reports_dir=base / "reports",
            )
            ctx = GlobalPipelineContext(
                pr_description="resume after rejection",
                workspace_paths=paths,
                test_code_snapshot="stale test suite",
                current_attempt=2,
            )
            ctx.contract = {
                "files_to_modify": ["src/core/models.py"],
                "instruction": "noop",
                "function_signatures": "noop",
                "strict_type_validation_rules": "noop",
                "architecture_reasoning": "noop",
            }
            ctx.review_report = ReviewReport(
                code_quality_analysis="ok",
                test_integrity_analysis="loophole detected",
                log_verification_analysis="ok",
                code_quality_approved=True,
                test_integrity_approved=False,
                diagnostic_payload="rewrite tests",
            )

            async def _approve(*_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock) as architect,
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "fresh tests"))) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
            ):
                # Act
                await orchestrator.main()

            # Assert
            architect.assert_not_called()
            qa.assert_awaited_once()
            self.assertEqual(ctx.test_code_snapshot, "fresh tests")

    async def test_resume_starts_from_persisted_attempt_counter(self) -> None:
        # Arrange â€” a checkpoint persisted at end of cycle 2 (counter pre-incremented to 3)
        # must yield a single remaining cycle so the original retry budget is preserved.
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                code_dir=base / "code",
                tests_dir=base / "tests",
                logs_dir=base / "logs",
                reports_dir=base / "reports",
            )
            ctx = GlobalPipelineContext(
                pr_description="resume late",
                workspace_paths=paths,
                test_code_snapshot="approved tests",
                current_attempt=3,
            )
            ctx.contract = {
                "files_to_modify": ["src/core/models.py"],
                "instruction": "noop",
                "function_signatures": "noop",
                "strict_type_validation_rules": "noop",
                "architecture_reasoning": "noop",
            }
            ctx.review_report = ReviewReport(
                code_quality_analysis="needs fix",
                test_integrity_analysis="ok",
                log_verification_analysis="ok",
                code_quality_approved=False,
                test_integrity_approved=True,
                diagnostic_payload="fix prod",
            )

            async def _approve(*_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
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
                code_dir=base / "code",
                tests_dir=base / "tests",
                logs_dir=base / "logs",
                reports_dir=base / "reports",
            )
            ctx = GlobalPipelineContext(
                pr_description="resume exhausted",
                workspace_paths=paths,
                test_code_snapshot="tests",
                current_attempt=4,
            )
            ctx.contract = {
                "files_to_modify": ["src/core/models.py"],
                "instruction": "noop",
                "function_signatures": "noop",
                "strict_type_validation_rules": "noop",
                "architecture_reasoning": "noop",
            }

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock) as architect,
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new_callable=AsyncMock) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
            ):
                with self.assertRaises(SystemExit) as exit_ctx:
                    await orchestrator.main()

            # Assert
            self.assertEqual(exit_ctx.exception.code, 1)
            architect.assert_not_called()
            qa.assert_not_called()
            developer.assert_not_called()
            reviewer.assert_not_called()

    async def test_reset_attempts_flag_restores_full_retry_budget(self) -> None:
        # Arrange — checkpoint is past the retry budget AND has rejected tests, so
        # the only way QA gets a fresh attempt is via --reset-attempts.
        with TemporaryDirectory() as td:
            base = Path(td)
            paths = WorkspacePaths(
                code_dir=base / "code",
                tests_dir=base / "tests",
                logs_dir=base / "logs",
                reports_dir=base / "reports",
            )
            ctx = GlobalPipelineContext(
                pr_description="resume with reset",
                workspace_paths=paths,
                test_code_snapshot="stale tests",
                current_attempt=4,
            )
            ctx.contract = {
                "files_to_modify": ["src/core/models.py"],
                "instruction": "noop",
                "function_signatures": "noop",
                "strict_type_validation_rules": "noop",
                "architecture_reasoning": "noop",
            }
            ctx.review_report = ReviewReport(
                code_quality_analysis="ok",
                test_integrity_analysis="brittle assertions",
                log_verification_analysis="ok",
                code_quality_approved=True,
                test_integrity_approved=False,
                diagnostic_payload="rewrite tests without string matching",
            )

            async def _approve(*_args, **_kwargs) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok",
                    test_integrity_analysis="ok",
                    log_verification_analysis="ok",
                    code_quality_approved=True,
                    test_integrity_approved=True,
                    diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=True)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock) as architect,
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "fresh tests"))) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
            ):
                # Act
                await orchestrator.main()

            # Assert
            architect.assert_not_called()
            qa.assert_awaited_once()
            self.assertEqual(developer.await_count, 1)
            # After the single successful cycle the persisted counter advances from 1 to 2.
            self.assertEqual(ctx.current_attempt, 2)


class BootstrapSessionTests(unittest.IsolatedAsyncioTestCase):
    """Session bootstrap must shallow-clone, branch, map paths, and re-anchor logging."""

    async def test_shallow_clone_branch_and_workspace_mapping(self) -> None:
        # Arrange — the caller owns run_dir (logging is re-anchored by main(), not bootstrap).
        with TemporaryDirectory() as td:
            cfg = orchestrator.RunConfig(
                description="d", base_branch="main", resume=None, reset_attempts=False,
                repo="some-repo", ticket="DEMO-1", src_dir="src/", tests_dir="tests/",
            )
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
            self.assertEqual(paths.code_dir.name, "src")
            self.assertEqual(paths.tests_dir.name, "tests")
            self.assertEqual(paths.logs_dir, (run_dir / "logs").resolve())
            self.assertEqual(paths.reports_dir, (run_dir / "reports").resolve())

    async def test_clone_failure_aborts_with_exit_1(self) -> None:
        # Arrange — git clone returns non-zero; the run must abort and surface the child's stderr.
        with TemporaryDirectory() as td:
            cfg = orchestrator.RunConfig(
                description="d", base_branch="main", resume=None, reset_attempts=False,
                repo="bad-repo", ticket="T", src_dir="src/", tests_dir="tests/",
            )
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
                repo="slow-repo", ticket="T", src_dir="src/", tests_dir="tests/",
            )
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


class FinalizeTransactionTests(unittest.IsolatedAsyncioTestCase):
    """The success transaction commits the staged delta atomically (and optionally pushes)."""

    def _ctx(self, base: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            code_dir=base / "code", tests_dir=base / "tests",
            logs_dir=base / "logs", reports_dir=base / "reports",
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
        for lead in ("// c-style", "/* block", "* continuation", '"""docstring', "'''docstring"):
            with TemporaryDirectory() as td:
                p = self._write(td, "a.txt", lead + "\nbody\n")
                self.assertIs(orchestrator._top_block_has_comment(p), True, lead)


class EnforceDocumentationGuardrailTests(unittest.IsolatedAsyncioTestCase):
    """The fast-fail middleware flags only undocumented, newly-created, uncontracted files."""

    @staticmethod
    def _ctx(repo: Path, files_to_modify: list[str], snapshot_keys: list[str]) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            code_dir=repo / "src", tests_dir=repo / "tests",
            logs_dir=repo / "logs", reports_dir=repo / "reports", repo_dir=repo,
        )
        ctx = GlobalPipelineContext(pr_description="t", base_branch="main", workspace_paths=paths)
        ctx.contract = ArchitectureContract(
            files_to_modify=files_to_modify, instruction="i", function_signatures="s",
            strict_type_validation_rules="r", architecture_reasoning="why",
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


class DocumentationGuardrailLoopTests(unittest.IsolatedAsyncioTestCase):
    """Loop integration: a free reroute spends no functional budget; the cap triggers a Hard Halt."""

    @staticmethod
    def _resume_ctx(base: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            code_dir=base / "code", tests_dir=base / "tests",
            logs_dir=base / "logs", reports_dir=base / "reports",
        )
        ctx = GlobalPipelineContext(
            pr_description="resume run", workspace_paths=paths, test_code_snapshot="existing tests",
        )
        ctx.contract = ArchitectureContract(
            files_to_modify=["src/core/models.py"], instruction="noop", function_signatures="noop",
            strict_type_validation_rules="noop", architecture_reasoning="noop",
        )
        return ctx

    async def test_free_reroute_keeps_budget_and_bypasses_reviewer_until_documented(self) -> None:
        # Arrange — guardrail misses once then passes; the miss must reroute the Developer for free.
        with TemporaryDirectory() as td:
            ctx = self._resume_ctx(Path(td))

            async def _approve(*_a, **_k) -> None:
                ctx.review_report = ReviewReport(
                    code_quality_analysis="ok", test_integrity_analysis="ok", log_verification_analysis="ok",
                    code_quality_approved=True, test_integrity_approved=True, diagnostic_payload="",
                )

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "enforce_documentation_guardrail",
                                  new=AsyncMock(side_effect=["SYSTEM GUARDRAIL: add comment", None])),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
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

    async def test_cap_exhausted_triggers_hard_halt(self) -> None:
        # Arrange — guardrail keeps missing; after 2 free reroutes the run must hard-halt.
        with TemporaryDirectory() as td:
            ctx = self._resume_ctx(Path(td))

            with (
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "build_production_snapshot"),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=Path("cp.json"), reset_attempts=False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "enforce_documentation_guardrail",
                                  new=AsyncMock(side_effect=["miss", "miss", "miss"])),
                mock.patch.object(orchestrator, "run_reviewer_node", new_callable=AsyncMock) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "finalize_transaction", new_callable=AsyncMock),
            ):
                # Act / Assert
                with self.assertRaises(SystemExit) as exit_ctx:
                    await orchestrator.main()

            self.assertEqual(exit_ctx.exception.code, 1)
            self.assertEqual(developer.await_count, 3)   # initial + 2 fast-fail reroutes (cap=2)
            reviewer.assert_not_called()                 # Reviewer never reached
            self.assertEqual(ctx.current_attempt, 1)     # no functional-budget retry consumed
            self.assertTrue((ctx.workspace_paths.reports_dir / "incident_report.json").exists())


if __name__ == "__main__":
    unittest.main()

