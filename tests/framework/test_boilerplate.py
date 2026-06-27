"""Unit tests for the engine-curated baseline file appended to TASK-01 (the root-cause fix for the
TPM RECITATION block): the per-env .gitignore now comes from the engine, so the LLM never reproduces it.
The canonical Apache 2.0 LICENSE text (render_apache_license) is engine-curated too, but is written
deterministically by the Technical Writer node — no longer part of the TASK-01 baseline block."""
import unittest

from src.shared.core.boilerplate import (
    APACHE_LICENSE_TEMPLATE,
    DEFAULT_LICENSE_HOLDER,
    render_apache_license,
    build_gitignore_baseline_block,
)
from src.shared.core.environments import get_gitignore_template, GITIGNORE_TEMPLATES


class RenderApacheLicenseTests(unittest.TestCase):
    def test_fills_year_and_holder(self) -> None:
        text = render_apache_license("Ada Lovelace", "2026")
        self.assertIn("Apache License", text)
        self.assertIn("Version 2.0", text)
        self.assertIn("Copyright 2026 Ada Lovelace", text)

    def test_blank_holder_falls_back_to_default(self) -> None:
        self.assertIn(DEFAULT_LICENSE_HOLDER, render_apache_license("", "2026"))
        self.assertIn(DEFAULT_LICENSE_HOLDER, render_apache_license("   ", "2026"))

    def test_template_has_no_unfilled_slots_after_render(self) -> None:
        self.assertIn("{year}", APACHE_LICENSE_TEMPLATE)          # slots present in the template...
        rendered = render_apache_license("X", "2026")
        self.assertNotIn("{year}", rendered)                      # ...and gone after rendering
        self.assertNotIn("{holder}", rendered)


class BuildGitignoreBaselineBlockTests(unittest.TestCase):
    def test_contains_gitignore_for_env(self) -> None:
        env_id = "python-3.12-core"
        block = build_gitignore_baseline_block(env_id)
        self.assertIn("Repository Baseline Files (engine-provided", block)
        # The .gitignore content is the SSOT template from environments.py (not re-authored here).
        self.assertIn(get_gitignore_template(env_id).strip().splitlines()[0], block)
        self.assertIn("```gitignore", block)

    def test_license_is_not_in_the_baseline_block(self) -> None:
        # LICENSE moved out of the baseline block — the Technical Writer writes it deterministically.
        block = build_gitignore_baseline_block("python-3.12-core")
        self.assertNotIn("Apache License", block)
        self.assertNotIn("LICENSE", block)

    def test_unsupported_env_fails_fast(self) -> None:
        with self.assertRaises(ValueError):
            build_gitignore_baseline_block("rust-1.0-nope")

    def test_list_of_envs_combines_all_patterns(self) -> None:
        block = build_gitignore_baseline_block(["python-3.12-core", "node-22-web"])
        self.assertIn("__pycache__/", block)    # python patterns
        self.assertIn("node_modules/", block)   # node patterns
        self.assertIn("```gitignore", block)

    def test_list_with_single_env_matches_str_call(self) -> None:
        block_str = build_gitignore_baseline_block("python-3.12-core")
        block_list = build_gitignore_baseline_block(["python-3.12-core"])
        self.assertEqual(block_str, block_list)


if __name__ == "__main__":
    unittest.main()
