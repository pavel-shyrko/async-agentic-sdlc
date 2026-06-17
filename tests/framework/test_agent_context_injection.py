"""Unit tests for the PROJECT CONTEXT injection into the Developer and QA prompts.

`TechLeadContract.shared_context` carries the language-neutral project goal so the Developer and QA
understand WHAT they are building (and don't fabricate it) — while the contract Directives / snapshot
stay authoritative. These tests assert the block is injected when set and omitted when empty, mocking
the LLM/CLI boundaries so no Docker, git network, or real model call is needed.
"""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import AsyncMock

# Agents import src.shared.core.config at module import time.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.executor.agents import developer, qa
from src.shared.core.models import GlobalPipelineContext, TechLeadContract, WorkspacePaths, QATestSuite

_DEV_BLOCK = "=== PROJECT CONTEXT (reference only"
_QA_BLOCK = "=== PROJECT CONTEXT (reference) ==="
_GOAL = "A CLI tool that converts JSON files to CSV."


def _paths(root: Path) -> WorkspacePaths:
    return WorkspacePaths(
        code_dir=root / "src", tests_dir=root / "tests",
        logs_dir=root / "logs", reports_dir=root / "reports", repo_dir=root,
    )


def _contract(shared_context: str, files=("src/calc.py",)) -> TechLeadContract:
    return TechLeadContract(
        files_to_modify=list(files),
        topology_contract=[{"file_path": "src/calc.py", "exports": ["add"], "depends_on": []}],
        instruction="Implement add(a, b).",
        shared_context=shared_context,
        function_signatures="def add(a: int, b: int) -> int",
        strict_type_validation_rules="Operands must be int.",
        techlead_reasoning="trivial",
        environment_id="python-3.12-core",
    )


class DeveloperContextInjectionTests(unittest.IsolatedAsyncioTestCase):
    """The Developer prompt carries the subordinate PROJECT CONTEXT block iff shared_context is set."""

    async def _captured_prompt(self, shared_context: str) -> str:
        with TemporaryDirectory() as td:
            ctx = GlobalPipelineContext(pr_description="x", workspace_paths=_paths(Path(td)))
            ctx.contract = _contract(shared_context)
            with (
                mock.patch.object(developer, "build_agent_context", new=AsyncMock(return_value="SKILLS")),
                mock.patch.object(developer, "run_claude_cli", new=AsyncMock(return_value=(0, None))) as cli,
            ):
                await developer.run_developer_node(ctx)
            return cli.await_args.args[0]  # first positional arg to run_claude_cli is the prompt

    async def test_block_present_when_context_set(self) -> None:
        prompt = await self._captured_prompt(_GOAL)
        self.assertIn(_DEV_BLOCK, prompt)
        self.assertIn(_GOAL, prompt)

    async def test_block_absent_when_context_empty(self) -> None:
        prompt = await self._captured_prompt("")
        self.assertNotIn(_DEV_BLOCK, prompt)


class QaContextInjectionTests(unittest.IsolatedAsyncioTestCase):
    """The QA system prompt carries the reference PROJECT CONTEXT block iff shared_context is set."""

    async def _captured_system_prompt(self, shared_context: str) -> str:
        captured: dict = {}

        async def _fake_llm(node, model, messages):
            captured["system"] = messages[0]["content"]
            return QATestSuite(new_imports="import unittest", new_test_code="class T: pass"), {}

        with TemporaryDirectory() as td:
            root = Path(td)
            ctx = GlobalPipelineContext(pr_description="x", base_branch="main", workspace_paths=_paths(root))
            ctx.contract = _contract(shared_context)
            ctx.repository_map = "MAP"  # pre-set so generate_repo_map is never invoked
            with (
                mock.patch.object(qa, "build_agent_context", new=AsyncMock(return_value="SKILLS")),
                mock.patch.object(qa, "run_structured_llm", side_effect=_fake_llm),
                mock.patch.object(qa, "log_token_usage"),
                mock.patch.object(qa, "get_git_root", new=AsyncMock(return_value=str(root))),
                mock.patch.object(qa, "get_pipeline_snapshot_files", new=AsyncMock(return_value=[])),
            ):
                await qa.run_qa_agent_node(ctx)
        return captured["system"]

    async def test_block_present_when_context_set(self) -> None:
        sys_prompt = await self._captured_system_prompt(_GOAL)
        # qa.md statically documents the marker, so key on the injected block+goal pair (unique to it).
        self.assertIn(f"{_QA_BLOCK}\n{_GOAL}", sys_prompt)

    async def test_block_absent_when_context_empty(self) -> None:
        sys_prompt = await self._captured_system_prompt("")
        self.assertNotIn(_GOAL, sys_prompt)  # the goal text only appears when actually injected


if __name__ == "__main__":
    unittest.main()
