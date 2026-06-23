"""Unit tests for the Nexus run-dir contract: per-run logs/reports/artifacts layout, per-phase
checkpointing + --resume, a clean incident on a terminal halt, and the checkpoint-kind router."""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import AsyncMock

os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.nexus import nexus_runner as nr
from src.nexus.nexus_runner import run_nexus
from src.nexus.state import NexusState
from src.nexus import runner as orchestrator
from src.nexus.runner import _checkpoint_kind, _run_dir_from_checkpoint
from src.shared.core.runs import Projects

_TASKS = [{"ticket_id": "TASK-01", "title": "Do it", "description": "body", "environment_id": "python-3.12-core"}]


def _patch_agents(po="# Epic", sa="# Blueprint", tpm=None):
    """Patch the three Nexus agents with AsyncMocks (no real LLM)."""
    return (
        mock.patch.object(nr, "run_po", new=AsyncMock(return_value=po)),
        mock.patch.object(nr, "run_sa", new=AsyncMock(return_value=sa)),
        mock.patch.object(nr, "run_tpm", new=AsyncMock(return_value=tpm if tpm is not None else _TASKS)),
    )


class NexusRunDirTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_run_builds_full_layout_and_checkpoint(self) -> None:
        with TemporaryDirectory() as td:
            run_dir = Path(td) / "run_x"
            p_po, p_sa, p_tpm = _patch_agents()
            with p_po, p_sa, p_tpm:
                out = await run_nexus("an idea", run_dir=run_dir)

            self.assertEqual(out, run_dir)
            # Same structure as the executor: logs/ + reports/, plus the artifacts/ deliverables dir.
            self.assertTrue((run_dir / "logs").is_dir())
            self.assertTrue((run_dir / "reports").is_dir())
            self.assertTrue((run_dir / "artifacts" / "epic.md").is_file())
            self.assertTrue((run_dir / "artifacts" / "blueprint.md").is_file())
            self.assertTrue((run_dir / "artifacts" / "TASK-01.md").is_file())
            self.assertTrue((run_dir / "reports" / "finops_report.json").is_file())
            # Checkpoint exists, is tagged nexus, and records the run as fully complete.
            ckpt = json.loads((run_dir / "reports" / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(ckpt["kind"], "nexus")
            self.assertEqual(ckpt["completed_phase"], "TPM")

    async def test_task01_gets_engine_baseline_files_others_do_not(self) -> None:
        # TASK-01 (repo-prep) is appended the engine-curated .gitignore + MIT LICENSE so the TPM never
        # reproduces them (the RECITATION root cause); business tickets stay free of baseline files.
        tasks = [
            {"ticket_id": "TASK-01", "title": "Prep", "description": "prep body", "environment_id": "python-3.12-core"},
            {"ticket_id": "TASK-02", "title": "Feature", "description": "feature body", "environment_id": "python-3.12-core"},
        ]
        with TemporaryDirectory() as td:
            run_dir = Path(td) / "run_b"
            p_po, p_sa, p_tpm = _patch_agents(tpm=tasks)
            with p_po, p_sa, p_tpm:
                await run_nexus("an idea", run_dir=run_dir)

            t1 = (run_dir / "artifacts" / "TASK-01.md").read_text(encoding="utf-8")
            t2 = (run_dir / "artifacts" / "TASK-02.md").read_text(encoding="utf-8")
            self.assertIn("Repository Baseline Files (engine-provided", t1)
            self.assertIn("Permission is hereby granted", t1)        # full MIT body injected
            self.assertIn("```gitignore", t1)
            self.assertNotIn("Repository Baseline Files", t2)        # business ticket untouched
            self.assertNotIn("Permission is hereby granted", t2)

    async def test_resume_skips_completed_phases(self) -> None:
        with TemporaryDirectory() as td:
            run_dir = Path(td) / "run_y"
            # Seed a checkpoint as if PO+SA already finished; only TPM should run on resume.
            seed = NexusState.new("an idea", run_dir)
            seed.epic_text, seed.blueprint_text = "# Epic", "# Blueprint"
            seed.completed_phase = "SA"
            seed.ensure_dirs()
            seed.save_checkpoint()

            p_po, p_sa, p_tpm = _patch_agents()
            with p_po as m_po, p_sa as m_sa, p_tpm as m_tpm:
                await run_nexus(resume=seed.checkpoint_path)
                m_po.assert_not_awaited()              # PO skipped — epic reused from checkpoint
                m_sa.assert_not_awaited()              # SA skipped — blueprint reused
                m_tpm.assert_awaited_once()            # only the unfinished phase runs

            self.assertTrue((run_dir / "artifacts" / "TASK-01.md").is_file())

    async def test_terminal_failure_writes_incident_and_exits_clean(self) -> None:
        with TemporaryDirectory() as td:
            run_dir = Path(td) / "run_z"
            p_po, p_sa, _ = _patch_agents()
            p_tpm = mock.patch.object(nr, "run_tpm", new=AsyncMock(side_effect=ValueError("RECITATION-ish")))
            with p_po, p_sa, p_tpm:
                with self.assertRaises(SystemExit) as cm:
                    await run_nexus("an idea", run_dir=run_dir)
            self.assertEqual(cm.exception.code, 1)
            self.assertTrue((run_dir / "reports" / "incident_report.json").is_file())


class NexusMainRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_idea_creates_project_umbrella_and_nexus_run(self) -> None:
        with TemporaryDirectory() as td:
            runs_base = Path(td)
            p_po, p_sa, p_tpm = _patch_agents()
            with (
                mock.patch.object(orchestrator, "RUNS_BASE", runs_base),
                mock.patch.object(orchestrator, "reconfigure_logging"),   # don't pin an audit file in temp
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=None, reset_attempts=False,
                    idea="CLI: JSON to CSV", repo="git@h:r.git")),
                p_po, p_sa, p_tpm,
            ):
                await orchestrator.main()

            project = runs_base / "cli-json-to-csv"
            self.assertTrue((project / "project.json").is_file())          # umbrella manifest
            nexus_runs = list(project.glob("001_nexus_plan_*"))
            self.assertEqual(len(nexus_runs), 1)                            # numbered planning run
            self.assertTrue((nexus_runs[0] / "artifacts" / "epic.md").is_file())


class ExecRunProjectRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_resolves_repo_and_ticket_body_from_project(self) -> None:
        with TemporaryDirectory() as td:
            runs_base = Path(td)
            store = Projects(runs_base)
            store.create("proj", repo="git@h:r.git", base_branch="dev")
            nexus_run = store.allocate("proj", "nexus", "plan")
            (nexus_run / "artifacts").mkdir(parents=True)
            (nexus_run / "artifacts" / "TASK-01.md").write_text("# Do the thing\n\nbody", encoding="utf-8")

            captured: dict = {}

            class _Stop(Exception):
                pass

            async def _boot(cfg, run_dir):   # capture the resolved cfg, then halt before the FSM loop
                captured.update(repo=cfg.repo, base=cfg.base_branch, desc=cfg.description, file=cfg.file)
                raise _Stop()

            with (
                mock.patch.object(orchestrator, "RUNS_BASE", runs_base),
                mock.patch.object(orchestrator, "reconfigure_logging"),
                mock.patch.object(orchestrator, "check_environment"),
                mock.patch.object(orchestrator, "bootstrap_session", new=_boot),
                mock.patch.object(orchestrator, "parse_args", return_value=orchestrator.RunConfig(
                    description=None, base_branch="main", resume=None, reset_attempts=False,
                    run_project="proj", ticket="TASK-01")),
            ):
                with self.assertRaises(_Stop):
                    await orchestrator.main()

            self.assertEqual(captured["repo"], "git@h:r.git")     # repo from project.json
            self.assertEqual(captured["base"], "dev")             # base branch from project.json
            self.assertIn("Do the thing", captured["desc"])       # ticket BODY becomes the description
            self.assertTrue(captured["file"].endswith("TASK-01.md"))


class CheckpointRouterTests(unittest.TestCase):
    def test_nexus_checkpoint_detected_executor_and_garbage_are_not(self) -> None:
        with TemporaryDirectory() as td:
            nexus_ckpt = Path(td) / "reports" / "checkpoint.json"
            nexus_ckpt.parent.mkdir(parents=True)
            nexus_ckpt.write_text(json.dumps({"kind": "nexus"}), encoding="utf-8")
            exec_ckpt = Path(td) / "exec.json"
            exec_ckpt.write_text(json.dumps({"pr_description": "x"}), encoding="utf-8")

            self.assertEqual(_checkpoint_kind(nexus_ckpt), "nexus")
            self.assertIsNone(_checkpoint_kind(exec_ckpt))               # executor → no kind
            self.assertIsNone(_checkpoint_kind(Path(td) / "missing.json"))
            # run dir is the checkpoint's grandparent under the canonical reports/ layout.
            self.assertEqual(_run_dir_from_checkpoint(nexus_ckpt), Path(td).resolve())


class GetTasksForNexusRunTests(unittest.TestCase):
    """E1 task enumeration: checkpoint order is authoritative (no sorting); the no-checkpoint fallback
    natural-sorts artifacts so TASK-2 precedes TASK-10."""

    def test_checkpoint_preserves_tpm_list_order(self) -> None:
        with TemporaryDirectory() as td:
            run_dir = Path(td) / "run_x"
            state = NexusState(raw_idea="i", run_dir=run_dir, tasks=[
                {"ticket_id": "TASK-10", "title": "ten", "description": "b", "environment_id": "python-3.12-core"},
                {"ticket_id": "TASK-2", "title": "two", "description": "b", "environment_id": "python-3.12-core"},
            ])
            state.ensure_dirs()
            state.save_checkpoint()
            # Authoritative order = the TPM list order, NOT a re-sort of the ids.
            self.assertEqual(nr.get_tasks_for_nexus_run(run_dir), ["TASK-10", "TASK-2"])

    def test_fallback_scans_artifacts_in_natural_order(self) -> None:
        with TemporaryDirectory() as td:
            run_dir = Path(td) / "run_y"
            artifacts = run_dir / "artifacts"
            artifacts.mkdir(parents=True)
            for name in ("TASK-2.md", "TASK-10.md", "epic.md", "blueprint.md"):
                (artifacts / name).write_text("x", encoding="utf-8")
            # No reports/checkpoint.json → fallback. Natural sort (2 < 10); epic/blueprint excluded.
            self.assertEqual(nr.get_tasks_for_nexus_run(run_dir), ["TASK-2", "TASK-10"])

    def test_empty_when_no_checkpoint_and_no_artifacts(self) -> None:
        with TemporaryDirectory() as td:
            self.assertEqual(nr.get_tasks_for_nexus_run(Path(td) / "nope"), [])


if __name__ == "__main__":
    unittest.main()
