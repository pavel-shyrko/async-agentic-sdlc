---
name: tbf-claude-context-sync
description: Reconcile Claude's own operating context — the CONTENT of .claude/rules/*.md and .claude/skills/*/SKILL.md — to the current code after a feature/fix. Use when the user asks to update/sync the rules or skills, or after a change adds a module, CLI flag, env knob, FSM state/route, agent role, external provider, or failure mode. Complements tbf-docs-sync (which owns human docs + enumeration sweeps); this owns the rule/skill prose and triggers. Accepts a diff range or a description of what changed.
---

# Claude Operating-Context Sync (rules & skills)

## Context
`/tbf-docs-sync` keeps the **human-facing** docs (CHANGELOG/README/ARCHITECTURE) current and runs an
*enumeration* peer-sweep (is every agent/knob/skill **listed**). It does NOT reconcile the **content** of
Claude's own governance context. This skill closes that gap: it updates the **prose/behavior** of
`.claude/rules/*.md` and `.claude/skills/*/SKILL.md` so they describe the engine as it is now — the drift
class that recurs is a rule that still describes the old terminal state, or a diagnostic skill that has no
class for a new failure mode. Run it on the same triggers as `/tbf-docs-sync` (a structural or behavioral
change), typically right after `/tbf-docs-sync` in [/tbf-iteration-release](../tbf-iteration-release/SKILL.md).
Same guardrail: fix the metadata, NEVER the generated clone.

## Step 1 — Change inventory (from the diff)
Read the commits / `git diff` and list, by class: new or renamed **modules / functions / helpers**; new
**CLI flags**; new **env-overridable constants**; new/changed **FSM states, routes, or terminal steps**;
new/removed **agent roles**; new **external systems/providers**; new **failure modes / crash classes**; new
**cross-cutting invariants**. Each class maps to specific rule/skill owners below.

## Step 2 — Rules pass (`.claude/rules/*.md`)
For each change class, patch the rule that owns it (don't eyeball — `grep` the rule for the stale anchor):
- **`repo-module-map`** — a new/renamed module, public function, helper, or plane member → add it to the
  correct plane list (it enumerates every `src/` SSOT).
- **`pipeline-fsm-loops`** — a new FSM state, routing edge, gate, or terminal/finalize step (e.g. a new
  success-path action) → update the matching state.
- **`run-layout-and-cli`** — a new CLI flag, run-dir kind, or layout grammar change.
- **`config-constant-convention`** — a new env-overridable `UPPER_CASE` constant → add to the enumerated list.
- **`agent-provider-model-map`** / **`agent-contracts`** / **`agent-role-registration`** — a new role,
  provider, output model, or call-path behavior (e.g. a new timeout on the structured path).
- **`workspace-topology`**, **`qa-sandbox-hardening`**, **`debugging-protocol`**, etc. — when the structural
  boundary, sandbox surface, or diagnostic procedure they describe changed.
- **A brand-new cross-cutting invariant** that future edits must honor (e.g. "sanitize every subprocess
  argv") warrants a **NEW path-scoped rule** — create it with `paths:` frontmatter covering the files it
  governs, the **Why**, the **How to apply**, and `[[links]]` to related rules.

Also keep frontmatter current: a rule's `paths:` list MUST include any new file it now governs (a rule that
covers `subprocess` safety must list a newly-added `subprocess`-spawning module).

## Step 3 — Skills pass (`.claude/skills/*/SKILL.md`)
- **`tbf-analyze-run`** — a new failure mode → add a **root-cause class** (Step 3), a **diagnostic tell** (Step 2
  if it presents unusually, e.g. a non-halt crash with no incident report), AND a trigger phrase in the
  **frontmatter `description`** (the `description` is the auto-invocation signal — a class the description
  never mentions won't pull the skill in).
- **The sync/release skills** (`/tbf-docs-sync`, `/tbf-iteration-release`, this one) — when a new sync target or
  enumeration surface appears, add it to their checklist.
- **A brand-new governance procedure** (a repeatable multi-step maintenance task) warrants a **NEW skill**
  directory `.claude/skills/<name>/SKILL.md`; then enumerate it (Step 4).

## Step 4 — Enumerate any new rule/skill
A new `.claude/skills/<name>/` MUST be named in **CLAUDE.md** (Project Knowledge skills list) AND **README**
(Developer Meta-Tools + the structure-tree comment). A new rule needs no enumeration (rules auto-load by
`paths:`), but cross-link it from related rules via `[[name]]`. (`/tbf-docs-sync`'s skill peer-check also covers
the skill enumeration — don't duplicate, just confirm.)

## Step 5 — Drift sweep (mechanical)
Pick an existing **peer** of each new element — a sibling module line in `repo-module-map`, a neighbouring
terminal state in `pipeline-fsm-loops`, a sibling root-cause class in `tbf-analyze-run` — `grep -rn` it across
`.claude/`, and confirm the new element now appears in the SAME places. Presence in only one is a miss.

## Output Format
Apply changes directly. End with a raw checklist of touched `.claude/**` files. Zero conversational text.
