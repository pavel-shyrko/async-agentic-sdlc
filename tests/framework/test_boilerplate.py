"""Unit tests for the engine-curated baseline files appended to TASK-01 (the root-cause fix for the
TPM RECITATION block): the canonical MIT LICENSE + per-env .gitignore now come from the engine, so the
LLM never reproduces them."""
import unittest

from src.shared.core.boilerplate import (
    MIT_LICENSE_TEMPLATE,
    DEFAULT_LICENSE_HOLDER,
    render_mit_license,
    build_baseline_block,
)
from src.shared.core.environments import get_gitignore_template


class RenderMitLicenseTests(unittest.TestCase):
    def test_fills_year_and_holder(self) -> None:
        text = render_mit_license("Ada Lovelace", "2026")
        self.assertIn("MIT License", text)
        self.assertIn("Permission is hereby granted", text)   # full canonical body
        self.assertIn("Copyright (c) 2026 Ada Lovelace", text)

    def test_blank_holder_falls_back_to_default(self) -> None:
        self.assertIn(DEFAULT_LICENSE_HOLDER, render_mit_license("", "2026"))
        self.assertIn(DEFAULT_LICENSE_HOLDER, render_mit_license("   ", "2026"))

    def test_template_has_no_unfilled_slots_after_render(self) -> None:
        self.assertIn("{year}", MIT_LICENSE_TEMPLATE)          # slots present in the template...
        rendered = render_mit_license("X", "2026")
        self.assertNotIn("{year}", rendered)                   # ...and gone after rendering
        self.assertNotIn("{holder}", rendered)


class BuildBaselineBlockTests(unittest.TestCase):
    def test_contains_gitignore_and_license_for_env(self) -> None:
        env_id = "python-3.12-core"
        block = build_baseline_block(env_id, holder="Acme", year="2026")
        self.assertIn("Repository Baseline Files (engine-provided", block)
        self.assertIn("Permission is hereby granted", block)               # MIT body
        self.assertIn("Copyright (c) 2026 Acme", block)
        # The .gitignore content is the SSOT template from environments.py (not re-authored here).
        self.assertIn(get_gitignore_template(env_id).strip().splitlines()[0], block)
        self.assertIn("```gitignore", block)

    def test_unsupported_env_fails_fast(self) -> None:
        with self.assertRaises(ValueError):
            build_baseline_block("rust-1.0-nope")


if __name__ == "__main__":
    unittest.main()
