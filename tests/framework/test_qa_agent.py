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
from src.shared.core.environments import is_testable_source, derive_test_target, is_test_file


class DisposeZombieTestsTests(unittest.TestCase):
    """``_dispose_zombie_tests`` deletes Reviewer-flagged test files, strictly sandboxed to tests_dir."""

    def test_deletes_named_test_file_inside_tests_dir(self) -> None:
        with TemporaryDirectory() as td:
            tests_dir = Path(td)
            zombie = tests_dir / "test_old_module.py"
            zombie.write_text("import gone", encoding="utf-8")

            qa._dispose_zombie_tests(tests_dir, {"test_old_module.py"})

            self.assertFalse(zombie.exists())

    def test_refuses_path_traversal_escape(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            outsider = root / "test_secret.py"  # a test_*.py, but OUTSIDE the tests dir
            outsider.write_text("keep me", encoding="utf-8")

            qa._dispose_zombie_tests(tests_dir, {"../test_secret.py"})

            self.assertTrue(outsider.exists())  # traversal rejected — protected file survives

    def test_refuses_non_test_file(self) -> None:
        with TemporaryDirectory() as td:
            tests_dir = Path(td)
            protected = tests_dir / "conftest.py"  # not a test_*.py
            protected.write_text("keep me", encoding="utf-8")

            qa._dispose_zombie_tests(tests_dir, {"conftest.py"})

            self.assertTrue(protected.exists())

    def test_missing_file_is_a_noop(self) -> None:
        with TemporaryDirectory() as td:
            # Names a file that does not exist — must not raise.
            qa._dispose_zombie_tests(Path(td), {"test_absent.py"})

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


class StripFencesTests(unittest.TestCase):
    """Fence stripping is language-neutral — any opening language tag is removed."""

    def test_strips_go_and_csharp_fences(self) -> None:
        self.assertEqual(qa._strip_fences("```go\npackage x\n```"), "package x")
        self.assertEqual(qa._strip_fences("```csharp\nclass T {}\n```"), "class T {}")
        self.assertEqual(qa._strip_fences("```\nplain\n```"), "plain")


class EnsureGoPackageClauseTests(unittest.TestCase):
    """A Go test file must start with `package <pkg>`; the guard repairs missing/misplaced clauses."""

    def test_missing_clause_uses_sibling_package_from_snapshot(self) -> None:
        code = 'import (\n\t"testing"\n)\n\nfunc TestX(t *testing.T) {}\n'
        snap = {"internal/converter/processor.go": "package converter\n\nfunc Convert() {}\n"}
        out = qa._ensure_go_package_clause(code, "internal/converter/processor_test.go", snap)
        self.assertTrue(out.startswith("package converter\n"))
        self.assertIn('import (', out)

    def test_missing_clause_cmd_dir_defaults_to_main(self) -> None:
        code = 'import "testing"\n\nfunc TestMain(t *testing.T) {}\n'
        out = qa._ensure_go_package_clause(code, "cmd/json2csv/main_test.go", None)
        self.assertTrue(out.startswith("package main\n"))

    def test_missing_clause_no_snapshot_uses_dir_basename(self) -> None:
        code = 'import "testing"\n'
        out = qa._ensure_go_package_clause(code, "internal/cli/parser_test.go", None)
        self.assertTrue(out.startswith("package cli\n"))

    def test_misplaced_clause_is_hoisted_to_top(self) -> None:
        code = 'import (\n\t"testing"\n)\n\npackage converter\n\nfunc TestX(t *testing.T) {}\n'
        out = qa._ensure_go_package_clause(code, "internal/converter/processor_test.go", None)
        self.assertTrue(out.startswith("package converter\n"))
        self.assertEqual(out.count("package converter"), 1)  # moved, not duplicated

    def test_already_correct_is_unchanged(self) -> None:
        code = 'package converter\n\nimport "testing"\n\nfunc TestX(t *testing.T) {}\n'
        self.assertEqual(qa._ensure_go_package_clause(code, "internal/converter/processor_test.go", None), code)

    def test_leading_comment_before_package_is_allowed(self) -> None:
        code = '// Code generated by QA.\npackage converter\n\nimport "testing"\n'
        self.assertEqual(qa._ensure_go_package_clause(code, "internal/converter/processor_test.go", None), code)


class AssembleSuiteTextTests(unittest.TestCase):
    """Whole-file assembly for non-Python stacks joins imports+code and honors overwrite."""

    def test_joins_imports_and_code(self) -> None:
        suite = QATestSuite(new_imports="import \"testing\"", new_test_code="func TestA(t *testing.T){}")
        out = qa._assemble_suite_text("", suite)
        self.assertIn("import \"testing\"", out)
        self.assertIn("func TestA", out)

    def test_empty_delta_keeps_existing_when_not_overwriting(self) -> None:
        suite = QATestSuite(new_imports="", new_test_code="")
        out = qa._assemble_suite_text("package converter\n", suite)
        self.assertEqual(out, "package converter\n")


if __name__ == "__main__":
    unittest.main()
