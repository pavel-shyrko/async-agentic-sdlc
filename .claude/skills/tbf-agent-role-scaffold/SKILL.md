---
name: tbf-agent-role-scaffold
description: Scaffold a new structured (Gemini/instructor) agent role end-to-end across every touch point — config/ROLE_MODELS, system prompt, Pydantic output model, agent node, checkpoint persistence, FSM wiring, tests, and the ADR. Use when the user asks to add a new agent/role to any plane (Nexus control / Development worker / Deployment infra). Operationalizes the agent-role-registration rule; the Developer is the one role this does NOT fit (it is the agentic Claude CLI, not structured).
disable-model-invocation: true
---

# Scaffold a New Structured Agent Role

## Context
Adding a structured role touches ~8 places; miss one and the role silently won't load, won't bill, or won't
persist on `--resume`. This skill walks every touch point. The authoritative checklist is the
[agent-role-registration](../../rules/agent-role-registration.md) rule — this skill *executes* it. All
structured roles run via `run_structured_llm(role, Model, messages)` (instructor → forced Pydantic output);
the **Developer** is the sole exception (agentic Claude CLI) and is out of scope here. See
[agent-provider-model-map](../../rules/agent-provider-model-map.md), [agent-contracts](../../rules/agent-contracts.md).

## Step 0 — Decide plane & shape
Control plane (`src/nexus/`) or worker plane (`src/development/`)? Does it introduce a **new FSM state/route**
(→ needs an ADR + a `pipeline-fsm-loops` update) or slot into an existing transition? What is its input
context and its structured output model?

## Steps — the registration checklist (apply each)
1. **Model + label + plane** — `src/shared/core/config.py`: add `XYZ_MODEL = GEMINI_3_5_FLASH` near the other
   role models AND an entry in `ROLE_MODELS`: `"xyz": (XYZ_MODEL, "Xyz Agent")`. The dict key is the `role` slug
   passed to `run_structured_llm`; the label is the human name in logs/telemetry. **ALSO map that exact label
   in `AGENT_PLANE`** (`nexus`/`development`/`deployment`) — E5 per-plane FinOps derives the rollup from this by
   label, so a missing entry mis-buckets the role's spend into the default `development` plane.
2. **System prompt** — `prompts/system/<role>.md`. **⚠ Editing/creating files under `prompts/system/`
   requires explicit Human authorization (CLAUDE.md guardrail) — confirm before writing.** Single-section
   (loaded by `get_system_prompt` + `build_agent_context`, like reviewer/techlead) unless it needs a
   user-template split (`---`-delimited, like qa). Must be language-neutral and follow house prompt style.
3. **Output model** — Where to define it depends on the plane:
   - **Worker-plane / shared** (used across agents or by FSM routing) → `src/shared/core/models.py` (e.g., `ReviewReport`, `ArbiterVerdict`, `TechLeadContract`).
   - **Control-plane only** (used by a single nexus agent, not consumed by the FSM) → local in the agent file (e.g., `TaskTicket`/`ProjectPlan` in `src/nexus/agents/tpm.py`, `Blueprint` in `sa.py`).
   Use `Literal[...]` for closed enums so an invalid value fails at deserialization. If it carries an `environment_id`, reuse the shared `_validate_environment_id` validator (importable from `src/shared/core/environments.py`).
4. **Agent node** — `src/development/agents/<role>.py` (worker) or `src/nexus/agents/<role>.py` (control).
   - **Worker-plane:** mirror [reviewer.py](../../../src/development/agents/reviewer.py): build `sys_prompt =
     get_system_prompt(role) + "\n\n" + await build_agent_context(role, ctx)`, call
     `run_structured_llm(role, Model, [...])`, store the result on `ctx`.
   - **Control-plane (nexus):** mirror `src/nexus/agents/tpm.py` or `po.py`: the context is passed directly as
     `epic_text`/`blueprint_text` parameters; use `get_system_prompt_with_platforms(role)` (not
     `get_system_prompt`) when the prompt injects the platform/environment list
     (`{injected_supported_platforms_list}`).
   In both planes: ALWAYS `log_token_usage(ctx.telemetry, "<Label>", raw_response, XYZ_MODEL)` — telemetry
   parity is mandatory or FinOps/the financial breaker under-counts.
5. **State + persistence** — if the output must survive `--resume`, add a field to `GlobalPipelineContext`
   (worker) or `NexusState` (control). Both checkpoint via `model_dump_json`/`model_validate_json`, so a new
   field auto-persists.
6. **FSM wiring** — wire the node in the runner for its plane:
   - **Control-plane (nexus)** → `src/nexus/nexus_runner.py` (`run_nexus` function: the linear PO→SA→TPM
     sequence; add a new phase there). The nexus FSM has no retry loop — each phase checkpoints on success.
   - **Worker-plane (development / deployment)** → `src/nexus/runner.py` (`run_executor` function: the
     budgeted retry cycle). Gate it so existing flows are unaffected.
   New caps/limits are env-overridable `UPPER_CASE` constants
   ([config-constant-convention](../../rules/config-constant-convention.md)), never inline literals.
7. **Tests** — `tests/framework/test_orchestrator.py` (mock the node, assert routing/termination via the
   `mock.patch.object(... "run_*_node" ...)` pattern), a node unit test (mock `run_structured_llm`, assert
   verdict stored + telemetry recorded), and `test_prompts.py` pins for new prompt literals. Run via
   [run-tests-via-wsl](../../rules/run-tests-via-wsl.md).
8. **ADR** — if the role adds a new FSM state or changes routing, write one (run the `/tbf-adr-generation` skill).

## Step 9 — Propagate the new role everywhere it is enumerated
A new role is a peer-set member: run `/tbf-docs-sync` (README Model-Routing roster + `agents/` tree + `prompts/system/`
list + ARCHITECTURE L1/L2 + component table) and `/tbf-claude-context-sync` (the `repo-module-map`,
`agent-provider-model-map`, and `agent-contracts` rules). Confirm `ls src/*/agents/*.py` + `ls prompts/system/`
match what the docs enumerate — a role present in one enumeration and missing from a sibling is the canonical
drift miss.

## Output Format
Apply changes directly (pausing for Human sign-off before any `prompts/system/` write). End with a raw
checklist of every touch point above marked done / N-A. Zero conversational filler.
