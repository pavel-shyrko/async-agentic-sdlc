import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

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


class BehaviorExample(BaseModel):
    """One authoritative golden case — the behavioral ORACLE for a function. Language-neutral DATA: the
    fields describe a case in prose/literals, never code, so the suite (QA) and the audit (Reviewer) share
    ONE source of truth for the expected behavior instead of independently guessing it."""
    input: str = Field(description="Language-neutral description of the input case.")
    expected: str = Field(default="", description="Expected output/return value for this input.")
    raises: str = Field(default="", description="OR the expected error TYPE/condition (never a message).")


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
    acceptance_examples: list[BehaviorExample] = Field(
        default_factory=list,
        description="Authoritative golden cases (input → expected | raises) — the behavioral ORACLE the "
        "QA suite asserts verbatim and the Reviewer adjudicates against. Pin the cases where the answer is "
        "non-obvious (empty/degenerate inputs, library-defined output, boundaries). Empty for non-code/infra "
        "tasks.")
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
    plane: str = "development" # control plane this agent belongs to: nexus | development | deployment
    input_tokens: int = 0      # fresh, uncached prompt tokens
    output_tokens: int = 0
    cache_read_tokens: int = 0   # cheap re-reads of a cached prompt (agentic CLI re-sends) — NOT budgeted
    cache_write_tokens: int = 0  # one-time cache population — NOT budgeted
    total_tokens: int = 0        # budgeted footprint: fresh input + output ONLY (cache excluded)
    cost_usd: Decimal = Decimal("0")
    duration_seconds: float = 0.0  # cumulative wall-clock spent in this agent's LLM/CLI calls
    calls: int = 0

class PhaseUsage(BaseModel):
    """Wall-clock for a non-LLM infra phase (a docker gate, git clone, PR/merge) — see
    ``PipelineTelemetry.record_phase``. Infra phases spend NO tokens/money, so this carries time only;
    it makes the previously-invisible gate/SAST/git time auditable next to the per-agent LLM time."""
    duration_seconds: float = 0.0  # cumulative wall-clock spent in this infra phase
    calls: int = 0                 # how many times the phase ran (e.g. a gate re-run per cycle)

class PipelineTelemetry(BaseModel):
    """Cumulative, checkpoint-persisted token/cost/time telemetry across all agent calls.

    ``cost_usd`` is the ONLY budget gate (money-only breaker, ADR 0022): it mixes Gemini (estimated from a
    price table) and Claude (authoritative, reported by the CLI). ``total_tokens`` is REPORTED, not capped —
    it counts only the real new footprint (fresh input + output) and DELIBERATELY EXCLUDES cache read/write
    tokens: the agentic Claude CLI re-sends its prompt every internal turn, so cache reads would otherwise
    dominate the count while costing ~10% of fresh input. Cache tokens are tracked separately for
    transparency. ``duration_seconds`` rolls up per-call wall-clock; ``by_plane()`` aggregates by control
    plane; ``merge()`` builds the application-wide total. Persisted in the context so spend survives
    ``--resume``.
    """
    total_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_write_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    total_duration_seconds: float = 0.0  # cumulative wall-clock across all recorded agent (LLM/CLI) calls
    total_infra_seconds: float = 0.0     # cumulative wall-clock across all non-LLM infra phases (gates/SAST/git)
    by_agent: dict[str, AgentUsage] = Field(default_factory=dict)
    by_phase: dict[str, PhaseUsage] = Field(default_factory=dict)  # infra phase → wall-clock (record_phase)

    @property
    def total_wall_seconds(self) -> float:
        """Real end-to-end wall-clock ≈ LLM/CLI time + measured infra (gate/SAST/git) time. The historical
        ``total_duration_seconds`` counted LLM time ONLY, hiding ~40%+ of the build (the gates/SAST/git that
        run between agent calls); this is the honest figure surfaced in the FinOps TOTAL."""
        return self.total_duration_seconds + self.total_infra_seconds

    def record(self, agent: str, input_tokens: int, output_tokens: int,
               cost_usd: Decimal | float = Decimal("0"), provider: str = "gemini",
               cache_read_tokens: int = 0, cache_write_tokens: int = 0,
               plane: str = "development", duration_seconds: float = 0.0) -> None:
        # Coerce at the boundary so float callers stay safe while precision is preserved exactly.
        cost = cost_usd if isinstance(cost_usd, Decimal) else Decimal(str(cost_usd))
        slot = self.by_agent.setdefault(agent, AgentUsage(provider=provider, plane=plane))
        slot.provider = provider
        slot.plane = plane
        # Budgeted total excludes cache — cache reads are cheap re-sends, not new spend footprint.
        budgeted = input_tokens + output_tokens
        slot.input_tokens += input_tokens
        slot.output_tokens += output_tokens
        slot.cache_read_tokens += cache_read_tokens
        slot.cache_write_tokens += cache_write_tokens
        slot.total_tokens += budgeted
        slot.cost_usd += cost
        slot.duration_seconds += duration_seconds
        slot.calls += 1
        self.total_tokens += budgeted
        self.total_cache_read_tokens += cache_read_tokens
        self.total_cache_write_tokens += cache_write_tokens
        self.total_cost_usd += cost
        self.total_duration_seconds += duration_seconds

    def record_phase(self, phase: str, duration_seconds: float) -> None:
        """Accumulate wall-clock for a non-LLM infra phase (a docker gate, the SAST scan, git clone, a
        PR/merge). Token/money-free — it only makes the gate/SAST/git time visible alongside the per-agent
        LLM time. Callers (the FSM in ``runner.py``) time the full call (incl. container startup) and pass
        the elapsed; a step that runs N times (e.g. a gate re-run per cycle) coalesces into one slot."""
        slot = self.by_phase.setdefault(phase, PhaseUsage())
        slot.duration_seconds += duration_seconds
        slot.calls += 1
        self.total_infra_seconds += duration_seconds

    def by_provider(self) -> dict[str, dict]:
        """Aggregate tokens + cost per provider (e.g. ``{"gemini": {...}, "claude": {...}}``)."""
        agg: dict[str, dict] = {}
        for usage in self.by_agent.values():
            slot = agg.setdefault(usage.provider, {"tokens": 0, "cost_usd": Decimal("0")})
            slot["tokens"] += usage.total_tokens
            slot["cost_usd"] += usage.cost_usd
        return agg

    def by_plane(self) -> dict[str, dict]:
        """Aggregate tokens + cost + time + calls per control plane (nexus | development | deployment)."""
        agg: dict[str, dict] = {}
        for usage in self.by_agent.values():
            slot = agg.setdefault(
                usage.plane,
                {"tokens": 0, "cost_usd": Decimal("0"), "duration_seconds": 0.0, "calls": 0},
            )
            slot["tokens"] += usage.total_tokens
            slot["cost_usd"] += usage.cost_usd
            slot["duration_seconds"] += usage.duration_seconds
            slot["calls"] += usage.calls
        return agg

    def merge(self, other: "PipelineTelemetry") -> None:
        """Fold another telemetry's totals + per-agent slots into this one.

        Used to build the application-wide aggregate (E5): the batch merges each finished ticket's
        telemetry (and the Nexus planning + DevOps phases) into a single ``BatchState.app_telemetry`` so the
        cross-plane spend, per-role/per-plane breakdown, and the running budget total survive ``--resume``.
        Sums every cumulative field; per-agent slots accumulate by name (same agent across runs coalesces).
        """
        for name, ou in other.by_agent.items():
            slot = self.by_agent.setdefault(name, AgentUsage(provider=ou.provider, plane=ou.plane))
            slot.provider = ou.provider
            slot.plane = ou.plane
            slot.input_tokens += ou.input_tokens
            slot.output_tokens += ou.output_tokens
            slot.cache_read_tokens += ou.cache_read_tokens
            slot.cache_write_tokens += ou.cache_write_tokens
            slot.total_tokens += ou.total_tokens
            slot.cost_usd += ou.cost_usd
            slot.duration_seconds += ou.duration_seconds
            slot.calls += ou.calls
        for phase, op in other.by_phase.items():
            pslot = self.by_phase.setdefault(phase, PhaseUsage())
            pslot.duration_seconds += op.duration_seconds
            pslot.calls += op.calls
        self.total_tokens += other.total_tokens
        self.total_cache_read_tokens += other.total_cache_read_tokens
        self.total_cache_write_tokens += other.total_cache_write_tokens
        self.total_cost_usd += other.total_cost_usd
        self.total_duration_seconds += other.total_duration_seconds
        self.total_infra_seconds += other.total_infra_seconds

    def finops_report(self, budget_usd: Decimal | float = Decimal("0")) -> dict:
        """Serializable FinOps summary: money spend vs the budget, plus per-plane/-provider/-agent breakdown.

        Budget is **money-only** (E5): the USD ceiling is the sole gate. Tokens are reported as raw counts
        (cache read/write surfaced separately) but no longer carry a budget — the token total is auditable,
        not a limit. Time (``duration_seconds``) is rolled up per agent and per plane.
        """
        budget_usd_dec = budget_usd if isinstance(budget_usd, Decimal) else Decimal(str(budget_usd))
        used_pct_usd = round(100.0 * float(self.total_cost_usd) / float(budget_usd_dec), 2) if budget_usd_dec else 0.0
        return {
            "total_cost_usd": round(self.total_cost_usd, 6),
            "budget_usd": round(budget_usd_dec, 6),
            "budget_used_pct_usd": used_pct_usd,
            "total_tokens": self.total_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_cache_write_tokens": self.total_cache_write_tokens,
            "total_duration_seconds": round(self.total_duration_seconds, 3),
            "total_infra_seconds": round(self.total_infra_seconds, 3),
            "total_wall_seconds": round(self.total_wall_seconds, 3),
            "by_plane": self.by_plane(),
            "by_provider": self.by_provider(),
            "by_agent": {name: usage.model_dump() for name, usage in self.by_agent.items()},
            "by_phase": {phase: usage.model_dump() for phase, usage in self.by_phase.items()},
        }

class SkillRelevance(BaseModel):
    score: float = Field(description="Semantic relevance score between 0.0 and 1.0")

class DocumentationUpdate(BaseModel):
    architecture_document: str = Field(
        description="The absolute, complete, updated content of docs/architecture_state.md markdown file, integrating new components, design decisions, and active constraints from the completed task."
    )
    readme: str = Field(
        description="The absolute, complete, updated content of README.md — the human-facing project README, built incrementally from the previous README plus this ticket's delta. Preserve the deployment/release URL marker blocks verbatim."
    )
    changelog: str = Field(
        description="The absolute, complete, updated content of the root CHANGELOG.md (Keep a Changelog format), adding one entry under [Unreleased] for the completed ticket and preserving all prior history."
    )
    usage_guide: str = Field(
        default="",
        description="The complete end-user usage guide for the finished, compiled/deployed application (docs/USAGE.md). Populate this ONLY on the final iteration (when the FINAL ITERATION input is true); leave it empty ('') on every earlier ticket.",
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
    dev_evidence_citation: str = Field(
        default="",
        description="VERBATIM evidence for a production rejection: a line quoted from the gate/runner output "
                    "OR a `FILE: <path>` + code excerpt from the production snapshot. Required (non-empty) "
                    "when code_quality_approved is false; empty otherwise.",
    )
    zombie_tests_to_delete: list[str] = Field(
        default_factory=list,
        description="List of specific obsolete or zombie test filenames that must be physically deleted from disk.",
    )

    @model_validator(mode="after")
    def _require_routing_coherence(self) -> "ReviewReport":
        """Code-enforce the feedback-routing invariant the prompt alone could not guarantee (BACKLOG
        #11/#17/#18): the channel(s) driving the next cycle must be fed only on a genuinely-rejected side,
        and a production rejection must point at real evidence. instructor re-prompts the Reviewer on any
        ValueError below, forcing a coherent report instead of a silent retry-budget burn."""
        # #17 — a rejection must carry actionable guidance (forward direction).
        if not self.code_quality_approved and not self.dev_diagnostic_payload.strip():
            raise ValueError("code_quality_approved=false requires a non-empty dev_diagnostic_payload.")
        if not self.test_integrity_approved and not self.qa_diagnostic_payload.strip():
            raise ValueError("test_integrity_approved=false requires a non-empty qa_diagnostic_payload.")
        # #18 — converse: an approved side must NOT carry a payload (else the router feeds a channel for a
        # defect-free side and the Developer + QA fight). Biconditional: payload non-empty <=> rejection.
        if self.code_quality_approved and self.dev_diagnostic_payload.strip():
            raise ValueError("code_quality_approved=true forbids a non-empty dev_diagnostic_payload.")
        if self.test_integrity_approved and self.qa_diagnostic_payload.strip():
            raise ValueError("test_integrity_approved=true forbids a non-empty qa_diagnostic_payload.")
        # #11 — a production rejection must cite verbatim evidence (a gate line or a code excerpt), so the
        # Reviewer cannot reroute the Developer onto a phantom structural defect.
        if not self.code_quality_approved and not self.dev_evidence_citation.strip():
            raise ValueError("code_quality_approved=false requires a non-empty dev_evidence_citation.")
        return self


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
    idea: str = ""                   # Original --idea string from project.json; propagated to agents.
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
    # True only for the LAST ticket of an --auto-execute batch (set fresh by run_executor each call, never
    # trusted from the checkpoint). Signals the TechWriter to author the end-user usage guide for the
    # finished/deployable application (docs/USAGE.md). Single-ticket paths leave it False.
    is_final_ticket: bool = False
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
    # E5 — application-wide FinOps. app_telemetry is the merged Nexus + every ticket + DevOps total, so the
    # running spend (app_telemetry.total_cost_usd), per-role/per-plane breakdown, and time survive --resume.
    # The budget CEILING is deliberately NOT stored here — it is re-resolved per invocation (env / --budget),
    # so re-passing a larger --budget on a resume "adds money" and continues a budget-halted batch.
    app_telemetry: PipelineTelemetry = Field(default_factory=PipelineTelemetry)
    nexus_merged: bool = False         # guards against folding the Nexus planning telemetry in twice on resume
    budget_marker: str | None = None   # set on a clean budget-exhaustion stop; cleared when a resume continues
    released_tag: str | None = None    # E6: the v* tag pushed after the batch completed (--release); idempotent resume guard

    def save_checkpoint(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load_checkpoint(cls, path: Path) -> "BatchState":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
