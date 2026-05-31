import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from src.core.prompts import get_system_prompt, get_skill


class GetSystemPromptTests(unittest.TestCase):

    def setUp(self) -> None:
        get_system_prompt.cache_clear()
        get_skill.cache_clear()

    def test_loads_static_prompt(self) -> None:
        result = get_system_prompt("architect")
        self.assertIn("Principal Architect", result)

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
        raw = get_system_prompt("qa")
        parts = raw.split("\n---\n", 1)
        self.assertEqual(len(parts), 2)
        self.assertIn("automated QA engineer", parts[0])
        self.assertIn("{module_dot}", parts[1])

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
