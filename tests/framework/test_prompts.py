import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from src.shared.core.prompts import (
    get_system_prompt,
    get_system_prompt_sections,
    get_system_prompt_with_platforms,
    get_skill,
    generate_repo_map,
    build_agent_context,
)
from src.shared.core.models import GlobalPipelineContext, WorkspacePaths


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

    def test_techlead_prompt_topology_example_is_language_neutral(self) -> None:
        # The system prompt must NOT bias the stack — the topology example uses placeholders, not a
        # concrete language (language specifics belong in the gated *_core skills).
        result = get_system_prompt("techlead")
        self.assertIn("<ext>", result)                 # placeholder example, not a committed extension
        self.assertNotIn("validation.py", result)      # no Python-specific example paths
        self.assertNotIn('"Circle"', result)

    def test_tpm_folds_repo_prep_into_task01_no_standalone_task00(self) -> None:
        # Repo baseline is folded into TASK-01 as a mandatory leading block (no standalone TASK-00);
        # TASK-02+ are business-only. This removes the extra repo-prep iteration.
        result = get_system_prompt("tpm")
        self.assertIn("MANDATORY REPOSITORY PREPARATION RULE", result)
        self.assertIn("PRESENCE AND CURRENCY", result)
        self.assertIn("Repository Preparation (MANDATORY — do this FIRST)", result)
        self.assertIn("there is NO standalone `TASK-00`", result)
        # The old reserved-TASK-00 contract must be gone.
        self.assertNotIn("`TASK-00` is RESERVED", result)
        self.assertNotIn("BUSINESS TICKETS START AT `TASK-01`", result)

    def test_tpm_delegates_gitignore_and_license_to_engine(self) -> None:
        # The .gitignore/LICENSE are no longer reproduced by the TPM (reproducing canonical boilerplate
        # tripped Gemini's recitation filter) — the engine appends them at materialisation via
        # boilerplate.build_baseline_block. So no gitignore template is injected and the prompt forbids
        # the model from writing those two files' content itself.
        result = get_system_prompt_with_platforms("tpm")
        self.assertNotIn("{injected_gitignore_templates}", result)
        self.assertNotIn("```gitignore", result)           # no canonical gitignore blocks injected
        self.assertIn("ENGINE-PROVIDED", result)
        self.assertIn("Repository Baseline Files (engine-provided", result)

    def test_tpm_injects_readme_scaffold_and_env_commands(self) -> None:
        # README must follow the GitHub-aligned scaffold and pull accurate per-env commands; the
        # placeholders are filled and the old loose 3-bullet structure no longer drives it alone.
        result = get_system_prompt_with_platforms("tpm")
        self.assertNotIn("{injected_readme_scaffold}", result)
        self.assertNotIn("{injected_env_commands}", result)
        self.assertIn("## Getting Started", result)             # scaffold section injected
        self.assertIn("## Running Tests", result)
        self.assertIn("accurately reflect the essence", result)  # the project-fidelity hard gate
        self.assertIn("go build ./...", result)                 # real go env command injected
        self.assertIn("python -m pytest", result)               # real python env command injected

    def test_tpm_test_project_scaffold_is_build_glue_not_a_test_case(self) -> None:
        # The test-PROJECT scaffold (dir + build manifest) is Developer-owned build glue allocated to the
        # scaffolding ticket; only the test-CASE source files stay QA-owned and out of every ticket. This
        # is the fix for the dropped test project (QA's tests landed orphaned, never compiled/run).
        result = get_system_prompt("tpm")
        self.assertIn("TEST-PROJECT SCAFFOLD IS BUILD GLUE", result)
        self.assertIn("test-CASE source file", result)
        self.assertIn("KEEP the test-project manifest", result)

    def test_tpm_scaffold_ticket_ships_buildable_testable_skeleton(self) -> None:
        # TASK-01 must leave the repo buildable+testable (entry point for an executable + the test project),
        # never a config-only shell that strands the build into a reroute / zero-coverage merge.
        result = get_system_prompt("tpm")
        self.assertIn("BUILDABLE, TESTABLE SKELETON", result)
        self.assertIn("ENTRY POINT", result)

    def test_tpm_forbids_over_decomposition(self) -> None:
        # Atomicity must not become one-file-per-ticket for a trivial app (4 thin tickets = 4 build/merge
        # cycles). The prompt explicitly balances atomicity against over-splitting.
        result = get_system_prompt("tpm")
        self.assertIn("OVER-DECOMPOSITION", result)

    def test_sa_prompt_honors_user_mandated_stack(self) -> None:
        # An explicitly user-mandated language/platform must not be overridden by the architect.
        result = get_system_prompt("sa")
        self.assertIn("HONOR THE USER'S MANDATED STACK", result)
        self.assertIn("ORIGINAL USER REQUEST", result)

    def test_sa_topology_includes_test_scaffold_excludes_test_cases(self) -> None:
        # The File Topology must declare the test-PROJECT scaffold (build glue/architecture) but keep
        # individual test-CASE source files out (QA's exclusive domain). Reconciles the upgrade with the
        # QA-domain boundary; language-neutral.
        result = get_system_prompt("sa")
        self.assertIn("test-project scaffold", result)
        self.assertIn("test-CASE source files", result)
        self.assertIn("QA agent's exclusive domain", result)

    def test_techlead_prompt_scopes_contract_to_current_task(self) -> None:
        # The contract scope is the CURRENT TASK ticket, not the whole Blueprint (the SOLE router must
        # not implement the entire project topology when running one ticket).
        result = get_system_prompt("techlead")
        self.assertIn("CURRENT TASK SCOPE", result)
        self.assertIn("REFERENCE CONTEXT", result)
        self.assertIn("INFRA / NON-CODE TASK", result)

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

    def test_qa_prompt_has_identity_fidelity_and_thin_module(self) -> None:
        # Language-neutral correctness: test pkg/namespace matches the sibling; no foreign-pkg fabrication.
        result = get_system_prompt("qa")
        self.assertIn("TEST-FILE IDENTITY FIDELITY", result)
        self.assertIn("Thin / untestable module", result)

    def test_qa_prompt_carries_target_environment_instruction(self) -> None:
        # The native-framework/placement directive lives in the prompt (not hardcoded in qa.py),
        # and references the data block by name.
        result = get_system_prompt("qa")
        self.assertIn("TARGET ENVIRONMENT PROFILE", result)
        self.assertIn("native testing framework", result)

    def test_qa_prompt_has_whole_file_assembly(self) -> None:
        # Unified, language-neutral assembly — no delta/AST language remains.
        result = get_system_prompt("qa")
        self.assertIn("TEST FILE ASSEMBLY", result)
        self.assertNotIn("obsolete_test_names", result)

    def test_reviewer_prompt_routes_wrong_test_package_to_qa(self) -> None:
        # Closes the convergence gap: a wrong-package test is a QA defect, never the Developer's.
        result = get_system_prompt("reviewer")
        self.assertIn("WRONG TEST PACKAGE/NAMESPACE", result)

    def test_arbiter_prompt_has_routing_rubric_and_output_contract(self) -> None:
        # The Arbiter triages a stuck cycle into a route; the contract route must carry an amendment
        # directive and must not touch environment_id.
        result = get_system_prompt("arbiter")
        self.assertIn("ROUTING RUBRIC", result)
        self.assertIn("contract_conflict", result)
        self.assertIn("contract_amendment_directive", result)
        self.assertIn("environment_id", result)            # the pin rule is stated

    def test_techlead_prompt_has_error_precedence_and_amendment_mode(self) -> None:
        # Root-cause hardening: overlapping Raises need explicit precedence; amendment mode is documented.
        result = get_system_prompt("techlead")
        self.assertIn("ERROR PRECEDENCE", result)
        self.assertIn("AMENDMENT MODE", result)

    def test_reviewer_prompt_requires_constraint_respecting_repair(self) -> None:
        # A repair that fixes a gate by breaking a stated NFR is invalid — name the contract conflict.
        result = get_system_prompt("reviewer")
        self.assertIn("CONSTRAINT-RESPECTING REPAIR", result)

    def test_techlead_prompt_pins_behavioral_oracle(self) -> None:
        # The TechLead authors acceptance_examples — the behavioral oracle the suite and audit share.
        result = get_system_prompt("techlead")
        self.assertIn("acceptance_examples", result)
        self.assertIn("BEHAVIORAL ORACLE", result)

    def test_qa_prompt_pins_authoritative_examples_then_expand(self) -> None:
        # Hybrid: assert the contract's pinned examples verbatim, THEN expand with BVA (creative freedom).
        result = get_system_prompt("qa")
        self.assertIn("AUTHORITATIVE EXAMPLES FIRST", result)
        self.assertIn("ACCEPTANCE EXAMPLES", result)
        self.assertIn("Boundary Value Analysis", result)  # the expansion mandate survives

    def test_reviewer_prompt_adjudicates_against_the_oracle(self) -> None:
        # A test contradicting an acceptance example is a PRODUCTION bug; an altered example is a TEST bug.
        result = get_system_prompt("reviewer")
        self.assertIn("ACCEPTANCE-EXAMPLE ORACLE", result)

    def test_reviewer_prompt_requires_grounded_evidence(self) -> None:
        # BACKLOG #11: a production rejection must cite verbatim evidence, and a test-only failure defaults
        # the production verdict to approved — closing the phantom-defect reroute.
        result = get_system_prompt("reviewer")
        self.assertIn("GROUNDED EVIDENCE", result)
        self.assertIn("dev_evidence_citation", result)
        self.assertIn("TEST-ONLY FAILURE", result)

    def test_arbiter_prompt_routes_are_authoritative(self) -> None:
        # BACKLOG #25: the developer/qa route now authoritatively selects the feedback channel and
        # overrides a Reviewer misroute, so it must match the root_cause_class exactly.
        result = get_system_prompt("arbiter")
        self.assertIn("AUTHORITATIVE", result)

    def test_loads_template_with_placeholders(self) -> None:
        raw = get_system_prompt("developer")
        rendered = raw.format(
            instruction="Build X",
            core_libraries="- pydantic",
            architectural_constraints="- use DI",
            function_signatures="def foo()",
            strict_type_validation_rules="bool is not int",
            code_dir="/tmp/code",
        )
        self.assertIn("Build X", rendered)
        self.assertIn("/tmp/code", rendered)
        self.assertIn("pydantic", rendered)
        self.assertIn("use DI", rendered)

    def test_developer_prompt_has_scope_discipline_rule(self) -> None:
        # The Developer must be fenced to the contract — never implement another ticket's feature
        # logic just because the README/PROJECT CONTEXT mentions it — but a contracted build manifest
        # DOES authorize the minimal language-required entry point/glue it needs to compile.
        raw = get_system_prompt("developer")
        self.assertIn("SCOPE DISCIPLINE", raw)
        self.assertIn("OTHER tickets'", raw)
        self.assertIn("build manifest", raw)

    def test_qa_prompt_splits_into_system_and_user(self) -> None:
        system, user_template = get_system_prompt_sections("qa")
        self.assertIn("automated QA engineer", system)
        self.assertIn("{module_ref}", user_template)

    def test_sections_raises_on_missing_separator(self) -> None:
        with mock.patch(
            "src.shared.core.prompts.get_system_prompt", return_value="no separator here"
        ):
            with self.assertRaises(ValueError) as ctx:
                get_system_prompt_sections("qa")
        self.assertIn("qa", str(ctx.exception))

    def test_sections_raises_on_empty_section(self) -> None:
        with mock.patch(
            "src.shared.core.prompts.get_system_prompt", return_value="system rules\n---\n   "
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


class QASkillFidelityTests(unittest.TestCase):
    """The per-language QA skills carry concrete package/namespace/placement + thin-entrypoint rules."""

    def setUp(self) -> None:
        get_skill.cache_clear()

    def test_go_qa_forbids_foreign_package_in_entrypoint_test(self) -> None:
        raw = get_skill("go_qa")
        self.assertIn("colocated production sibling", raw)
        self.assertIn("package main", raw)

    def test_python_qa_has_placement_and_module_identity(self) -> None:
        raw = get_skill("python_qa")
        self.assertIn("File Placement & Module Identity", raw)
        self.assertIn("__main__", raw)

    def test_dotnet_qa_has_namespace_fidelity(self) -> None:
        raw = get_skill("dotnet_qa")
        self.assertIn("Namespace & Placement Fidelity", raw)


class DotnetLayoutMandateTests(unittest.TestCase):
    """The dotnet skills must mandate the canonical src/+tests/ layout (root holds ONLY the .sln) — the
    single fix for the MSB1011 / cross-globbed *Tests.cs / CS0579 reroute cascade a root-level .csproj
    triggers. The QA skill must NOT colocate the test source with the production type."""

    def setUp(self) -> None:
        get_skill.cache_clear()

    def test_core_mandates_subdir_layout_root_holds_only_sln(self) -> None:
        raw = get_skill("dotnet_core")
        self.assertIn("root holds ONLY the .sln", raw)
        self.assertIn("NEVER place a `.csproj` at the repository root", raw)
        self.assertIn("src/<Project>/<Project>.csproj", raw)
        self.assertIn("tests/<Project>.Tests/", raw)

    def test_core_names_the_three_root_csproj_footguns(self) -> None:
        raw = get_skill("dotnet_core")
        for marker in ("MSB1011", "CS0579", "InternalsVisibleTo"):
            self.assertIn(marker, raw, marker)

    def test_qa_does_not_colocate_test_with_production(self) -> None:
        raw = get_skill("dotnet_qa")
        # The exact phrasing that put `Models/CliOptionsTests.cs` into the production tree (run 003).
        self.assertNotIn("colocated with the type under test", raw)
        self.assertIn("INSIDE the test project directory", raw)
        self.assertIn("InternalsVisibleTo", raw)

    def test_core_scaffold_ticket_contracts_entry_point_and_test_project(self) -> None:
        # The scaffold/init ticket must ship a buildable+testable skeleton in ONE contract — the Exe entry
        # point AND the test project — never a config-only shell (the CS5001-reroute + orphaned-tests bug).
        raw = get_skill("dotnet_core")
        self.assertIn("buildable+testable skeleton ships in ONE ticket", raw)
        self.assertIn("do not create C# source code files", raw)   # the anti-pattern it forbids
        self.assertIn("Test project skeleton", raw)


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

    def test_prunes_build_and_dependency_dirs_registry_driven(self) -> None:
        # The prune set is registry-derived (repo_map_ignore_dirs union) — a fresh clone's build/dependency
        # output (node_modules/bin/obj/dist) must NOT bloat the topology map for any stack, not just Python.
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "src" / "app.ts").write_text("export const x = 1\n", encoding="utf-8")
            for noise in ("node_modules", "bin", "obj", "dist"):
                (root / noise).mkdir()
                (root / noise / "junk.txt").write_text("junk", encoding="utf-8")

            tree = generate_repo_map(root)

            self.assertIn("src/", tree)
            self.assertIn("app.ts", tree)
            for noise in ("node_modules", "bin", "obj", "dist"):
                self.assertNotIn(f"{noise}/", tree)

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
        from src.shared.core.prompts import _SYSTEM_DIR
        self.assertTrue(_SYSTEM_DIR.is_dir(), f"{_SYSTEM_DIR} is not a directory")

    def test_skills_dir_exists(self) -> None:
        from src.shared.core.prompts import _SKILLS_DIR
        self.assertTrue(_SKILLS_DIR.is_dir(), f"{_SKILLS_DIR} is not a directory")


class BuildAgentContextADRTests(unittest.IsolatedAsyncioTestCase):
    """The living ADR is injected into every consuming node, with first-iteration safety.

    Uses ``techwriter`` as the node name: no skill targets it, so the skill loop is a no-op and the
    only output is the ADR block — keeping the assertion hermetic (no domain LLM fallback fires).
    """

    @staticmethod
    def _ctx(repo: Path) -> GlobalPipelineContext:
        paths = WorkspacePaths(
            logs_dir=repo / "logs", reports_dir=repo / "reports", repo_dir=repo,
        )
        return GlobalPipelineContext(pr_description="t", base_branch="main", workspace_paths=paths)

    async def test_injects_on_disk_document_when_present(self) -> None:
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "docs").mkdir()
            (repo / "docs" / "architecture_state.md").write_text(
                "# State\nStreaming invariant: row-by-row.", encoding="utf-8")
            out = await build_agent_context("techwriter", self._ctx(repo))
            self.assertIn("LIVING ARCHITECTURE DOCUMENT", out)
            self.assertIn("row-by-row", out)

    async def test_injects_placeholder_on_first_iteration(self) -> None:
        # GUARD: the document does not exist yet — must NOT raise, must feed the placeholder.
        with TemporaryDirectory() as td:
            out = await build_agent_context("techwriter", self._ctx(Path(td)))
            self.assertIn("LIVING ARCHITECTURE DOCUMENT", out)
            self.assertIn("first iteration", out)

    async def test_skips_injection_when_workspace_unbound(self) -> None:
        out = await build_agent_context("techwriter", GlobalPipelineContext(pr_description="t"))
        self.assertNotIn("LIVING ARCHITECTURE DOCUMENT", out)


class ArbiterTriageSkillTests(unittest.IsolatedAsyncioTestCase):
    """The arbiter node now receives a global `arbiter_triage` skill via build_agent_context('arbiter',…)
    — arbiter.py already calls it — giving the failure triager the build-glue / contract-gap routing
    guardrails WITHOUT touching the off-limits arbiter system prompt. Hermetic: no skill is `domain` for
    arbiter, so no LLM relevance fallback fires; no workspace, so the ADR block is skipped."""

    async def test_arbiter_node_receives_triage_skill(self) -> None:
        out = await build_agent_context("arbiter", GlobalPipelineContext(pr_description="t"))
        self.assertIn("ARBITER TRIAGE GUARDRAILS", out)
        self.assertIn("Build glue is legitimate", out)         # entrypoint/glue is not a scope violation
        self.assertIn("CONTRACT gap", out)                     # missing required-to-build file → contract route


class PerLanguageCoreRoutingTests(unittest.IsolatedAsyncioTestCase):
    """Each language's `*_core` skill gates into the techlead/developer/reviewer nodes by domain tag,
    and the other languages' cores stay out. The LLM relevance fallback is mocked to False so a tag
    miss deterministically excludes a domain skill (no network)."""

    _MARKERS = {
        "go": "LANGUAGE TARGET: Go",
        "node": "LANGUAGE TARGET: Node",
        "dotnet": "LANGUAGE TARGET: .NET",
        "python": "LANGUAGE TARGET: Python",
    }
    # Topology skills targeting a node are `.format()`-ed, so supply their placeholders.
    _TOPO = {"techlead": {}, "developer": {"code_dir": "/repo"}, "reviewer": {}}

    def setUp(self) -> None:
        get_skill.cache_clear()

    async def _context(self, node: str, tag: str) -> str:
        ctx = GlobalPipelineContext(pr_description="t")  # no workspace_paths -> ADR block skipped
        with mock.patch(
            "src.shared.core.prompts.fallback_semantic_search",
            new=mock.AsyncMock(return_value=False),
        ):
            return await build_agent_context(
                node, ctx, inferred_tags=[tag], topology_kwargs=self._TOPO[node]
            )

    async def test_core_skill_routes_into_each_node_and_others_excluded(self) -> None:
        for node in ("techlead", "developer", "reviewer"):
            for tag, marker in self._MARKERS.items():
                out = await self._context(node, tag)
                self.assertIn(marker, out, f"{tag}_core missing for node {node!r}")
                for other_tag, other_marker in self._MARKERS.items():
                    if other_tag != tag:
                        self.assertNotIn(
                            other_marker, out,
                            f"{other_tag}_core leaked into node {node!r} routed for {tag!r}",
                        )


class DeveloperPathRuleOwnershipTests(unittest.IsolatedAsyncioTestCase):
    """The pathing rule has a SINGLE owner: developer_topology renders it (with {code_dir} substituted),
    and the developer system prompt no longer carries a duplicate PATH ROUTING bullet."""

    def setUp(self) -> None:
        get_skill.cache_clear()

    async def test_topology_skill_renders_path_rule_with_code_dir(self) -> None:
        ctx = GlobalPipelineContext(pr_description="t")  # no workspace_paths -> ADR block skipped
        with mock.patch(
            "src.shared.core.prompts.fallback_semantic_search",
            new=mock.AsyncMock(return_value=False),
        ):
            out = await build_agent_context("developer", ctx, topology_kwargs={"code_dir": "/repo"})
        self.assertIn("CRITICAL PATHING RULE", out)
        self.assertIn("/repo", out)                 # {code_dir} substituted by the topology formatter
        self.assertIn("TOPOLOGY CONTRACT", out)      # rule anchors to the injected block

    def test_system_prompt_no_longer_owns_path_routing(self) -> None:
        raw = get_system_prompt("developer")
        self.assertNotIn("PATH ROUTING", raw)        # re-homed to developer_topology (single owner)


class PerLanguageCoreFrontmatterTests(unittest.TestCase):
    """The new core skills are well-formed and target all three production nodes."""

    def setUp(self) -> None:
        get_skill.cache_clear()

    def test_new_core_skills_target_three_nodes(self) -> None:
        from src.shared.core.prompts import _parse_frontmatter, _SKILLS_DIR
        for skill_id in ("go_core", "node_core", "dotnet_core"):
            meta, body = _parse_frontmatter((_SKILLS_DIR / f"{skill_id}.md").read_text(encoding="utf-8"))
            self.assertEqual(meta.get("type"), "domain", skill_id)
            self.assertEqual(set(meta.get("nodes", [])), {"techlead", "developer", "reviewer"}, skill_id)
            self.assertTrue(meta.get("triggers"), skill_id)
            self.assertIn("LANGUAGE TARGET", body, skill_id)


class DevOpsPromptTests(unittest.TestCase):
    """E4: the devops system prompt carries the archetype-branching + WIF hard rules, and the three
    archetype skills are well-formed and target the devops node."""

    def setUp(self) -> None:
        get_system_prompt.cache_clear()
        get_skill.cache_clear()

    def test_system_prompt_has_archetype_branching_and_wif_rules(self) -> None:
        raw = get_system_prompt("devops")
        self.assertIn("Workload Identity Federation", raw)
        self.assertIn("Cloud Run", raw)
        # CLI/library must NOT get a Dockerfile / Cloud Run deploy (the audit's #3 — in the prompt itself).
        self.assertIn("NO Dockerfile and NO Cloud Run deploy step", raw)

    def test_archetype_skills_target_devops_node(self) -> None:
        from src.shared.core.prompts import _parse_frontmatter, _SKILLS_DIR
        expected = {"devops_rest_api": "api", "devops_crud_app": "crud", "devops_cli_tool": "cli"}
        for skill_id, trigger in expected.items():
            meta, body = _parse_frontmatter((_SKILLS_DIR / f"{skill_id}.md").read_text(encoding="utf-8"))
            self.assertEqual(meta.get("type"), "domain", skill_id)
            self.assertEqual(meta.get("nodes"), ["devops"], skill_id)
            self.assertEqual(meta.get("triggers"), [trigger], skill_id)
            self.assertTrue(body.strip(), skill_id)

    def test_secrets_vs_variables_split_matches_devops_setup_guide(self) -> None:
        # Contract (docs/guides/devops_setup.md): WIF_PROVIDER/SERVICE_ACCOUNT are SECRETS;
        # PROJECT_ID/REGION/REGISTRY_NAME are VARIABLES. The generated workflow must reference them
        # accordingly or the deploy can't resolve. Pin both the rest_api skill and the system prompt.
        rest = get_skill("devops_rest_api")
        self.assertIn("secrets.GCP_WIF_PROVIDER", rest)
        self.assertIn("vars.GCP_PROJECT_ID", rest)
        self.assertIn("vars.GCP_REGION", rest)
        self.assertNotIn("secrets.GCP_PROJECT_ID", rest)   # the bug this fixes
        self.assertNotIn("secrets.GCP_REGION", rest)
        prompt = get_system_prompt("devops")
        self.assertIn("${{ secrets.* }}", prompt)
        self.assertIn("${{ vars.* }}", prompt)

    def test_devops_prompt_mandates_canonical_commands_no_invented_linters(self) -> None:
        # The lint-gate epic's CI SSOT: the generated CI must run the project's canonical commands and
        # must NOT invent stricter gates (the cause of the red `ruff check` CI). Pin the rule in the
        # system prompt and the CLI skill (the archetype whose workflow runs test/lint steps).
        prompt = get_system_prompt("devops")
        self.assertIn("CANONICAL", prompt)
        self.assertIn("do not invent it", prompt)
        cli = get_skill("devops_cli_tool")
        self.assertIn("canonical project commands", cli)
        self.assertIn("lint_cmd", cli)


if __name__ == "__main__":
    unittest.main()
