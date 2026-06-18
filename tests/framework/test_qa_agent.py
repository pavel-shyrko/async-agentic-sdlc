"""Unit tests for QA-agent deterministic helpers (zombie disposal, fence stripping, text
assembly) and the environment-aware test-target/filtering helpers."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

# qa imports src.shared.core.config at module import time.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.executor.agents import qa
from src.shared.core.models import QATestSuite
from src.shared.core.environments import is_testable_source, derive_test_target, is_test_file, get_qa_profile

# The Python test-name predicate, now supplied explicitly by callers (the engine default was removed).
_PY_TEST_NAME = qa._test_name_predicate("python-3.12-core")


class DisposeZombieTestsTests(unittest.TestCase):
    """``_dispose_zombie_tests`` deletes Reviewer-flagged test files, strictly sandboxed to tests_dir."""

    def test_deletes_named_test_file_inside_tests_dir(self) -> None:
        with TemporaryDirectory() as td:
            tests_dir = Path(td)
            zombie = tests_dir / "test_old_module.py"
            zombie.write_text("import gone", encoding="utf-8")

            qa._dispose_zombie_tests(tests_dir, {"test_old_module.py"}, name_ok=_PY_TEST_NAME)

            self.assertFalse(zombie.exists())

    def test_refuses_path_traversal_escape(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            outsider = root / "test_secret.py"  # a test_*.py, but OUTSIDE the tests dir
            outsider.write_text("keep me", encoding="utf-8")

            qa._dispose_zombie_tests(tests_dir, {"../test_secret.py"}, name_ok=_PY_TEST_NAME)

            self.assertTrue(outsider.exists())  # traversal rejected — protected file survives

    def test_refuses_non_test_file(self) -> None:
        with TemporaryDirectory() as td:
            tests_dir = Path(td)
            protected = tests_dir / "conftest.py"  # not a test_*.py
            protected.write_text("keep me", encoding="utf-8")

            qa._dispose_zombie_tests(tests_dir, {"conftest.py"}, name_ok=_PY_TEST_NAME)

            self.assertTrue(protected.exists())

    def test_missing_file_is_a_noop(self) -> None:
        with TemporaryDirectory() as td:
            # Names a file that does not exist — must not raise.
            qa._dispose_zombie_tests(Path(td), {"test_absent.py"}, name_ok=_PY_TEST_NAME)

    def test_colocated_go_zombie_disposed_via_profile_predicate(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            zombie = repo / "src" / "internal" / "converter" / "engine_test.go"
            zombie.parent.mkdir(parents=True)
            zombie.write_text("package converter", encoding="utf-8")

            qa._dispose_zombie_tests(
                repo, {"src/internal/converter/engine_test.go"},
                name_ok=qa._test_name_predicate("go-1.23-cli"),
            )

            self.assertFalse(zombie.exists())

    def test_go_predicate_rejects_non_go_test_file(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            keep = repo / "src" / "main.go"  # production file, not a *_test.go
            keep.parent.mkdir(parents=True)
            keep.write_text("package main", encoding="utf-8")

            qa._dispose_zombie_tests(repo, {"src/main.go"}, name_ok=qa._test_name_predicate("go-1.23-cli"))

            self.assertTrue(keep.exists())


class IsTestableSourceTests(unittest.TestCase):
    """Only real source files of the target stack are testable — never docs/config/markers."""

    def test_filters_non_code_artifacts_for_go(self) -> None:
        for non_source in ("README.md", "LICENSE", ".gitignore", "go.mod", "go.sum"):
            self.assertFalse(is_testable_source("go-1.23-cli", non_source), non_source)
        self.assertTrue(is_testable_source("go-1.23-cli", "src/internal/converter/engine.go"))

    def test_filters_package_markers_per_stack(self) -> None:
        self.assertFalse(is_testable_source("python-3.12-core", "src/__init__.py"))
        self.assertTrue(is_testable_source("python-3.12-core", "src/cmd/root.py"))
        self.assertFalse(is_testable_source("node-20-web", "package.json"))
        self.assertTrue(is_testable_source("node-20-web", "src/app.ts"))
        self.assertFalse(is_testable_source("dotnet-10-sdk", "App.csproj"))
        self.assertTrue(is_testable_source("dotnet-10-sdk", "src/Converter.cs"))


class IsTestFileTests(unittest.TestCase):
    """The shared test-file predicate recognizes each stack's convention (colocated or separate)."""

    def test_positives_per_language(self) -> None:
        self.assertTrue(is_test_file("go-1.23-cli", "src/internal/converter/converter_test.go"))
        self.assertTrue(is_test_file("python-3.12-core", "tests/test_converter.py"))
        self.assertTrue(is_test_file("node-20-web", "src/app.test.ts"))
        self.assertTrue(is_test_file("node-20-web", "src/app.spec.js"))
        self.assertTrue(is_test_file("dotnet-10-sdk", "src/ConverterTests.cs"))

    def test_negatives_are_production(self) -> None:
        self.assertFalse(is_test_file("go-1.23-cli", "src/internal/converter/converter.go"))
        self.assertFalse(is_test_file("python-3.12-core", "src/converter.py"))
        self.assertFalse(is_test_file("node-20-web", "src/app.ts"))
        self.assertFalse(is_test_file("dotnet-10-sdk", "src/Converter.cs"))


class DeriveTestTargetTests(unittest.TestCase):
    """Test file naming + placement is driven by the environment's language profile."""

    def test_python_separate_layout(self) -> None:
        path, ref = derive_test_target("python-3.12-core", "src/cmd/root.py")
        self.assertEqual(path, "test_src_cmd_root.py")   # separate tests/ dir, dotted ref
        self.assertEqual(ref, "src.cmd.root")

    def test_go_colocated_layout(self) -> None:
        path, ref = derive_test_target("go-1.23-cli", "src/internal/converter/engine.go")
        self.assertEqual(path, "src/internal/converter/engine_test.go")
        self.assertEqual(ref, "src/internal/converter/engine.go")

    def test_node_colocated_dot_test(self) -> None:
        path, _ = derive_test_target("node-20-web", "src/app.ts")
        self.assertEqual(path, "src/app.test.ts")

    def test_dotnet_colocated_tests_suffix(self) -> None:
        path, _ = derive_test_target("dotnet-10-sdk", "src/Converter.cs")
        self.assertEqual(path, "src/ConverterTests.cs")


class TestRootProfileTests(unittest.TestCase):
    """The QA language profile is the SSOT for the test root (replacing the removed --tests-dir flag):
    separate-layout (python) places tests under repo/<test_root>; colocated stacks have no root."""

    def test_python_separate_layout_has_tests_root(self) -> None:
        prof = get_qa_profile("python-3.12-core")
        self.assertEqual(prof["layout"], "separate")
        self.assertEqual(prof["test_root"], "tests")

    def test_colocated_stacks_have_no_test_root(self) -> None:
        for env in ("go-1.23-cli", "node-20-web", "dotnet-10-sdk"):
            prof = get_qa_profile(env)
            self.assertEqual(prof["layout"], "colocated")
            self.assertIsNone(prof["test_root"])


class StripFencesTests(unittest.TestCase):
    """Fence stripping is language-neutral — any opening language tag is removed."""

    def test_strips_go_and_csharp_fences(self) -> None:
        self.assertEqual(qa._strip_fences("```go\npackage x\n```"), "package x")
        self.assertEqual(qa._strip_fences("```csharp\nclass T {}\n```"), "class T {}")
        self.assertEqual(qa._strip_fences("```\nplain\n```"), "plain")


class EnvironmentProfileBlockTests(unittest.TestCase):
    """The TARGET ENVIRONMENT PROFILE block is PURE DATA — behavioral instructions live in qa.md."""

    def test_block_carries_registry_data_only(self) -> None:
        from src.shared.core.environments import get_qa_profile
        out = qa._environment_profile_block("python-3.12-core", get_qa_profile("python-3.12-core"))
        self.assertIn("=== TARGET ENVIRONMENT PROFILE ===", out)
        self.assertIn("environment_id: python-3.12-core", out)
        self.assertIn("language: python", out)
        self.assertIn("layout: separate", out)
        # No behavioral instructions may leak into the data block (those belong in qa.md/skills).
        for instruction in ("Generate tests using ONLY", "Write each test", "Return the COMPLETE", "overwrite_existing"):
            self.assertNotIn(instruction, out, instruction)


class AssembleSuiteTests(unittest.TestCase):
    """One language-neutral whole-file assembly path: join header+code, honor the empty-delta safety
    net. No per-language parsing/rewriting — correctness is the agent's job (skills + compile gate)."""

    def test_joins_imports_and_code_go(self) -> None:
        suite = QATestSuite(new_imports='package converter\n\nimport "testing"',
                            new_test_code="func TestA(t *testing.T){}")
        out = qa._assemble_suite("", suite)
        self.assertIn("package converter", out)
        self.assertIn("func TestA", out)

    def test_joins_imports_and_code_python(self) -> None:
        # Same code path as Go — proves language-neutrality (no ast.parse for Python anymore).
        suite = QATestSuite(new_imports="import unittest",
                            new_test_code="class T(unittest.TestCase):\n    def test_a(self): pass")
        out = qa._assemble_suite("", suite)
        self.assertIn("import unittest", out)
        self.assertIn("class T(unittest.TestCase)", out)

    def test_writes_model_content_verbatim_no_package_rewrite(self) -> None:
        # A wrong package is NOT silently corrected here — it flows to the compile gate → QA loop.
        suite = QATestSuite(new_imports="package converter", new_test_code="func TestX(t *testing.T){}",
                            overwrite_existing=True)
        out = qa._assemble_suite("package main\n", suite)
        self.assertTrue(out.startswith("package converter"))

    def test_empty_delta_keeps_existing_when_not_overwriting(self) -> None:
        suite = QATestSuite(new_imports="", new_test_code="")
        out = qa._assemble_suite("package converter\n", suite)
        self.assertEqual(out, "package converter\n")


if __name__ == "__main__":
    unittest.main()
