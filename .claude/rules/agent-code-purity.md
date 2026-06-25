---
paths:
  - "src/development/agents/*.py"
  - "src/nexus/agents/*.py"
  - "src/deployment/agents/*.py"
---

# Agent Python files must be pure control flow — no inline prompts

Agent `.py` files are **orchestration wiring only**: they assemble context from `ctx`, call
`get_system_prompt()` / `build_agent_context()`, inject structured data, and invoke the LLM.
**Instructional text belongs in `prompts/system/<role>.md`** — not in Python strings.

## What is allowed in agent code

```python
# OK — data injection with a neutral label
prompt += f"\n\n=== TOPOLOGY CONTRACT ===\n{topo}"

# OK — control flow, logging, telemetry
if ctx.contract.topology_contract:
    ...
log.info(f"🟩 [ROLE] Developer Agent ...")
```

## What is NOT allowed

```python
# WRONG — instructional text embedded in Python
prompt += (
    "\n\n=== TOPOLOGY CONTRACT (write EXACTLY these paths, repo-root-relative; "
    "never add a `src/` or other parent prefix) ===\n" + topo
)

# WRONG — retry framing as a Python string literal
prompt = (
    "⚠️ MANDATORY CORRECTION (overrides the Contract below for this turn) — "
    "your previous attempt was REJECTED. You MUST resolve the following ...\n"
    + error_trace + prompt
)
```

## Correct pattern

Move the instructional phrasing into `prompts/system/<role>.md` as a named template section with a
`{placeholder}` for the dynamic data. The agent code injects ONLY the data:

```python
# prompts/system/developer.md contains:
#   === TOPOLOGY CONTRACT ===
#   Place files at EXACTLY these repo-root-relative paths — never add a prefix:
#   {topology_block}

prompt = get_system_prompt("developer").format(
    ...
    topology_block=topo,
)
```

For retry headers, add a `{retry_header}` placeholder at the top of the system prompt and render it
conditionally (empty string on first cycle, filled on retry). Keep the full instructional sentence in
`.md`, not in `.py`.

## Why

- Prompt text in Python is invisible to the prompt-suite conventions
  ([prompt-suite-conventions](prompt-suite-conventions.md)) and
  [prompt-language-independence](prompt-language-independence.md) rules — those fire only on
  `prompts/system/*.md` and `prompts/skills/*.md`.
- Prompt text in Python is never reviewed by `/tbf-docs-sync` or `/tbf-claude-context-sync`.
- Inline Python strings scatter the agent's effective instructions across two places, making prompt
  engineering harder to reason about and test.

## Data vs instructions — the boundary

| Content | Where |
|---|---|
| Section label ONLY (e.g. `=== TOPOLOGY CONTRACT ===`) | OK in `.py` |
| Section label + inline instruction ("write EXACTLY these paths…") | must move to `.md` |
| Retry/correction directive ("MANDATORY CORRECTION … REJECTED … MUST resolve") | must move to `.md` |
| Structured data serialized from `ctx` | always OK in `.py` |
