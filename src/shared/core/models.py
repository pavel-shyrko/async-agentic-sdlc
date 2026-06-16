import os
import re
from decimal import Decimal
from pathlib import Path
from pydantic import BaseModel, Field, field_validator

from src.shared.core.environments import SUPPORTED_ENVIRONMENTS

# ==========================================
# SESSION DIRECTORY STRUCTURE
# ==========================================
# Root for per-run, git-anchored sessions (runs/run_<uuid>/...). Env-overridable so
# tests and parallel orchestrators can relocate the session tree off the engine repo.
RUNS_BASE = Path(os.environ.get("PIPELINE_RUNS_BASE", "runs"))

class WorkspacePaths(BaseModel):
    # All paths are required — production resolves them via `for_run` (git-anchored under
    # RUNS_BASE); there is no implicit fallback tree.
    code_dir: Path
    tests_dir: Path
    logs_dir: Path
    reports_dir: Path
    repo_dir: Path  # git working-tree root; the snapshot builder runs `git ls-files` here

    def model_post_init(self, __context) -> None:
        for d in (self.code_dir, self.tests_dir, self.logs_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_run(cls, run_dir: Path, repo_dir: Path, src_dir: str, tests_dir: str) -> "WorkspacePaths":
        """Maps a git-anchored run onto absolute workspace paths.

        ``code_dir``/``tests_dir`` resolve inside the cloned repo; ``logs_dir``/``reports_dir``
        live under the run root (OUTSIDE the clone) to keep meta-state out of the target tree.

        A containment guard (analogous to ``_assert_within_root``) rejects any ``--src-dir`` /
        ``--tests-dir`` that escapes the repo via ``..`` traversal, so a hostile or fat-fingered
        argument cannot map the workspace onto the filesystem root.
        """
        repo_root = repo_dir.resolve()
        code_dir = (repo_root / src_dir).resolve()
        tests_dir_abs = (repo_root / tests_dir).resolve()
        for label, p in (("--src-dir", code_dir), ("--tests-dir", tests_dir_abs)):
            if p != repo_root and not p.is_relative_to(repo_root):
                raise ValueError(f"Path traversal blocked: {label} resolves outside repo ({p}).")
        run_root = run_dir.resolve()
        return cls(
            code_dir=code_dir,
            tests_dir=tests_dir_abs,
            logs_dir=run_root / "logs",
            reports_dir=run_root / "reports",
            repo_dir=repo_root,
        )

# ==========================================
# CONTRACTS & PIPELINE STATE
# ==========================================
class TopologyNode(BaseModel):
    file_path: str = Field(description="Repo-root-relative path of the source file.")
    exports: list[str] = Field(description="Symbols (functions/classes) this file publicly exports.")
    depends_on: list[str] = Field(
        default_factory=list,
        description="Language-neutral dependency links as 'path/to/file.ext:symbol'.",
    )

class TechLeadContract(BaseModel):
    files_to_modify: list[str] = Field(description="List of target source file paths.")
    topology_contract: list[TopologyNode] = Field(
        description="Language-neutral dependency graph: each contracted file, its exported symbols, "
        "and its dependency links. SSOT for downstream import resolution. No language syntax.",
    )
    instruction: str = Field(description="Technical directives for the Developer Agent.")
    architectural_constraints: list[str] = Field(
        default_factory=list,
        description="Architectural rules, patterns, and constraints extracted from the blueprint.")
    core_libraries: list[str] = Field(
        default_factory=list,
        description="Mandatory libraries and frameworks the implementation MUST use.")
    function_signatures: str = Field(description="Function names, arguments, types, and exceptions.")
    strict_type_validation_rules: str = Field(description="Type validation rules for the implementation.")
    techlead_reasoning: str = Field(description="Justification for the chosen design.")
    domain_tags: list[str] = Field(description="Up to 5 lowercase tags for the target tech stack/language AND business domain — e.g. 'python', 'dotnet', 'typescript', 'math', 'database'. The language tag acts as the dynamic skill router and MUST be declared first.", default_factory=list)
    environment_id: str = Field(..., description="The Paved-Road platform id (e.g. 'python-3.12-core') this ticket executes on, copied verbatim from the ticket/blueprint. MUST be one of the strictly supported environments.")

    @field_validator("environment_id")
    @classmethod
    def _validate_environment_id(cls, v: str) -> str:
        if v not in SUPPORTED_ENVIRONMENTS:
            raise ValueError(
                f"Unsupported environment_id '{v}'. "
                f"Choose one of: {sorted(SUPPORTED_ENVIRONMENTS)}."
            )
        return v

class AgentUsage(BaseModel):
    provider: str = "gemini"   # "gemini" (cost estimated) | "claude" (cost authoritative from CLI)
    input_tokens: int = 0      # fresh, uncached prompt tokens
    output_tokens: int = 0
    cache_read_tokens: int = 0   # cheap re-reads of a cached prompt (agentic CLI re-sends) — NOT budgeted
    cache_write_tokens: int = 0  # one-time cache population — NOT budgeted
    total_tokens: int = 0        # budgeted footprint: fresh input + output ONLY (cache excluded)
    cost_usd: Decimal = Decimal("0")
    calls: int = 0

class PipelineTelemetry(BaseModel):
    """Cumulative, checkpoint-persisted token/cost telemetry across all agent calls.

    ``total_tokens`` (the value the token Circuit Breaker reads) counts only the real new footprint —
    fresh input + output — and DELIBERATELY EXCLUDES cache read/write tokens: the agentic Claude CLI
    re-sends its prompt every internal turn, so cache reads would otherwise dominate the budget while
    costing ~10% of fresh input. Cache tokens are tracked separately for transparency. ``cost_usd``
    mixes Gemini (estimated from a price table) and Claude (authoritative, reported by the CLI) and is
    the money-accurate spend signal. Persisted in the context so both budgets survive ``--resume``.
    """
    total_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_write_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    by_agent: dict[str, AgentUsage] = Field(default_factory=dict)

    def record(self, agent: str, input_tokens: int, output_tokens: int,
               cost_usd: Decimal | float = Decimal("0"), provider: str = "gemini",
               cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> None:
        # Coerce at the boundary so float callers stay safe while precision is preserved exactly.
        cost = cost_usd if isinstance(cost_usd, Decimal) else Decimal(str(cost_usd))
        slot = self.by_agent.setdefault(agent, AgentUsage(provider=provider))
        slot.provider = provider
        # Budgeted total excludes cache — cache reads are cheap re-sends, not new spend footprint.
        budgeted = input_tokens + output_tokens
        slot.input_tokens += input_tokens
        slot.output_tokens += output_tokens
        slot.cache_read_tokens += cache_read_tokens
        slot.cache_write_tokens += cache_write_tokens
        slot.total_tokens += budgeted
        slot.cost_usd += cost
        slot.calls += 1
        self.total_tokens += budgeted
        self.total_cache_read_tokens += cache_read_tokens
        self.total_cache_write_tokens += cache_write_tokens
        self.total_cost_usd += cost

    def by_provider(self) -> dict[str, dict]:
        """Aggregate tokens + cost per provider (e.g. ``{"gemini": {...}, "claude": {...}}``)."""
        agg: dict[str, dict] = {}
        for usage in self.by_agent.values():
            slot = agg.setdefault(usage.provider, {"tokens": 0, "cost_usd": Decimal("0")})
            slot["tokens"] += usage.total_tokens
            slot["cost_usd"] += usage.cost_usd
        return agg

    def finops_report(self, budget_tokens: int, budget_usd: Decimal | float = Decimal("0")) -> dict:
        """Serializable FinOps summary: totals, budget utilisation, and per-provider/-agent breakdown.

        Reports the USD budget as the primary spend signal and the (cache-excluded) token budget as the
        secondary ceiling. Cache read/write totals are surfaced separately — the full footprint stays
        auditable even though it is not counted against the token budget.
        """
        budget_usd_dec = budget_usd if isinstance(budget_usd, Decimal) else Decimal(str(budget_usd))
        used_pct = round(100.0 * self.total_tokens / budget_tokens, 2) if budget_tokens else 0.0
        used_pct_usd = round(100.0 * float(self.total_cost_usd) / float(budget_usd_dec), 2) if budget_usd_dec else 0.0
        return {
            "total_cost_usd": round(self.total_cost_usd, 6),
            "budget_usd": round(budget_usd_dec, 6),
            "budget_used_pct_usd": used_pct_usd,
            "total_tokens": self.total_tokens,
            "budget_tokens": budget_tokens,
            "budget_used_pct": used_pct,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_cache_write_tokens": self.total_cache_write_tokens,
            "by_provider": self.by_provider(),
            "by_agent": {name: usage.model_dump() for name, usage in self.by_agent.items()},
        }

class SkillRelevance(BaseModel):
    score: float = Field(description="Semantic relevance score between 0.0 and 1.0")

class ArchitectureUpdate(BaseModel):
    updated_architecture_document: str = Field(
        description="The absolute, complete, updated content of docs/architecture_state.md markdown file, integrating new components, design decisions, and active constraints from the completed task."
    )

class QATestSuite(BaseModel):
    overwrite_existing: bool = Field(
        default=False,
        description="If True, completely discard the existing on-disk test suite file and build it fresh from new_imports and new_test_code. Use this to clear fatal top-level import or syntax errors from previous iterations.",
    )
    new_imports: str = Field(default="", description="New import statements to add, if any. Code only.")
    new_test_code: str = Field(description="Only the NEW test classes/functions. Code only.")
    obsolete_test_names: list[str] = Field(
        default_factory=list,
        description="Exact names of existing test classes or test_* functions that are now invalid and must be removed.",
    )
    files_to_delete: list[str] = Field(
        default_factory=list,
        description="Test file paths (relative to the tests dir) to delete wholesale — their target "
                    "production module was removed/renamed. Used for zombie-test disposal.",
    )

    @field_validator("new_imports", "new_test_code")
    @classmethod
    def clean_markdown_fences(cls, v: str) -> str:
        """Strip accidental markdown fences, language-neutral — the opening fence may carry ANY
        language tag (```python, ```go, ```csharp, ```typescript) or none."""
        v = re.sub(r"^```[A-Za-z0-9_+-]*\s*", "", v)
        v = re.sub(r"\s*```$", "", v)
        return v.strip()

class ReviewReport(BaseModel):
    code_quality_analysis: str = Field(description="Audit text for production code quality.")
    test_integrity_analysis: str = Field(description="Audit text for test integrity.")
    log_verification_analysis: str = Field(description="Analysis text for test runner and scanner output.")
    code_quality_approved: bool = Field(description="Boolean flag indicating production code approval status.")
    test_integrity_approved: bool = Field(description="Boolean flag indicating test integrity approval status.")
    qa_diagnostic_payload: str = Field(default="", description="Instructions ONLY for the QA Agent to fix incorrect, hallucinated, or broken tests.")
    dev_diagnostic_payload: str = Field(default="", description="Instructions ONLY for the Developer to fix production code bugs.")
    zombie_tests_to_delete: list[str] = Field(
        default_factory=list,
        description="List of specific obsolete or zombie test filenames that must be physically deleted from disk.",
    )

class GlobalPipelineContext(BaseModel):
    pr_description: str
    base_branch: str = "main"
    ticket: str = ""
    # Bound by the orchestrator via `WorkspacePaths.for_run` once the git-anchored session
    # exists; None until then. Every node accesses it only within a live run.
    workspace_paths: WorkspacePaths | None = None
    contract: TechLeadContract | None = None
    production_code_snapshot: dict[str, str] = Field(default_factory=dict)
    production_code_diff: str = ""
    test_code_snapshot: str = ""
    error_trace: str = ""           # Developer channel: production-code fix instructions only.
    qa_error_trace: str = ""        # QA channel: test-suite fix instructions only (isolated from Dev).
    review_report: ReviewReport | None = None
    current_attempt: int = 1
    repository_map: str = ""
    telemetry: PipelineTelemetry = Field(default_factory=PipelineTelemetry)

    def needs_test_regeneration(self) -> bool:
        """Whether QA must (re)generate tests before the next cycle.

        Recovers ephemeral regeneration intent from the last persisted review report so a
        rejected-tests checkpoint cannot bypass QA on resume: regenerate when the review
        rejected the test suite, or when no validated test snapshot exists yet.
        """
        if self.review_report and not self.review_report.test_integrity_approved:
            return True
        return not self.test_code_snapshot

    def save_checkpoint(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load_checkpoint(cls, path: Path) -> "GlobalPipelineContext":
        raw = path.read_text(encoding="utf-8")
        return cls.model_validate_json(raw)
