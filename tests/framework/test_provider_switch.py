"""Unit tests for the MODEL_PROVIDER / --provider switch (force the whole pipeline onto one provider).

Covers the config resolver (alias normalization, override, structured-role + developer routing,
provider-aware env check), run_structured_llm routing, the DeveloperFileSet model, and the Gemini
Developer node's file materialization."""
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("GEMINI_API_KEY", "test-key")  # config builds the genai client at import

from src.shared.core import config
from src.shared.core.config import (
    normalize_provider, set_model_provider, active_provider, structured_role_routing,
    developer_provider, CLAUDE_CLI_MODEL,
    DEVELOPER_GEMINI_MODEL,
    PROVIDER_DEFAULT, PROVIDER_GEMINI, PROVIDER_CLAUDE,
)
from src.shared.core.models import DeveloperFileWrite, DeveloperFileSet


def _restore_default():
    set_model_provider(PROVIDER_DEFAULT)


class NormalizeProviderTests(unittest.TestCase):
    def test_aliases_map_to_canonical(self) -> None:
        for raw in ("api", "google", "gemini", "GEMINI", " Api "):
            self.assertEqual(normalize_provider(raw), PROVIDER_GEMINI)
        for raw in ("claude", "claude-code", "cli", "Claude", " CLI "):
            self.assertEqual(normalize_provider(raw), PROVIDER_CLAUDE)        # Claude Code CLI (no key)
        for raw in ("", None, "default", "mixed", "nonsense"):
            self.assertEqual(normalize_provider(raw), PROVIDER_DEFAULT)


class ActiveProviderOverrideTests(unittest.TestCase):
    def tearDown(self) -> None:
        _restore_default()

    def test_set_and_read(self) -> None:
        self.assertEqual(set_model_provider("api"), PROVIDER_GEMINI)
        self.assertEqual(active_provider(), PROVIDER_GEMINI)
        self.assertEqual(set_model_provider("claude"), PROVIDER_CLAUDE)
        self.assertEqual(active_provider(), PROVIDER_CLAUDE)

    def test_falsy_leaves_current_unchanged(self) -> None:
        set_model_provider("claude")
        self.assertEqual(set_model_provider(None), PROVIDER_CLAUDE)   # flag absent → keep current
        self.assertEqual(set_model_provider(""), PROVIDER_CLAUDE)


class StructuredRoleRoutingTests(unittest.TestCase):
    def tearDown(self) -> None:
        _restore_default()

    def test_default_and_gemini_use_role_gemini_model(self) -> None:
        gemini_model, label = config.ROLE_MODELS["tpm"]
        for prov in (PROVIDER_DEFAULT, "api"):
            set_model_provider(prov)
            model, lbl, provider = structured_role_routing("tpm")
            self.assertEqual((model, lbl, provider), (gemini_model, label, PROVIDER_GEMINI))

    def test_claude_provider_routes_every_role_to_the_cli(self) -> None:
        set_model_provider("claude")
        for role in config.ROLE_MODELS:
            model, _label, provider = structured_role_routing(role)
            self.assertEqual(model, CLAUDE_CLI_MODEL)
            self.assertEqual(provider, PROVIDER_CLAUDE)

    def test_developer_pseudo_role_is_always_gemini_emitter(self) -> None:
        # The "developer" structured role is the Gemini emitter — only reached on the gemini path.
        set_model_provider("api")
        model, label, provider = structured_role_routing("developer")
        self.assertEqual((model, label, provider), (DEVELOPER_GEMINI_MODEL, "Developer Agent", PROVIDER_GEMINI))


class DeveloperProviderTests(unittest.TestCase):
    def tearDown(self) -> None:
        _restore_default()

    def test_developer_backend_per_provider(self) -> None:
        set_model_provider("api")
        self.assertEqual(developer_provider(), PROVIDER_GEMINI)         # Gemini emitter
        for prov in (PROVIDER_DEFAULT, "claude"):
            set_model_provider(prov)
            self.assertEqual(developer_provider(), PROVIDER_CLAUDE)     # agentic Claude CLI


class CheckEnvironmentProviderTests(unittest.TestCase):
    """check_environment requires only the keys/binaries the active provider actually exercises."""
    def tearDown(self) -> None:
        _restore_default()

    def _run(self, env: dict, which_ok=("docker", "bandit", "claude", "gh")):
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(config.shutil, "which", side_effect=lambda t: t if t in which_ok else None):
            config.check_environment(require_forge=False)

    def test_claude_cli_provider_needs_no_api_key(self) -> None:
        set_model_provider("claude")
        # Claude Code CLI everywhere: needs only the `claude` binary — NO GEMINI_API_KEY, NO ANTHROPIC_API_KEY.
        self._run({})

    def test_claude_cli_provider_requires_claude_binary(self) -> None:
        set_model_provider("claude")
        with self.assertRaises(SystemExit):
            self._run({}, which_ok=("docker", "bandit"))               # `claude` missing → exit

    def test_gemini_provider_needs_no_claude_binary(self) -> None:
        set_model_provider("api")
        # Claude CLI absent is fine under gemini (Developer runs on Gemini).
        self._run({"GEMINI_API_KEY": "x"}, which_ok=("docker", "bandit"))

    def test_default_provider_needs_gemini_key_and_claude_binary(self) -> None:
        set_model_provider(PROVIDER_DEFAULT)
        self._run({"GEMINI_API_KEY": "x"})
        set_model_provider(PROVIDER_DEFAULT)
        with self.assertRaises(SystemExit):
            self._run({})                                              # missing GEMINI_API_KEY → exit


class DeveloperFileSetModelTests(unittest.TestCase):
    def test_leading_slash_normalized(self) -> None:
        self.assertEqual(DeveloperFileWrite(file_path="/src/main.py", content="x").file_path, "src/main.py")

    def test_traversal_rejected(self) -> None:
        with self.assertRaises(Exception):
            DeveloperFileWrite(file_path="../evil.py", content="x")

    def test_deletions_normalized(self) -> None:
        fs = DeveloperFileSet(files=[], files_to_delete=["/old.py"])
        self.assertEqual(fs.files_to_delete, ["old.py"])


class RunStructuredLlmRoutingTests(unittest.IsolatedAsyncioTestCase):
    """run_structured_llm uses the Gemini instructor_client (default/gemini) or the Claude Code CLI
    one-shot adapter (provider=claude)."""
    def tearDown(self) -> None:
        _restore_default()

    @staticmethod
    def _fake_client(captured: dict) -> SimpleNamespace:
        def _create(**kwargs):
            captured.update(kwargs)
            return (SimpleNamespace(ok=True), SimpleNamespace())
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create_with_completion=_create)))

    async def test_default_provider_uses_gemini_client_without_max_tokens(self) -> None:
        from src.shared.utils import llm
        set_model_provider(PROVIDER_DEFAULT)
        captured: dict = {}
        with mock.patch.object(llm, "instructor_client", self._fake_client(captured)):
            await llm.run_structured_llm("tpm", object, [{"role": "user", "content": "hi"}])
        self.assertNotIn("max_tokens", captured)
        self.assertEqual(captured["model"], config.ROLE_MODELS["tpm"][0])

    async def test_claude_cli_provider_uses_oneshot_adapter(self) -> None:
        from pydantic import BaseModel
        from src.shared.utils import llm

        class _Out(BaseModel):
            answer: str

        set_model_provider("claude")
        captured: dict = {}
        usage = {"input_tokens": 5, "output_tokens": 2, "cache_read_tokens": 0,
                 "cache_write_tokens": 0, "cost_usd": Decimal("0.01")}

        async def _fake_oneshot(prompt, model=None, json_schema=None, timeout=None, idle_timeout=None):
            captured.update(prompt=prompt, model=model, schema=json_schema)
            # structured=None → exercises the free-text fallback parse path.
            return ('Here you go: {"answer": "hi"} done', None, usage)

        with mock.patch.object(llm, "run_claude_cli_oneshot", new=_fake_oneshot), \
                mock.patch.object(llm, "instructor_client",
                                  SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
                                      create_with_completion=lambda **k: (_ for _ in ()).throw(
                                          AssertionError("instructor must not be used on the CLI path")))))):
            parsed, raw = await llm.run_structured_llm("tpm", _Out, [{"role": "user", "content": "hi"}])

        self.assertEqual(parsed.answer, "hi")                          # JSON extracted from free text + validated
        self.assertEqual(captured["model"], CLAUDE_CLI_MODEL)
        self.assertEqual(captured["schema"]["title"], "_Out")          # Pydantic schema forwarded to --json-schema
        self.assertEqual(raw.claude_cli_usage["cost_usd"], Decimal("0.01"))  # usage surfaced for telemetry
        self.assertIn("JSON Schema", captured["prompt"])               # schema embedded in the prompt (fallback)

    async def test_claude_cli_provider_uses_native_structured_output(self) -> None:
        from pydantic import BaseModel
        from src.shared.utils import llm

        class _Out(BaseModel):
            answer: str

        set_model_provider("claude")

        async def _fake_oneshot(prompt, model=None, json_schema=None, timeout=None, idle_timeout=None):
            # structured_output present (CLI --json-schema) → no text parsing needed.
            return ("", {"answer": "native"}, {"input_tokens": 1, "output_tokens": 1,
                    "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": Decimal("0.02")})

        with mock.patch.object(llm, "run_claude_cli_oneshot", new=_fake_oneshot):
            parsed, raw = await llm.run_structured_llm("tpm", _Out, [{"role": "user", "content": "hi"}])
        self.assertEqual(parsed.answer, "native")                      # validated from structured_output


class DeveloperGeminiNodeTests(unittest.IsolatedAsyncioTestCase):
    """The Gemini Developer path materializes the structured DeveloperFileSet under the repo sandbox."""
    async def test_writes_and_deletes_files(self) -> None:
        from src.development.agents import developer
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "stale.py").write_text("old", encoding="utf-8")
            file_set = DeveloperFileSet(
                files=[DeveloperFileWrite(file_path="src/app.py", content="print('hi')")],
                files_to_delete=["stale.py"],
            )
            ctx = SimpleNamespace(telemetry=SimpleNamespace())
            with mock.patch.object(developer, "run_structured_llm",
                                   new=mock.AsyncMock(return_value=(file_set, SimpleNamespace()))):
                await developer._run_developer_gemini(ctx, "prompt", repo)

            self.assertEqual((repo / "src" / "app.py").read_text(encoding="utf-8"), "print('hi')")
            self.assertFalse((repo / "stale.py").exists())


class ClaudeCliStructuredHelpersTests(unittest.TestCase):
    def test_extract_json_from_free_text(self) -> None:
        from src.shared.utils.llm import _extract_json_object
        self.assertEqual(_extract_json_object('Here: {"a": 1} thanks'), '{"a": 1}')

    def test_extract_json_from_fence(self) -> None:
        from src.shared.utils.llm import _extract_json_object
        self.assertEqual(_extract_json_object('```json\n{"a": 1}\n```'), '{"a": 1}')

    def test_full_assistant_text_concatenates_events(self) -> None:
        import json as _json
        from src.shared.utils.subprocess_helpers import _full_assistant_text
        lines = [
            _json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": '{"mark'}]}}),
            _json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": 'down": "hi"}'}]}}),
            _json.dumps({"type": "result", "result": "ignored-when-stream-present"}),
        ]
        self.assertEqual(_full_assistant_text(lines), '{"markdown": "hi"}')


if __name__ == "__main__":
    unittest.main()
