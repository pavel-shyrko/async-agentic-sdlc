import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from src.core.prompts import (
    get_system_prompt,
    get_system_prompt_sections,
    get_skill,
    generate_repo_map,
)


class GetSystemPromptTests(unittest.TestCase):

    def setUp(self) -> None:
        get_system_prompt.cache_clear()
        get_skill.cache_clear()

    def test_loads_static_prompt(self) -> None:
        result = get_system_prompt("techlead")
        self.assertIn("Principal TechLead", result)

    def test_techlead_prompt_has_topology_rule(self) -> None:
        # SSOT: the TechLead must emit a language-neutral dependency graph.
        result = get_system_prompt("techlead")
        self.assertIn("TOPOLOGY RULE", result)
        self.assertIn("topology_contract", result)

    def test_qa_prompt_has_dependency_resolution_rule(self) -> None:
        # QA translates the neutral topology graph into language-specific imports.
        result = get_system_prompt("qa")
        self.assertIn("DEPENDENCY RESOLUTION RULE", result)
        self.assertIn("topology_contract", result)

    def test_qa_prompt_has_packaging_rule(self) -> None:
        # Guards against the import-guessing that breaks test collection and loops the pipeline.
        result = get_system_prompt("qa")
        self.assertIn("CRITICAL PACKAGING RULE", result)
        self.assertIn("never guess a path", result)

    def test_loads_template_with_placeholders(self) -> None:
        raw = get_system_prompt("developer")
        rendered = raw.format(
            instruction="Build X",
            function_signatures="def foo()",
            strict_type_validation_rules="bool is not int",
            code_dir="/tmp/code",
        )
        self.assertIn("Build X", rendered)
        self.assertIn("/tmp/code", rendered)

    def test_qa_prompt_splits_into_system_and_user(self) -> None:
        system, user_template = get_system_prompt_sections("qa")
        self.assertIn("automated QA engineer", system)
        self.assertIn("{module_dot}", user_template)

    def test_sections_raises_on_missing_separator(self) -> None:
        with mock.patch(
            "src.core.prompts.get_system_prompt", return_value="no separator here"
        ):
            with self.assertRaises(ValueError) as ctx:
                get_system_prompt_sections("qa")
        self.assertIn("qa", str(ctx.exception))

    def test_sections_raises_on_empty_section(self) -> None:
        with mock.patch(
            "src.core.prompts.get_system_prompt", return_value="system rules\n---\n   "
        ):
            with self.assertRaises(ValueError):
                get_system_prompt_sections("qa")

    def test_raises_on_missing_agent(self) -> None:
        with self.assertRaises(FileNotFoundError):
            get_system_prompt("nonexistent_agent_xyz")

    def test_caching_returns_same_object(self) -> None:
        first = get_system_prompt("reviewer")
        second = get_system_prompt("reviewer")
        self.assertIs(first, second)


class GetSkillTests(unittest.TestCase):

    def setUp(self) -> None:
        get_skill.cache_clear()

    def test_loads_strict_validation_skill(self) -> None:
        raw = get_skill("strict_validation")
        self.assertIn("CRITICAL RULE", raw)
        self.assertIn("{strict_type_validation_rules}", raw)

    def test_skill_template_renders(self) -> None:
        raw = get_skill("strict_validation")
        rendered = raw.format(strict_type_validation_rules="bool must raise TypeError")
        self.assertIn("bool must raise TypeError", rendered)
        self.assertNotIn("{strict_type_validation_rules}", rendered)

    def test_raises_on_missing_skill(self) -> None:
        with self.assertRaises(FileNotFoundError):
            get_skill("nonexistent_skill_xyz")

    def test_caching_returns_same_object(self) -> None:
        first = get_skill("strict_validation")
        second = get_skill("strict_validation")
        self.assertIs(first, second)


class GenerateRepoMapTests(unittest.TestCase):
    """Recursive tree walker prunes noise and gracefully handles a missing root."""

    def test_missing_dir_returns_empty(self) -> None:
        with TemporaryDirectory() as td:
            self.assertEqual(generate_repo_map(Path(td) / "nope"), "")

    def test_tree_includes_source_and_tests_prunes_noise(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "src" / "pkg").mkdir(parents=True)
            (root / "src" / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_mod.py").write_text("y = 2\n", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text("ref\n", encoding="utf-8")
            (root / "src" / "pkg" / "__pycache__").mkdir()
            (root / "src" / "pkg" / "__pycache__" / "mod.cpython.pyc").write_text(
                "junk", encoding="utf-8"
            )

            tree = generate_repo_map(root)

            self.assertIn("src/", tree)
            self.assertIn("pkg/", tree)
            self.assertIn("mod.py", tree)
            self.assertIn("tests/", tree)
            self.assertIn("test_mod.py", tree)
            self.assertNotIn(".git", tree)
            self.assertNotIn("__pycache__", tree)
            self.assertNotIn(".pyc", tree)

    def test_directories_sort_before_files(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "zdir").mkdir()
            (root / "zdir" / "deep.py").write_text("z = 0\n", encoding="utf-8")
            (root / "afile.py").write_text("a = 0\n", encoding="utf-8")

            tree = generate_repo_map(root)

            self.assertLess(tree.index("zdir/"), tree.index("afile.py"))


class PathResolutionTests(unittest.TestCase):
    """Verifies that _REPO_ROOT resolves correctly relative to the loader module."""

    def setUp(self) -> None:
        get_system_prompt.cache_clear()

    def test_system_dir_exists(self) -> None:
        from src.core.prompts import _SYSTEM_DIR
        self.assertTrue(_SYSTEM_DIR.is_dir(), f"{_SYSTEM_DIR} is not a directory")

    def test_skills_dir_exists(self) -> None:
        from src.core.prompts import _SKILLS_DIR
        self.assertTrue(_SKILLS_DIR.is_dir(), f"{_SKILLS_DIR} is not a directory")


if __name__ == "__main__":
    unittest.main()
