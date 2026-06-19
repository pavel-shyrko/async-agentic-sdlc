---
name: docs-sync
description: Factually synchronize CHANGELOG.md (Keep a Changelog format), README.md, and docs/ARCHITECTURE.md after code changes. Use when the user asks to update the changelog or README, sync docs to recent commits/diff, or reflect new CLI flags, env vars, directory structure, execution commands, agent roles, FSM routes, or planes/containers. Focuses strictly on "what" changed.
---

# Factual Documentation Synchronization (Changelog, README & Architecture)

## Context
Update factual project-state tracking after code changes. Focus strictly on "What" changed.

## Protocol
1. **Diff Analysis**: Read the recent commits or `git diff`.
2. **CHANGELOG Update**:
   - Target `CHANGELOG.md`.
   - Strictly follow the "Keep a Changelog" format.
   - Map changes to standard blocks: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
   - Translate raw code diffs into human-readable engineering features/fixes. Do not dump raw commit messages.
3. **README Alignment**:
   - Target `README.md`.
   - Scan for out-of-sync factual data across ALL of these surfaces (not just CLI flags — every one drifts independently):
     - **Agent roster / Model Routing Matrix** — the enumerated list of structured roles (TechLead, QA, Reviewer, TechWriter, Arbiter, PO/SA/TPM). A new agent role MUST be added here.
     - **Numbered capabilities list** — the "Custom FSM Engine / Model Routing / … / Fast-Fail Guardrail / Autonomous Contract Self-Healing" items; a new engine behavior gets a new item or extends one.
     - **Environment variables / tunable constants** — NOT only CLI flags: new `*_MODEL`, budgets, and FSM knobs (`PIPELINE_MAX_RETRIES`, `ARBITER_TRIGGER_ATTEMPT`, `MAX_CONTRACT_AMENDMENTS`, `ARBITER_AMENDMENT_RETRY_BONUS`, etc.) belong in the relevant prose. Name each env var explicitly.
     - **Directory structure tree** — new modules/dirs (e.g. a new `src/.../<role>.py` agent or a new `src/shared/core/*.py`) and the per-line role/file comments.
     - **CLI arguments / execution commands** and **Developer Meta-Tools** (the `.claude/skills/` list — add a new `/skill`).
   - Apply targeted diff patches to the relevant sections to reflect the current state.
   - **Completeness sweep (anti-drift):** when this iteration ADDED an agent role or a skill, grep the README for an existing peer (e.g. another role name, or `/docs-sync`) and confirm the new entry appears in EVERY place peers are enumerated — roster AND capabilities AND structure tree AND (for a skill) the meta-tools list. A role/skill that appears in only one of these is a sync miss.
4. **Architecture Diagram Sync** (`docs/ARCHITECTURE.md`):
   - This is the C4 model (L1 System Context / L2 Containers / L3 Executor FSM) + the end-to-end
     `sequenceDiagram` + the component-reference table, all in GitHub-native Mermaid
     (`flowchart`/`sequenceDiagram` — never C4-plugin syntax, which GitHub won't render).
   - **Trigger — only when this iteration changed *structure*, not behavior.** Skip this step entirely for
     pure bugfixes/tuning. Re-sync when any of these changed:
     - **A new/removed agent role** (a `src/{nexus,executor}/agents/*.py` or plane module + its `ROLE_MODELS`
       entry) → add/remove the node in the relevant L2/L3 diagram AND the component-reference table row.
     - **A new/removed/re-routed FSM state or decision edge** (e.g. a new routing target like Arbiter, a new
       gate, a changed `while`/deadlock/breaker condition in `src/executor/runner.py`) → update the **L3
       Executor FSM** flowchart to match [pipeline-fsm-loops](../../rules/pipeline-fsm-loops.md). Don't
       duplicate that rule's prose — keep the diagram faithful and cross-reference it.
     - **A new external system** (a new provider/CLI/service the engine talks to) → L1 System Context node + arrow.
     - **A new plane / container / store** (a new top-level `src/` plane, prompt store, sandbox image class,
       or run-store artifact) → L2 Containers diagram + boundary.
   - **Drift sweep (same idiom as the README sweep):** grep `docs/ARCHITECTURE.md` for an existing peer of the
     new element (a sibling role name, a neighbouring FSM node, another container) and confirm the new element
     appears in BOTH the diagram AND the component-reference table. Presence in only one is a sync miss.
   - Keep diagrams grounded strictly in the current code — no invented or aspirational components.

## Output Format
Apply changes directly to the file system or provide strict `diff` blocks. End with a raw checklist of updated files. Zero conversational text.
