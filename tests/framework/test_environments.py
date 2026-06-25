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
    SUPPORTED_DEPLOY_TARGETS,
    QA_LANGUAGE_PROFILES,
    GITIGNORE_TEMPLATES,
    get_gitignore_template,
    all_source_extensions,
    extension_language_map,
    deploy_target_for_archetype,
    deploy_skill_for_target,
    deploy_target_skills,
    dependency_manifest,
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


class AuthoringContractTests(unittest.TestCase):
    """Every env declares an `authoring_contract` (prose the SA/TPM surface to the building agents) AND a
    `dependency_manifest` scalar (the engine SSOT the missing-manifest gate keys off). The two must not
    drift — the scalar's basename token must appear in a contract bullet — so the restore command and the
    authoring side can never silently disagree (the requirements.txt vs pyproject.toml halt class)."""

    def test_every_env_has_authoring_contract_and_manifest(self) -> None:
        for env_id, spec in SUPPORTED_ENVIRONMENTS.items():
            self.assertTrue(spec.get("authoring_contract"), env_id)        # non-empty bullet tuple
            self.assertTrue(spec.get("dependency_manifest"), env_id)       # non-empty manifest scalar

    def test_manifest_scalar_appears_in_contract_prose(self) -> None:
        # Drift guard: the engine SSOT (scalar) and the agent SSOT (prose) name the SAME manifest.
        for env_id, spec in SUPPORTED_ENVIRONMENTS.items():
            manifest = spec["dependency_manifest"]
            token = manifest.lstrip("*")  # `*.csproj` → `.csproj`
            blob = "\n".join(spec["authoring_contract"])
            self.assertIn(token, blob, f"{env_id}: manifest {manifest!r} not named in its authoring_contract")

    def test_python_manifest_is_requirements_txt_and_setup_cmd_restores_it(self) -> None:
        # Couples the restore SSOT to the authoring SSOT — the exact bug: the restore reads requirements.txt
        # while the agents authored only a pyproject.toml.
        self.assertEqual(dependency_manifest("python-3.12-core"), "requirements.txt")
        self.assertIn("requirements.txt", SUPPORTED_ENVIRONMENTS["python-3.12-core"]["setup_cmd"])

    def test_dependency_manifest_accessor_is_registry_driven(self) -> None:
        self.assertEqual(dependency_manifest("go-1.23-cli"), "go.mod")
        self.assertEqual(dependency_manifest("node-20-web"), "package.json")
        self.assertEqual(dependency_manifest("dotnet-10-sdk"), "*.csproj")
        # Unknown env / None → None (the missing-manifest gate then treats it as exempt, never a false fail).
        self.assertIsNone(dependency_manifest("no-such-env"))
        self.assertIsNone(dependency_manifest(None))


class DeployTargetRegistryTests(unittest.TestCase):
    """SUPPORTED_DEPLOY_TARGETS is the SSOT for WHERE an app deploys, mirroring SUPPORTED_ENVIRONMENTS.
    Pin its shape + the archetype→target / target→skill derivations so a new cloud is a registry entry
    + a deploy_<cloud>.md skill alone — no engine edit (engine stays deploy-target-agnostic)."""

    def test_every_target_has_the_required_shape(self) -> None:
        for target_id, spec in SUPPORTED_DEPLOY_TARGETS.items():
            self.assertTrue(spec.get("description"), target_id)
            self.assertTrue(spec.get("archetypes"), target_id)          # non-empty archetype tuple
            self.assertTrue(spec.get("skill"), target_id)               # names a platform skill
            self.assertTrue(spec.get("runtime_constraints"), target_id)  # non-empty constraint bullets

    def test_archetype_to_target_derivation(self) -> None:
        # Web archetypes resolve to the one cloud target; the CLI archetype to the release target.
        self.assertEqual(deploy_target_for_archetype("rest_api"), "gcp-cloud-run")
        self.assertEqual(deploy_target_for_archetype("crud_app"), "gcp-cloud-run")
        self.assertEqual(deploy_target_for_archetype("cli_tool"), "github-release")
        # Unknown / blank archetype → no target (the gate then skips the public-invoker check).
        self.assertIsNone(deploy_target_for_archetype("no-such-archetype"))
        self.assertIsNone(deploy_target_for_archetype(None))

    def test_archetype_partition_is_unambiguous(self) -> None:
        # No archetype is served by two targets (deploy_target_for_archetype's first-match is then exact).
        seen: dict[str, str] = {}
        for target_id, spec in SUPPORTED_DEPLOY_TARGETS.items():
            for arch in spec["archetypes"]:
                self.assertNotIn(arch, seen, f"{arch} served by both {seen.get(arch)} and {target_id}")
                seen[arch] = target_id

    def test_target_to_skill_and_skill_set(self) -> None:
        self.assertEqual(deploy_skill_for_target("gcp-cloud-run"), "deploy_gcp")
        self.assertEqual(deploy_skill_for_target("github-release"), "deploy_github_release")
        self.assertIsNone(deploy_skill_for_target("no-such-target"))
        self.assertIsNone(deploy_skill_for_target(None))
        # The skill set the DevOps node force-loads = every target's skill, deduped.
        self.assertEqual(set(deploy_target_skills()), {"deploy_gcp", "deploy_github_release"})

    def test_only_public_cloud_targets_require_invoker(self) -> None:
        # Cloud Run is public-facing (the 403-class fix); the GitHub-release target is not.
        self.assertTrue(SUPPORTED_DEPLOY_TARGETS["gcp-cloud-run"].get("requires_public_invoker"))
        self.assertFalse(SUPPORTED_DEPLOY_TARGETS["github-release"].get("requires_public_invoker"))

    def test_platform_skill_files_exist(self) -> None:
        # Every skill named in the registry must resolve to a real prompts/skills/<name>.md file.
        from src.shared.core.prompts import get_skill
        for name in deploy_target_skills():
            self.assertTrue(get_skill(name).strip(), name)


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
