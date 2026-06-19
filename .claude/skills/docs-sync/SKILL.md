---
name: docs-sync
description: Factually synchronize CHANGELOG.md (Keep a Changelog format) and README.md after code changes. Use when the user asks to update the changelog or README, sync docs to recent commits/diff, or reflect new CLI flags, env vars, directory structure, or execution commands. Focuses strictly on "what" changed.
---

# Factual Documentation Synchronization (Changelog & README)

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

## Output Format
Apply changes directly to the file system or provide strict `diff` blocks. End with a raw checklist of updated files. Zero conversational text.
