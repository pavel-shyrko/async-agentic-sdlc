---
paths:
  - "prompts/system/*.md"
---

# System-prompt suite conventions

All seven role prompts (`po`, `sa`, `tpm`, `techlead`, `developer`, `qa`, `reviewer`) follow a single
house style. Preserve it when editing any `prompts/system/*.md`. Guardrail: never edit
`prompts/system/*` unless the Human explicitly orders it (CLAUDE.md). Related:
[prompt-language-independence](prompt-language-independence.md), [agent-contracts](agent-contracts.md),
[skill-routing-frontmatter](skill-routing-frontmatter.md).

**Why:** the prompts had accreted heavy intra-file duplication, stale contradictions (e.g. a `TASK-00`
reference the same prompt elsewhere forbade), and drifting vocabulary for the same shared concepts —
which caused deadlocks and missed defects in the FSM ([pipeline-fsm-loops](pipeline-fsm-loops.md)).

**How to apply:**
- **Structure**: identity line → rules section (`## NON-NEGOTIABLE RULES` / `## CORE DIRECTIVES` /
  `## CRITICAL ARCHITECTURE RULES`) → `## OUTPUT CONTRACT` or `## Output Schema` mapping each structured
  field. State each rule ONCE; later sections cross-reference rather than restate. The intro must not
  pre-enumerate what the rules/output-contract already specify.
- **environment_id vocabulary** is identical across `sa`/`tpm`/`techlead`: "copied VERBATIM", "one of the
  strictly supported platforms", "an unsupported value is rejected" (mirrors the shared validator,
  see [agent-contracts](agent-contracts.md)).
- **Placeholder injection** (`get_system_prompt_with_platforms`, brace-safe `.replace()`): keep these
  tokens byte-exact — `{injected_supported_platforms_list}` + `{injected_supported_deploy_targets_list}`
  (sa + tpm), and `{injected_readme_scaffold}` / `{injected_env_commands}` (now the **techwriter**, which
  authors the README post-implementation — NOT the tpm, which no longer injects either). `{injected_supported_deploy_targets_list}` renders the `SUPPORTED_DEPLOY_TARGETS` registry
  (the WHERE-it-deploys SSOT, sibling to the platform list); the SA selects a target into the Blueprint's
  `## Deployment Target`. `{injected_supported_platforms_list}` now carries each env's `authoring_contract`
  bullets (the dependency-manifest convention) under its description; the SA records the selected one into the
  Blueprint's `## Runtime Contract`, the TPM propagates it onto `TASK-01` — both prose-threaded like the deploy
  target. Other prompts use plain `get_system_prompt`. The `{strict_type_validation_rules}`
  token is replaced for skills only.
- **Shared executor concepts** (reviewer ⇄ developer ⇄ qa) use one consistent statement each: feedback-
  channel isolation (dev vs qa payload), test-softening + exception-fidelity, uncontracted-file triage
  (justified / hallucinated / legacy), zombie-test routing. Reviewer keeps test-softening self-contained
  even though the `strict_validation` skill also covers it.
- **Test-pinned literals** in `tests/framework/test_prompts.py` must survive edits (e.g. reviewer
  "WRONG TEST PACKAGE/NAMESPACE"; sa "HONOR THE USER'S MANDATED STACK"/"ORIGINAL USER REQUEST"; tpm
  "MANDATORY REPOSITORY PREPARATION RULE"/"there is NO standalone `TASK-00`"). Run the suite via
  [run-tests-via-wsl](run-tests-via-wsl.md) after any prompt edit.

**Prompt-only invariants (NOT code-enforced — fragile):** `domain_tags[0]` ⇄ `environment_id` agreement is
guaranteed only by prompt text; a single LLM misfire breaks it silently (hardening tracked in
docs/BACKLOG.md #19–#24). Feedback-channel isolation and "rejection must carry a non-empty diagnostic
payload" are now **code-enforced** — the `ReviewReport` biconditional validator (`_require_routing_coherence`)
plus the `reconcile_feedback_routing` SSOT (ADR 0024 / BACKLOG #11/#17/#18/#25), so they no longer rely on
prompt text alone.
