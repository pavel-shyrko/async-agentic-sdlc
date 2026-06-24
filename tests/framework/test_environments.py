"""Registry invariants for the Paved-Road environment table (SUPPORTED_ENVIRONMENTS)."""
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

# environments imports nothing network-bound, but keep the guard consistent with sibling suites.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.shared.core.environments import (
    SUPPORTED_ENVIRONMENTS,
    QA_LANGUAGE_PROFILES,
    GITIGNORE_TEMPLATES,
    get_gitignore_template,
    all_source_extensions,
    extension_language_map,
)


class RegistryDerivationTests(unittest.TestCase):
    """The engine must stay language-agnostic: extension- and language-keyed behaviour is DERIVED from the
    registry (SUPPORTED_ENVIRONMENTS / QA_LANGUAGE_PROFILES), never hardcoded in gate/agent logic. These
    pin that contract so a new language is added by a registry entry alone — no edit to the engine."""

    def test_all_source_extensions_is_the_dedup_union_of_profiles(self) -> None:
        expected = {ext for p in QA_LANGUAGE_PROFILES.values() for ext in p["source_exts"]}
        self.assertEqual(set(all_source_extensions()), expected)
        # Deduped (a tuple with no repeats) and ordered longest-first so `tsx` precedes `ts`.
        self.assertEqual(len(all_source_extensions()), len(set(all_source_extensions())))
        lengths = [len(e) for e in all_source_extensions()]
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_extension_language_map_covers_every_profile_extension(self) -> None:
        mapping = extension_language_map()
        for language_id, profile in QA_LANGUAGE_PROFILES.items():
            for ext in profile["source_exts"]:
                self.assertEqual(mapping[ext], language_id)
        # Spot-check the routing the TechLead depends on, including the multi-ext node stack.
        self.assertEqual(mapping[".cs"], "dotnet")
        self.assertEqual(mapping[".py"], "python")
        self.assertEqual({mapping[e] for e in (".ts", ".tsx", ".js", ".jsx")}, {"node"})


class FailureMarkerAndIgnoreDirTests(unittest.TestCase):
    """`failure_origin_markers` and `repo_map_ignore_dirs` are registry-derived per env, so the engine's
    feedback extractor and repo-map walker carry NO language. Pin the derivation + the generic fallbacks."""

    def test_failure_origin_markers_are_per_env_plus_generic_base(self) -> None:
        from src.shared.core.environments import failure_origin_markers
        dotnet = failure_origin_markers("dotnet-10-sdk")
        self.assertIn("error CS", dotnet)         # the stack-specific marker
        self.assertIn("ERROR:", dotnet)           # the generic base is always appended
        self.assertIn("FAILED", dotnet)
        # An unknown env still gets the generic base (never empty → never a blind tail-only slice).
        self.assertEqual(set(failure_origin_markers("no-such-env")), {"ERROR:", "FAILED"})

    def test_repo_map_ignore_dirs_env_specific_and_union(self) -> None:
        from src.shared.core.environments import repo_map_ignore_dirs
        self.assertIn("node_modules", repo_map_ignore_dirs("node-20-web"))
        self.assertIn("obj", repo_map_ignore_dirs("dotnet-10-sdk"))
        self.assertNotIn("node_modules", repo_map_ignore_dirs("dotnet-10-sdk"))  # env-specific, not global
        # No env id (the TechLead runs before the language is known) → the union across all stacks.
        union = repo_map_ignore_dirs()
        self.assertTrue({"node_modules", "obj", "__pycache__"} <= union, union)


class OrphanTestMarkerTests(unittest.TestCase):
    """The orphan-test backstop's per-stack signals live in the env registry (not in gates.py), so the
    gate logic carries no language. Pin their shape and the deliberate Go exemption."""

    def test_markers_are_lowercase_and_paired(self) -> None:
        # ran_zero_tests substring-matches a lowercased blob, so a marker with uppercase could never hit.
        for env_id, spec in SUPPORTED_ENVIRONMENTS.items():
            empty = spec.get("empty_test_markers")
            if empty is None:
                self.assertNotIn("ran_test_markers", spec, env_id)  # both-or-neither
                continue
            for m in empty + spec.get("ran_test_markers", ()):
                self.assertEqual(m, m.lower(), f"{env_id}: {m!r}")

    def test_go_is_exempt_dotnet_python_node_opt_in(self) -> None:
        self.assertNotIn("empty_test_markers", SUPPORTED_ENVIRONMENTS["go-1.23-cli"])
        for env_id in ("dotnet-10-sdk", "python-3.12-core", "node-20-web"):
            self.assertTrue(SUPPORTED_ENVIRONMENTS[env_id].get("empty_test_markers"), env_id)


class PythonTestCmdTests(unittest.TestCase):
    """The Python functional gate must invoke pytest via `python -m` so the sandbox cwd (/workspace)
    lands on sys.path[0] — otherwise topology imports like `from src.converter import …` raise
    `ModuleNotFoundError: No module named 'src'` (BACKLOG #15)."""

    def test_python_runs_pytest_as_module(self) -> None:
        test_cmd = SUPPORTED_ENVIRONMENTS["python-3.12-core"]["test_cmd"]
        self.assertEqual(test_cmd, "python -m pytest")
        # The bare console script would not put cwd on sys.path — guard against a regression to it.
        self.assertTrue(test_cmd.startswith("python -m "))


@unittest.skipIf(shutil.which("git") is None, "git not available")
class GitignoreTemplateTests(unittest.TestCase):
    """The canonical templates must never ignore a SOURCE directory that shares a name with the
    build artifact — the exact failure that looped a real run into the circuit breaker."""

    def _check_ignored(self, repo: Path, rel: str) -> bool:
        # `git check-ignore` exits 0 when the path IS ignored, 1 when it is not.
        return subprocess.run(
            ["git", "check-ignore", "-q", rel], cwd=str(repo)
        ).returncode == 0

    def test_every_env_resolves_to_a_template(self) -> None:
        for env_id in SUPPORTED_ENVIRONMENTS:
            self.assertTrue(get_gitignore_template(env_id).strip(), env_id)

    def test_source_dir_named_like_binary_is_not_ignored(self) -> None:
        # Regression: an unanchored `json2csv` once swallowed the cmd/json2csv/ source dir, so
        # `git add -A` dropped main.go from the snapshot. Assert NO template repeats that mistake.
        for env_id in SUPPORTED_ENVIRONMENTS:
            with TemporaryDirectory() as td, self.subTest(env=env_id):
                repo = Path(td)
                subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
                (repo / ".gitignore").write_text(get_gitignore_template(env_id), encoding="utf-8")
                src = repo / "cmd" / "json2csv"
                src.mkdir(parents=True)
                (src / "main.go").write_text("package main\n", encoding="utf-8")
                self.assertFalse(
                    self._check_ignored(repo, "cmd/json2csv/main.go"),
                    f"{env_id}: source file under cmd/json2csv/ is git-ignored by the template",
                )

    def test_go_ignores_binaries_by_extension_not_name(self) -> None:
        go = GITIGNORE_TEMPLATES["go"]
        self.assertIn("*.exe", go)
        self.assertIn("*.test", go)
        # A bare project-name line (unanchored, no glob/slash) is exactly the forbidden pattern.
        for line in go.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self.assertTrue(
                "/" in line or "*" in line or "." in line,
                f"suspicious unanchored bare pattern in go template: {line!r}",
            )


if __name__ == "__main__":
    unittest.main()
