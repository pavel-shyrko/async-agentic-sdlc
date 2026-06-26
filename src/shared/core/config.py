import os
import sys
import shutil
import instructor
from decimal import Decimal
from contextvars import ContextVar
from google import genai
from google.genai import types
from google.genai.errors import ClientError

from src.shared.core.observability import log

# ==========================================
# MODEL ROUTING (single source of truth)
# ==========================================
# Available Gemini models (priced in MODEL_PRICING_MATRIX below) — assign any of these to the
# role constants. Ordered most → least capable / expensive:
GEMINI_3_1_PRO_PREVIEW = "gemini-3.1-pro-preview"   # tiered: doubles past 200k context
GEMINI_2_5_PRO         = "gemini-2.5-pro"
GEMINI_3_5_FLASH       = "gemini-3.5-flash"
GEMINI_2_5_FLASH       = "gemini-2.5-flash"
GEMINI_3_1_FLASH_LITE  = "gemini-3.1-flash-lite"
GEMINI_2_5_FLASH_LITE  = "gemini-2.5-flash-lite"    # cheapest

AVAILABLE_GEMINI_MODELS = (
    GEMINI_3_1_PRO_PREVIEW,
    GEMINI_2_5_PRO,
    GEMINI_3_5_FLASH,
    GEMINI_2_5_FLASH,
    GEMINI_3_1_FLASH_LITE,
    GEMINI_2_5_FLASH_LITE,
)

# Per-role model — set to any value from AVAILABLE_GEMINI_MODELS.
TECHLEAD_MODEL = GEMINI_2_5_FLASH
QA_MODEL = GEMINI_2_5_FLASH
REVIEWER_MODEL = GEMINI_2_5_FLASH
TECHWRITER_MODEL = GEMINI_2_5_FLASH   # Living-ADR maintainer; matches the other Gemini worker roles.
ARBITER_MODEL = GEMINI_2_5_FLASH      # Failure-triage / contract-conflict classifier (see runner FSM).
DEVOPS_MODEL = GEMINI_2_5_FLASH       # Deploy-scaffolding finalizer (E4); matches the other Gemini worker roles.
DB_ARCHITECT_MODEL = GEMINI_2_5_FLASH  # DB schema generation from blueprint (E7 --provision-db).
SEED_DATA_MODEL = GEMINI_2_5_FLASH     # Seed INSERT generation (E7 --provision-db, dev/staging only).
# Nexus Control Plane roles (Product Owner / Solution Architect / TPM). Defaulted to the
# cheap flash-lite tier to match the worker roles and keep the PoC inexpensive; SA/TPM can be
# bumped to GEMINI_2_5_PRO for deeper architectural reasoning.
PO_MODEL = GEMINI_2_5_FLASH     # lighter tier — avoids gemini-3.5-flash 503 high-demand spikes
SA_MODEL = GEMINI_2_5_FLASH
TPM_MODEL = GEMINI_2_5_FLASH
# Available Claude models for the Developer agent (Claude CLI). The CLI --model accepts a tier
# ALIAS (always resolves to the latest of that tier) or a pinned full id for reproducibility.
# Ordered most → least capable / expensive:
CLAUDE_OPUS   = "opus"      # latest Opus   (pin: "claude-opus-4-8")   — most capable
CLAUDE_SONNET = "sonnet"    # latest Sonnet (pin: "claude-sonnet-4-6") — balanced (default)
CLAUDE_HAIKU  = "haiku"     # latest Haiku  (pin: "claude-haiku-4-5")  — cheapest / fastest

AVAILABLE_CLAUDE_MODELS = (CLAUDE_OPUS, CLAUDE_SONNET, CLAUDE_HAIKU)

# Available reasoning-effort levels for the Claude CLI (--effort). Ordered shallow → deep
# (more effort = more thinking tokens = higher cost/latency):
EFFORT_LOW    = "low"
EFFORT_MEDIUM = "medium"
EFFORT_HIGH   = "high"
EFFORT_XHIGH  = "xhigh"
EFFORT_MAX    = "max"

AVAILABLE_EFFORT_LEVELS = (EFFORT_LOW, EFFORT_MEDIUM, EFFORT_HIGH, EFFORT_XHIGH, EFFORT_MAX)

# Developer agent (Claude CLI) — set each to any value from the catalogs above.
DEVELOPER_MODEL = CLAUDE_SONNET           # any of AVAILABLE_CLAUDE_MODELS (or a pinned full id)
DEVELOPER_EFFORT = EFFORT_MEDIUM          # any of AVAILABLE_EFFORT_LEVELS

# Wall-clock ceiling (seconds) for ONE agentic Developer CLI session. The launcher kills+reaps the
# child on expiry so a stalled `claude` can never hang the orchestrator. Generous default (15 min);
# env-overridable. This is the hard BACKSTOP; the idle watchdog below normally fires first.
DEVELOPER_CLI_TIMEOUT = int(os.environ.get("DEVELOPER_CLI_TIMEOUT", "900"))

# Inactivity ceiling (seconds): if the streaming Developer CLI emits NO output for this long, the
# launcher kills it — a stalled/rate-limited API call produces silence, so this catches it far sooner
# than the hard wall-clock cap. Env-overridable.
DEVELOPER_CLI_IDLE_TIMEOUT = int(os.environ.get("DEVELOPER_CLI_IDLE_TIMEOUT", "120"))

# Per-request wall-clock ceiling (seconds) for EVERY structured Gemini call (run_structured_llm → the
# shared instructor/genai client). Without it a stalled HTTP request hangs the executor forever, because
# with_api_retry only fires on exceptions and run_in_executor has no timeout. Wired into the client as
# `http_options.timeout` (milliseconds); on expiry the SDK raises, with_api_retry backs off and fails
# fast. Matches the GIT_NETWORK_TIMEOUT / GH_NETWORK_TIMEOUT 300 s convention; env-overridable.
GEMINI_REQUEST_TIMEOUT = int(os.environ.get("GEMINI_REQUEST_TIMEOUT", "300"))

# The Claude CLI executable. Default "claude" resolves on PATH; under WSL point this at the Linux
# binary (e.g. "/usr/local/bin/claude") so the run never accidentally resolves to a Windows
# `claude.exe` across the WSL↔Win32 interop boundary. Env-overridable.
CLAUDE_CLI_BIN = os.environ.get("CLAUDE_CLI_BIN", "claude")

# Semver bump level for the E6 autonomous release tag (`--release`): one of `major|minor|patch`. After a
# batch merges every ticket, the engine derives the next `v*` tag from the repo's existing tags and bumps it
# by this much (`v0.1.0` on a tagless/greenfield repo). The version itself is repo-derived — never persisted
# — so only the bump POLICY is a knob. Env-overridable.
RELEASE_VERSION_BUMP = os.environ.get("RELEASE_VERSION_BUMP", "minor")

# E7 — schema-validation gate retry budget for the DB provisioning phase (--provision-db).
# On a gate failure the DatabaseArchitectAgent is re-invoked with the violation list; this caps
# how many times that loop may run before a Hard Halt.
DB_PROVISION_MAX_RETRIES = int(os.environ.get("DB_PROVISION_MAX_RETRIES", "2"))

# ==========================================
# FINOPS — Financial Circuit Breaker budget
# ==========================================
# Application-wide USD spend budget (E5) — the SINGLE Financial Circuit Breaker ceiling governing a whole
# build (idea → all tickets → optional deploy), not each ticket in isolation. The batch threads the
# REMAINING budget (app_budget − spent) into each ticket; a per-invocation --budget overrides this. Money
# is the sole gate: cost is authoritative for Claude (CLI-reported) and estimated for Gemini, which keeps
# the breaker honest even when the agentic Claude CLI's cheap cache reads inflate the raw token count.
# Env-overridable; generous default so normal runs never trip. NEVER persisted in BatchState — re-resolved
# every invocation, so re-passing a larger --budget on a --resume "adds money" and continues a halted batch.
PIPELINE_APP_BUDGET_USD = Decimal(os.environ.get("PIPELINE_APP_BUDGET_USD", "25.00"))

# Below this remaining application budget the E3 batch stops cleanly BEFORE dispatching the next ticket,
# rather than starting one that would almost certainly trip the breaker mid-run. Env-overridable.
PIPELINE_APP_BUDGET_FLOOR_USD = Decimal(os.environ.get("PIPELINE_APP_BUDGET_FLOOR_USD", "0.01"))

# Cumulative token total — REPORTED ONLY (no longer a budget/ceiling, E5). Counts the real new footprint
# (fresh input + output; cache read/write are EXCLUDED, see PipelineTelemetry). Retained so the FinOps
# report can surface the token footprint alongside the money spend; the breaker gates on USD alone.
PIPELINE_BUDGET_TOKENS = int(os.environ.get("PIPELINE_BUDGET_TOKENS", "1000000"))

# Effective money ceiling for the CURRENT run scope, published as a runtime-only ContextVar (NEVER
# persisted — re-budgeting depends on re-resolving the ceiling each invocation, ADR 0022). It exists so the
# FinOps GRAND TOTAL / report render against the real --budget ceiling, not this module default: main() sets
# it to the app budget (so the Nexus summary shows it) and run_executor overrides it to the *remaining*
# per-ticket ceiling (so the per-ticket summary matches the breaker). A ContextVar (per-asyncio-task copy)
# keeps batch tickets isolated and avoids threading the budget through _abort_with_incident's many call
# sites. Unset → effective_budget_usd() falls back to PIPELINE_APP_BUDGET_USD (so existing callers/tests are
# unchanged).
EFFECTIVE_BUDGET_USD: ContextVar = ContextVar("EFFECTIVE_BUDGET_USD", default=None)


def effective_budget_usd() -> Decimal:
    """The effective money ceiling for the current run scope (the EFFECTIVE_BUDGET_USD ContextVar), or
    PIPELINE_APP_BUDGET_USD when unset. SSOT denominator the FinOps report/summary render against."""
    current = EFFECTIVE_BUDGET_USD.get()
    return current if current is not None else PIPELINE_APP_BUDGET_USD

# Role -> (model, human-readable agent name) for structured (instructor) LLM calls.
ROLE_MODELS = {
    "techlead": (TECHLEAD_MODEL, "Technical Lead Agent"),
    "qa":        (QA_MODEL,        "QA Agent"),
    "reviewer":  (REVIEWER_MODEL,  "Reviewer Agent"),
    "techwriter": (TECHWRITER_MODEL, "Technical Writer Agent"),
    "arbiter":   (ARBITER_MODEL,   "Arbiter Agent"),
    "devops":       (DEVOPS_MODEL,       "DevOps Agent"),
    "db_architect": (DB_ARCHITECT_MODEL, "DB Architect Agent"),
    "seed_data":    (SEED_DATA_MODEL,    "Seed Data Agent"),
    # Nexus Control Plane roles.
    "po":      (PO_MODEL,      "Product Owner Agent"),
    "sa":      (SA_MODEL,      "Solution Architect Agent"),
    "tpm":     (TPM_MODEL,      "Technical Project Manager Agent"),
}

# Agent display-label -> control plane (E5 FinOps per-plane rollup). Keyed by the EXACT labels passed to
# log_token_usage / telemetry.record (the by_agent keys), so plane attribution needs no per-agent-call
# change. The Developer (Claude CLI) records "Developer Agent" directly. Keep in sync with ROLE_MODELS
# labels + the Developer when adding a role (see agent-role-registration rule).
AGENT_PLANE = {
    "Product Owner Agent": "nexus",
    "Solution Architect Agent": "nexus",
    "Technical Project Manager Agent": "nexus",
    "Technical Lead Agent": "development",
    "TechLead": "development",                  # techlead.py logs the short label
    "QA Agent": "development",
    "Reviewer Agent": "development",
    "Technical Writer": "development",          # techwriter.py logs the short label
    "Technical Writer Agent": "development",
    "Arbiter Agent": "development",
    "Developer Agent": "development",
    "DevOps Agent": "deployment",
    "DB Architect Agent": "deployment",
    "Seed Data Agent": "deployment",
}

# ==========================================
# FINOPS — Gemini cost estimation (cache-aware + tiered)
# ==========================================
# Gemini's API does not return a cost figure (unlike the Claude CLI, which reports
# total_cost_usd authoritatively), so Gemini spend is ESTIMATED from token counts.
# All rates are USD per 1,000,000 tokens — ESTIMATES; tune them to your billing tier.
# Accuracy notes baked into the model:
#   * Cached input (context caching) bills far cheaper than fresh input — priced separately.
#   * Heavy models apply a long-context surcharge (≈2x) once the prompt exceeds a threshold.
#   * Multimodal (image/audio) tokens bill differently; treated as a text-rate approximation.
# Exact-precision pricing matrix. Monetary values are Decimal initialised from STRINGS to avoid
# IEEE-754 binary approximation. Each tier is (input, output, cached_read) USD per 1M tokens:
#   "short" → context <= 200k tokens, "long" → context > 200k tokens.
# Source: Google AI paid-tier pricing, verified 2026-06. Rates are the text/image/video tier
# (audio bills higher; treated as a text-rate approximation here). The per-hour context-cache
# STORAGE price ($1/1M tokens/hr) is NOT modelled: it applies only to EXPLICIT CachedContent you
# create with a TTL — this engine uses implicit caching (reads usage_metadata.cached_content_token_count
# at the per-token cached_read rate), so there is no storage charge to account for.
LONG_CONTEXT_THRESHOLD = 200_000
DEFAULT_PRICING_MODEL = "gemini-2.5-flash-lite"   # fallback rates for an unknown model

MODEL_PRICING_MATRIX: dict[str, dict[str, tuple[Decimal, Decimal, Decimal]]] = {
    "gemini-3.1-pro-preview": {
        "short": (Decimal("2.00"), Decimal("12.00"), Decimal("0.20")),
        "long":  (Decimal("4.00"), Decimal("18.00"), Decimal("0.40")),
    },
    "gemini-2.5-pro": {
        "short": (Decimal("1.25"), Decimal("10.00"), Decimal("0.125")),
        "long":  (Decimal("2.50"), Decimal("15.00"), Decimal("0.25")),
    },
    "gemini-3.5-flash": {
        "short": (Decimal("1.50"), Decimal("9.00"), Decimal("0.15")),
        "long":  (Decimal("1.50"), Decimal("9.00"), Decimal("0.15")),
    },
    "gemini-2.5-flash": {
        "short": (Decimal("0.30"), Decimal("2.50"), Decimal("0.03")),
        "long":  (Decimal("0.30"), Decimal("2.50"), Decimal("0.03")),
    },
    "gemini-3.1-flash-lite": {
        "short": (Decimal("0.25"), Decimal("1.50"), Decimal("0.025")),
        "long":  (Decimal("0.25"), Decimal("1.50"), Decimal("0.025")),
    },
    "gemini-2.5-flash-lite": {
        "short": (Decimal("0.10"), Decimal("0.40"), Decimal("0.01")),
        "long":  (Decimal("0.10"), Decimal("0.40"), Decimal("0.01")),
    },
}

# Catalog and pricing matrix must stay in lockstep — fail fast on drift.
if set(AVAILABLE_GEMINI_MODELS) != set(MODEL_PRICING_MATRIX):
    raise RuntimeError(
        "AVAILABLE_GEMINI_MODELS and MODEL_PRICING_MATRIX are out of sync: "
        f"{set(AVAILABLE_GEMINI_MODELS) ^ set(MODEL_PRICING_MATRIX)}"
    )

_PER_MILLION = Decimal(1_000_000)


def estimate_gemini_cost_usd(model_name: str, usage_metadata) -> Decimal:
    """Exact-precision USD cost for one Gemini call from its ``usage_metadata`` object.

    All arithmetic is ``Decimal``. Accounts for context-cache discounts (cached tokens priced at
    the cheaper ``cached_read`` rate) and tiered context pricing (the ``long`` tier applies once the
    prompt exceeds ``LONG_CONTEXT_THRESHOLD``). Multimodal prompts are priced at the text rate with
    a debug warning. Reads every field defensively — never raises (returns ``Decimal("0")``).
    """
    try:
        tiers = MODEL_PRICING_MATRIX.get(model_name)
        if tiers is None:
            log.debug(f"No pricing for model '{model_name}'; using default '{DEFAULT_PRICING_MODEL}' rates.")
            tiers = MODEL_PRICING_MATRIX[DEFAULT_PRICING_MODEL]

        prompt = int(getattr(usage_metadata, "prompt_token_count", 0) or 0)
        cached = int(getattr(usage_metadata, "cached_content_token_count", 0) or 0)
        output = int(getattr(usage_metadata, "candidates_token_count", 0) or 0)
        uncached = max(prompt - cached, 0)

        in_rate, out_rate, cached_rate = tiers["long" if prompt > LONG_CONTEXT_THRESHOLD else "short"]

        details = getattr(usage_metadata, "prompt_tokens_details", None) or []
        if any(str(getattr(d, "modality", "TEXT")).upper().endswith("TEXT") is False for d in details):
            log.debug("Non-text modality detected; Gemini cost is a text-rate approximation.")

        return (Decimal(uncached) * in_rate + Decimal(cached) * cached_rate
                + Decimal(output) * out_rate) / _PER_MILLION
    except Exception as e:  # pragma: no cover - pricing must never break the pipeline
        log.debug(f"Failed to estimate Gemini cost for '{model_name}': {e}")
        return Decimal("0")

# ==========================================
# ENVIRONMENT CHECKER
# ==========================================
def check_environment(require_forge: bool = False):
    log.info("🔍 Pre-flight environment check...")
    # `gh` (+ GITHUB_TOKEN) is only required when the run will open/merge a PR (--auto-merge, E2),
    # so plain runs never force a forge CLI on the operator.
    tools = ["docker", "claude", "bandit"] + (["gh"] if require_forge else [])
    for tool in tools:
        if not shutil.which(tool):
            log.error(f"🚨 CRITICAL: Binary '{tool}' not found in PATH.")
            sys.exit(1)

    if not os.environ.get("GEMINI_API_KEY"):
        log.error("🚨 CRITICAL: GEMINI_API_KEY is not set.")
        sys.exit(1)

    if require_forge and not os.environ.get("GITHUB_TOKEN"):
        log.error("🚨 CRITICAL: --auto-merge requires GITHUB_TOKEN (gh PR/merge auth) to be set.")
        sys.exit(1)

    # Container hardening: in docker mode the framework source must be immutable so the
    # Developer agent cannot mutate the pipeline itself (mount src/ :ro or run as non-root).
    if os.environ.get("RUNTIME_ENV") == "docker":
        if os.access("src", os.W_OK):
            log.error("🚨 CRITICAL: RUNTIME_ENV=docker but 'src/' is writable. "
                      "Mount it read-only (:ro) or run as a non-root user to prevent self-mutation.")
            sys.exit(1)
        log.info("  ✓ src/ confirmed read-only (container hardening).")

    log.info("  ✓ Environment verified.\n")

# ==========================================
# GENAI / INSTRUCTOR CLIENT SINGLETONS
# ==========================================
def get_genai_client() -> genai.Client:
    """Returns the module-level Google AI Studio client singleton."""
    return _genai_client


def _build_genai_client() -> genai.Client:
    log.debug("Initializing Google AI Studio client via GEMINI_API_KEY")
    return genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY"),
        # Bound every request so a stalled call raises instead of hanging the executor forever.
        http_options=types.HttpOptions(timeout=GEMINI_REQUEST_TIMEOUT * 1000),  # SDK expects ms
    )


_genai_client: genai.Client = _build_genai_client()

instructor_client: instructor.Instructor = instructor.from_genai(
    client=_genai_client,
    mode=instructor.Mode.GENAI_STRUCTURED_OUTPUTS,
)

# ==========================================
# HELPER FOR GRACEFUL QUOTA ERROR HANDLING
# ==========================================
def handle_quota_error(e: ClientError):
    log.error("\n🚨 RATE LIMIT EXHAUSTED (429) DETECTED!")
    log.error("   Your project is currently hitting the Google AI Studio quota limit.")
    log.error("   Ensure your AI Studio project is on a Pay-as-you-go plan.")
    log.error("\n   Details:")
    log.error(f"   {e}")
