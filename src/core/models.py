import os
import re
from decimal import Decimal
from pathlib import Path
from pydantic import BaseModel, Field, field_validator

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
    function_signatures: str = Field(description="Function names, arguments, types, and exceptions.")
    strict_type_validation_rules: str = Field(description="Type validation rules for the implementation.")
    techlead_reasoning: str = Field(description="Justification for the chosen design.")
    domain_tags: list[str] = Field(description="Up to 5 lowercase tags for the target tech stack/language AND business domain — e.g. 'python', 'dotnet', 'typescript', 'math', 'database'. The language tag acts as the dynamic skill router and MUST be declared first.", default_factory=list)

class AgentUsage(BaseModel):
    provider: str = "gemini"   # "gemini" (cost estimated) | "claude" (cost authoritative from CLI)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    calls: int = 0

class PipelineTelemetry(BaseModel):
    """Cumulative, checkpoint-persisted token/cost telemetry across all agent calls.

    The token total feeds the Financial Circuit Breaker; ``cost_usd`` mixes Gemini (estimated from
    a price table) and Claude (authoritative, reported by the CLI). Persisted in the context so the
    budget survives ``--resume`` exactly like the functional Circuit Breaker's ``current_attempt``.
    """
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    by_agent: dict[str, AgentUsage] = Field(default_factory=dict)

    def record(self, agent: str, input_tokens: int, output_tokens: int,
               cost_usd: Decimal | float = Decimal("0"), provider: str = "gemini") -> None:
        # Coerce at the boundary so float callers stay safe while precision is preserved exactly.
        cost = cost_usd if isinstance(cost_usd, Decimal) else Decimal(str(cost_usd))
        slot = self.by_agent.setdefault(agent, AgentUsage(provider=provider))
        slot.provider = provider
        added = input_tokens + output_tokens
        slot.input_tokens += input_tokens
        slot.output_tokens += output_tokens
        slot.total_tokens += added
        slot.cost_usd += cost
        slot.calls += 1
        self.total_tokens += added
        self.total_cost_usd += cost

    def by_provider(self) -> dict[str, dict]:
        """Aggregate tokens + cost per provider (e.g. ``{"gemini": {...}, "claude": {...}}``)."""
        agg: dict[str, dict] = {}
        for usage in self.by_agent.values():
            slot = agg.setdefault(usage.provider, {"tokens": 0, "cost_usd": Decimal("0")})
            slot["tokens"] += usage.total_tokens
            slot["cost_usd"] += usage.cost_usd
        return agg

    def finops_report(self, budget_tokens: int) -> dict:
        """Serializable FinOps summary: totals, budget utilisation, and per-provider/-agent breakdown."""
        used_pct = round(100.0 * self.total_tokens / budget_tokens, 2) if budget_tokens else 0.0
        return {
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "budget_tokens": budget_tokens,
            "budget_used_pct": used_pct,
            "by_provider": self.by_provider(),
            "by_agent": {name: usage.model_dump() for name, usage in self.by_agent.items()},
        }

class SkillRelevance(BaseModel):
    score: float = Field(description="Semantic relevance score between 0.0 and 1.0")

class QATestSuite(BaseModel):
    test_code: str = Field(description="Raw Python code only.")

    @field_validator("test_code")
    @classmethod
    def clean_markdown_fences(cls, v: str) -> str:
        """Ensures generated code is cleaned from accidental markdown fences."""
        v = re.sub(r"^```python\s*", "", v, flags=re.IGNORECASE)
        v = re.sub(r"^```\s*", "", v)
        v = re.sub(r"\s*```$", "", v)
        return v.strip()

class ReviewReport(BaseModel):
    code_quality_analysis: str = Field(description="Audit text for production code quality.")
    test_integrity_analysis: str = Field(description="Audit text for test integrity.")
    log_verification_analysis: str = Field(description="Analysis text for test runner and scanner output.")
    code_quality_approved: bool = Field(description="Boolean flag indicating production code approval status.")
    test_integrity_approved: bool = Field(description="Boolean flag indicating test integrity approval status.")
    diagnostic_payload: str = Field(description="Fix instructions returned on rejection.")

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
    error_trace: str = ""
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
