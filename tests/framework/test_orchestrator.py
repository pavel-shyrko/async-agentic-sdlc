"""Unit tests for checkpoint/resume orchestration flow."""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import AsyncMock

# orchestrator imports src.core.config at module import time.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

import orchestrator
from src.core.models import GlobalPipelineContext, ReviewReport, WorkspacePaths


class ParseArgsResumeTests(unittest.TestCase):
    """CLI parser must accept --resume without requiring task description input."""

    def test_resume_does_not_require_description(self) -> None:
        # Arrange
        argv = ["orchestrator.py", "--resume", "artifacts/reports/checkpoint.json"]
        # Act
        with mock.patch.object(sys, "argv", argv):
            description, base_branch, resume_path, reset_attempts = orchestrator.parse_args()
        # Assert
        self.assertIsNone(description)
        self.assertEqual(base_branch, "main")
        self.assertEqual(resume_path, Path("artifacts/reports/checkpoint.json"))
        self.assertFalse(reset_attempts)

    def test_reset_attempts_flag_is_propagated(self) -> None:
        # Arrange
        argv = ["orchestrator.py", "--resume", "cp.json", "--reset-attempts"]
        # Act
        with mock.patch.object(sys, "argv", argv):
            _description, _base_branch, _resume, reset_attempts = orchestrator.parse_args()
        # Assert
        self.assertTrue(reset_attempts)


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
                mock.patch.object(orchestrator, "parse_args", return_value=(None, "main", Path("cp.json"), False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock) as architect,
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_set_approved_review)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
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
            mock.patch.object(orchestrator, "parse_args", return_value=(None, "main", Path("bad.json"), False)),
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
                mock.patch.object(orchestrator, "parse_args", return_value=("fresh run", "main", None, False)),
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
                mock.patch.object(orchestrator, "parse_args", return_value=(None, "main", Path("cp.json"), False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock) as architect,
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "new tests"))) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_set_approved_review)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
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
                mock.patch.object(orchestrator, "parse_args", return_value=("fresh run", "main", None, False)),
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
                mock.patch.object(orchestrator, "parse_args", return_value=(None, "main", Path("cp.json"), False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock) as architect,
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "fresh tests"))) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
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
                mock.patch.object(orchestrator, "parse_args", return_value=(None, "main", Path("cp.json"), False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock),
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
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
                mock.patch.object(orchestrator, "parse_args", return_value=(None, "main", Path("cp.json"), False)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock) as architect,
                mock.patch.object(orchestrator, "run_qa_agent_node", new_callable=AsyncMock) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new_callable=AsyncMock) as reviewer,
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
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
                mock.patch.object(orchestrator, "parse_args", return_value=(None, "main", Path("cp.json"), True)),
                mock.patch.object(GlobalPipelineContext, "load_checkpoint", return_value=ctx),
                mock.patch.object(orchestrator, "run_architect_node", new_callable=AsyncMock) as architect,
                mock.patch.object(orchestrator, "run_qa_agent_node", new=AsyncMock(side_effect=lambda c, _e: setattr(c, "test_code_snapshot", "fresh tests"))) as qa,
                mock.patch.object(orchestrator, "run_developer_node", new_callable=AsyncMock) as developer,
                mock.patch.object(orchestrator, "run_reviewer_node", new=AsyncMock(side_effect=_approve)),
                mock.patch.object(orchestrator, "run_qa_unit_tests", new=AsyncMock(return_value=(True, []))),
                mock.patch.object(orchestrator, "run_security_scan", new=AsyncMock(return_value=(True, []))),
            ):
                # Act
                await orchestrator.main()

            # Assert
            architect.assert_not_called()
            qa.assert_awaited_once()
            self.assertEqual(developer.await_count, 1)
            # After the single successful cycle the persisted counter advances from 1 to 2.
            self.assertEqual(ctx.current_attempt, 2)


if __name__ == "__main__":
    unittest.main()

