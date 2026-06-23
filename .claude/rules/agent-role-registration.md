---
paths:
  - "src/shared/core/config.py"
  - "src/development/agents/*.py"
  - "src/deployment/agents/*.py"
  - "src/nexus/*.py"
  - "src/nexus/agents/*.py"
---

# Adding a new structured (Gemini/instructor) agent role

Checklist of EVERY touch point to register a new agent role (e.g. the `arbiter` added in ADR 0016).
Miss one and the role silently won't load, won't bill, or won't persist on `--resume`. Roles run via
`run_structured_llm(role, Model, messages)` (instructor → forced Pydantic output); the Developer is the
exception (agentic Claude CLI). See [agent-provider-model-map](agent-provider-model-map.md),
[agent-contracts](agent-contracts.md), [repo-module-map](repo-module-map.md).

1. **Model + label + plane** — `src/shared/core/config.py`: add `XYZ_MODEL = GEMINI_3_5_FLASH` near the
   other role models, AND an entry in `ROLE_MODELS`: `"xyz": (XYZ_MODEL, "Xyz Agent")`. The dict key is the
   `role` slug passed to `run_structured_llm`; the label is the human name used in logs/telemetry. **ALSO add
   that exact label to `AGENT_PLANE`** (`"Xyz Agent": "nexus"|"development"|"deployment"`) — E5 FinOps derives
   the per-plane rollup from this map by display label, so a missing entry silently mis-buckets the role's
   spend into the default `"development"` plane (the same "miss-one-and-it-mis-bills" trap as a missing
   `log_token_usage`). See [finops-app-budget](finops-app-budget.md).
2. **System prompt** — `prompts/system/<role>.md`. Single-section (loaded by `get_system_prompt` +
   `build_agent_context`, like reviewer/techlead) UNLESS it needs a user-template split (then
   `---`-delimited, like qa via `get_system_prompt_sections`). Must be language-neutral
   ([prompt-language-independence](prompt-language-independence.md)) and follow house style
   ([prompt-suite-conventions](prompt-suite-conventions.md)). Editing `prompts/system/*` needs explicit
   Human authorization (CLAUDE.md). Nexus-plane prompts that inject platforms use
   `get_system_prompt_with_platforms`.
3. **Output model** — a Pydantic model in `src/shared/core/models.py` (e.g. `ArbiterVerdict`). Use
   `Literal[...]` for closed enums so an invalid value fails at deserialization. If it carries an
   `environment_id`, reuse the shared `_validate_environment_id` validator.
4. **Agent node** — `src/development/agents/<role>.py` (worker plane) or `src/nexus/agents/<role>.py` (control
   plane). Mirror [reviewer.py](../../src/development/agents/reviewer.py): build `sys_prompt =
   get_system_prompt(role) + "\n\n" + await build_agent_context(role, ctx)`, call
   `run_structured_llm(role, Model, [...])`, store the result on `ctx`, then **always**
   `log_token_usage(ctx.telemetry, "<Label>", raw_response, XYZ_MODEL)` — telemetry parity is mandatory
   or FinOps/the financial breaker under-counts.
5. **State + persistence** — if the node's output must survive `--resume`, add a field to
   `GlobalPipelineContext` (worker) or `NexusState` (control). Both checkpoint via
   `model_dump_json`/`model_validate_json`, so a new field auto-persists — no extra plumbing.
6. **FSM wiring** — import the node in `src/nexus/runner.py` and call it at the
   right point in the cycle; gate it so existing flows are unaffected. New caps/limits go in as
   UPPER_CASE env-overridable constants ([config-constant-convention](config-constant-convention.md)),
   never inline literals. Control flow: [pipeline-fsm-loops](pipeline-fsm-loops.md).
7. **Tests** — `tests/framework/test_orchestrator.py` (mock the node, assert routing/termination via the
   existing `mock.patch.object(orchestrator, "run_*_node", ...)` pattern), a node unit test
   (mock `run_structured_llm`, assert verdict stored + telemetry recorded), and `test_prompts.py` pins
   for any new prompt literals. Run via [run-tests-via-wsl](run-tests-via-wsl.md).
8. **ADR** — if the role introduces a new FSM state or changes routing, write one (`/adr-generation`).
