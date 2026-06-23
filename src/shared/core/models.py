import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Literal
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
    # RUNS_BASE); there is no implicit fallback tree. The source/test layout INSIDE the clone is
    # NOT fixed here: the Developer writes by the contract's full repo-relative paths and the QA
    # node places tests via its language profile, so only the repo root + run meta-dirs are tracked.
    logs_dir: Path
    reports_dir: Path
    repo_dir: Path  # git working-tree root; the snapshot builder runs `git ls-files` here

    def model_post_init(self, __context) -> None:
        # Only the run meta-dirs are pre-created — NEVER source/test dirs inside the clone (their
        # layout is contract-/profile-driven, so pre-creating `src/`/`tests/` just leaves empties).
        for d in (self.logs_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_run(cls, run_dir: Path, repo_dir: Path) -> "WorkspacePaths":
        """Maps a git-anchored run onto absolute workspace paths.

        ``logs_dir``/``reports_dir`` live under the run root (OUTSIDE the clone) to keep meta-state
        out of the target tree; ``repo_dir`` is the clone's working-tree root.
        """
        run_root = run_dir.resolve()
        return cls(
            logs_dir=run_root / "logs",
            reports_dir=run_root / "reports",
            repo_dir=repo_dir.resolve(),
        )

# ==========================================
# CONTRACTS & PIPELINE STATE
# ==========================================
def normalize_repo_rel_path(raw: str) -> str:
    """Coerce a contract/topology path to a clean, repo-root-relative POSIX path.

    The SA/TPM blueprint topology writes paths with a LEADING SLASH (e.g. `/cmd/app/main.go`,
    `/.gitignore`), so the TechLead copies them into the contract verbatim. `repo_dir / "/.gitignore"`
    is ABSOLUTE under pathlib semantics — the leading slash discards the repo root — which both
    escapes the write sandbox (`_assert_within_root` blocks it) and makes the file read as perpetually
    "missing" (`(repo_dir / f).exists()` checks `/.gitignore`). Stripping the anchor here, at the
    contract boundary, fixes every downstream consumer at once. Backslashes are POSIX-normalised and
    genuine `..` traversal is rejected (a contract must never point outside the clone).
    """
    p = raw.replace("\\", "/").strip()
    parts = [seg for seg in p.lstrip("/").split("/") if seg not in ("", ".")]
    if ".." in parts:
        raise ValueError(f"Contract path escapes the repo sandbox: {raw!r}")
    if not parts:
        raise ValueError(f"Empty contract path: {raw!r}")
    return "/".join(parts)


class TopologyNode(BaseModel):
    file_path: str = Field(description="Repo-root-relative path of the source file.")

    @field_validator("file_path")
    @classmethod
    def _normalize_path(cls, v: str) -> str:
        return normalize_repo_rel_path(v)
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
    shared_context: str = Field(
        default="",
        description="Language-neutral statement of the PROJECT's goal, domain, and intended "
        "user-facing purpose, distilled from the ticket + blueprint — enough for an agent with no "
        "other context to understand WHAT is being built and WHY. Compact but COMPLETE: usually 1-3 "
        "sentences, expand only when the domain genuinely requires it. Do NOT restate the technical "
        "directives (those live in instruction/core_libraries/architectural_constraints). Reference "
        "surfaced to the Developer and QA; instruction remains the authoritative directive.")
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

    @field_validator("files_to_modify")
    @classmethod
    def _normalize_files_to_modify(cls, v: list[str]) -> list[str]:
        # Strip blueprint-style leading slashes so `repo_dir / f` stays INSIDE the clone — see
        # normalize_repo_rel_path. Without this, `/.gitignore` escapes the write sandbox AND reads as
        # perpetually missing, looping the Developer reroute into the circuit breaker.
        return [normalize_repo_rel_path(f) for f in v]

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

class ArbiterVerdict(BaseModel):
    """Root-cause triage of a STUCK cycle. Adds a third routing target — the contract — beyond the
    Developer/QA feedback channels, so a flawed contract (not an agent-fixable bug) can be repaired
    instead of looping to the circuit breaker."""
    root_cause_class: Literal["production_bug", "test_bug", "contract_conflict", "unrecoverable"] = Field(
        description="Classification of WHY the cycle keeps failing.")
    route: Literal["developer", "qa", "contract", "halt"] = Field(
        description="Where to send the fix: the existing Developer/QA channel, a TechLead contract "
        "amendment, or a hard halt to a human.")
    reasoning: str = Field(description="Justification, citing the repeated failure evidence.")
    contract_amendment_directive: str = Field(
        default="",
        description="REQUIRED when route=='contract': the precise SPEC correction for the TechLead — "
        "which rule/precedence/approach the contract must change. MUST NOT propose changing "
        "environment_id (the platform is fixed). Empty for any other route.")

class DevOpsManifests(BaseModel):
    """E4 deploy-scaffolding output: the CI/CD manifests a DevOps run writes into the finished app.

    Generated once, after the batch has merged every ticket to the base branch (see
    ``run_devops_scaffold``). ``archetype`` is a closed enum so an invalid class fails at
    deserialization; ``dockerfile_content`` is null for a ``cli_tool`` (no runtime container — the
    workflow builds/publishes a binary instead of deploying to Cloud Run)."""
    archetype: Literal["rest_api", "crud_app", "cli_tool"] = Field(
        description="Deploy archetype of the finished app — determines whether a runtime Dockerfile + "
        "Cloud Run deploy is generated (web service) or a build/release matrix (CLI tool / library).")
    dockerfile_content: str | None = Field(
        default=None,
        description="Full Dockerfile content for a web service (multi-stage, non-root). MUST be null for "
        "a cli_tool — a CLI/library has no runtime container.")
    workflow_content: str = Field(
        description="Full content of the .github/workflows/deploy.yml GitHub Actions workflow.")
    env_scaffold_content: str | None = Field(
        default=None,
        description="Optional .env.example / config scaffold listing required runtime env vars (no secrets).")
    engineering_reasoning: str = Field(
        description="Why this deploy topology (and archetype) was chosen, given the blueprint + repo.")


class GlobalPipelineContext(BaseModel):
    pr_description: str              # CLEAN ticket description — SSOT for the commit subject / PR body.
    # TechLead routing brief: pr_description prefixed with the [CURRENT TASK] header + appended
    # [ARCHITECTURAL BLUEPRINT]. Kept SEPARATE from pr_description so the template scaffolding never
    # leaks into the commit/PR (the TechLead is the sole consumer). Empty on a resumed run → falls back.
    techlead_brief: str = ""
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
    # Arbiter (failure triage) state. arbiter_verdict holds the latest classification; contract_amendments
    # counts autonomous TechLead contract rewrites (bounded by MAX_CONTRACT_AMENDMENTS), persisted so a
    # --resume recomputes the (extended) retry ceiling identically.
    arbiter_verdict: ArbiterVerdict | None = None
    contract_amendments: int = 0
    current_attempt: int = 1
    repository_map: str = ""
    # E4 deploy-scaffolding output (set only on a --scaffold-deploy run); persisted for checkpoint parity.
    devops_manifests: DevOpsManifests | None = None
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


class BatchState(BaseModel):
    """E3 batch-level checkpoint: tracks which tickets of a Nexus plan have already merged to ``main``.

    A multi-ticket batch (``--auto-execute``) drives every planned ticket in TPM order, each one cloning
    ``main`` fresh — so progress must survive a mid-batch halt to resume without redoing merged tickets.
    Persisted as ``reports/batch_state.json`` in the Nexus run dir (sibling of the ``kind="nexus"``
    planning checkpoint), so a bare ``--resume <project>`` (which resolves to the latest Nexus run) can
    re-enter the loop. Same JSON dump/load pattern as NexusState / GlobalPipelineContext.
    """
    kind: Literal["batch"] = "batch"   # NOT a --resume checkpoint discriminator; a sidecar marker.
    project_slug: str
    nexus_run: str                     # the Nexus run dir name this batch is driving
    tickets: list[str] = Field(default_factory=list)    # full ordered ticket snapshot (TPM order)
    completed: list[str] = Field(default_factory=list)  # tickets already merged to the base branch
    failed: str | None = None          # the ticket that halted the batch (cleared on its later success)

    def save_checkpoint(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load_checkpoint(cls, path: Path) -> "BatchState":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
