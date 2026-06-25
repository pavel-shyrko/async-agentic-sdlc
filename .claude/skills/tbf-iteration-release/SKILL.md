---
name: tbf-iteration-release
description: Document a full iteration release end-to-end — ADR + archive + CHANGELOG/README sync + Claude rules/skills sync + PRACTICUM takeaway, with all cross-links resolved. Use when the user asks to document or release an iteration. Orchestrates the tbf-adr-generation, tbf-docs-sync, tbf-claude-context-sync, and tbf-practicum-update skills in sequence.
argument-hint: "[iteration-number] [short-feature-name]"
disable-model-invocation: true
---

# Iteration Release Documentation

Document the release of Iteration `[ITERATION_NUMBER]` (`[SHORT_TECHNICAL_FEATURE_NAME]`). This is a
metadata-synchronization workflow that runs four sub-skills in order. Each step is driven by one skill —
follow its Protocol and Output Format.

## Architectural context to capture
Before mutating any document, establish: the architectural/logical problem that existed before the
changes, the key implementations (specific code/model changes + the benefit gained or bug eliminated),
and any agent-prompt/constraint changes (the new rule + the anti-pattern it prevents).

## Tasks
1. **ADR** — run the `/tbf-adr-generation` skill: create `docs/decisions/NNNN-[slug].md` (next sequence number) in
   MADR format (Title, Status, Context, Decision, Consequences). **If the architectural ADR for this
   change was already created during implementation** (a large feature often lands its own ADR with the
   code), do NOT create a duplicate — `/tbf-adr-generation` aborts when no *new* architectural change remains;
   identify the existing `docs/decisions/NNNN` and use it as this iteration's ADR for all the cross-links below.
2. **Archive** — create `docs/releases/iteration_[ITERATION_NUMBER]/iteration_[ITERATION_NUMBER]_README.md`
   with: Problem Statement, Implemented Solutions, Metrics/Logs analysis (use real numbers — e.g.
   `git diff --stat <prev-tag-or-commit>` for the footprint, plus any validation-run outcomes). Link it to
   the ADR (and the ADR/CHANGELOG should link back to it).
3. **CHANGELOG + README + ARCHITECTURE** — run the `/tbf-docs-sync` skill (follow its full checklist): add the
   release section to `CHANGELOG.md` (linked to the new ADR + the archive) and patch `README.md`. Then run
   `/tbf-docs-sync`'s **Peer-enumeration drift sweep** (its Protocol step 5) — the mechanical sibling-grep over
   agents, the `prompts/system/` list, the ADR `0000–NNNN` range, version/iteration stamps, env knobs, and
   skills. **Re-verify the FULL peer-sets, not just what this iteration added** — these enumerations carry
   drift from PRIOR releases (a role added two releases ago can still be missing from one doc), and a
   release is the moment to catch it. **If this iteration changed structure** (a new/removed agent role, an
   FSM state/route, an external system, or a plane/container/store), `/tbf-docs-sync`'s **Architecture Diagram
   Sync** step also updates the C4 diagrams + component table in `docs/ARCHITECTURE.md` — skip it only for
   pure behavior/bugfix iterations.
4. **Claude operating-context** — run the `/tbf-claude-context-sync` skill: reconcile the CONTENT of
   `.claude/rules/*.md` and `.claude/skills/*/SKILL.md` to this iteration's change inventory (new module/fn
   in `repo-module-map`; new FSM/terminal step in `pipeline-fsm-loops`; new CLI flag in `run-layout-and-cli`;
   new env knob in `config-constant-convention`; new role/provider/timeout behavior in `agent-provider-model-map`;
   a new failure mode → new `tbf-analyze-run` root-cause class + trigger). `/tbf-docs-sync` (step 3) only checks
   that rules/skills *enumerate* peers; this updates their *prose/behavior*, and creates a NEW rule/skill when
   the iteration introduces a cross-cutting invariant or a repeatable governance procedure.
5. **PRACTICUM** — run the `/tbf-practicum-update` skill: add one or more new "Key Engineering Takeaways"
   bullet(s) at the TOP of that section, each capturing a generalizable lesson and linking the iteration's
   ADR (from step 1). (Only add a "Development Steps" row if that table actually exists in the current
   `PRACTICUM.md` — the present structure is the Takeaways list, so do not invent a table.)
6. **Verify** — concretely confirm every cross-link resolves and every path matches the current topology:
   the ADR, archive, and any referenced rule/skill files EXIST on disk; relative paths from the archive
   (`../../decisions/…`, `../../../CHANGELOG.md`) and the CHANGELOG/README/PRACTICUM (`./docs/decisions/…`) point at real
   files; and the CHANGELOG version heading + ADR slug match. Then run the drift-sweep grep checks
   mechanically (don't eyeball): the highest `docs/decisions/NNNN` equals the upper bound of every
   `0000–NNNN` range string; no stale prior-version stamp (`v<old>`) remains in any doc that means "current
   state"; the agent/prompt/skill peer-sets resolve to identical file-hit sets (per `/tbf-docs-sync` step 5); and
   `ls src/*/agents/*.py` + `ls prompts/system/` match what the README enumerates. If step 4 created a NEW
   skill, confirm it is named in CLAUDE.md AND README Meta-Tools (`ls .claude/skills/` vs both); a NEW rule
   has a valid `paths:` frontmatter and resolvable `[[links]]`. Fix any miss before finishing.

## Placeholders to customize
- `[ITERATION_NUMBER]` — numeric iteration identifier.
- `[SHORT_TECHNICAL_FEATURE_NAME]` — concise feature/fix name.
- Problem statement, per-component changes, and the main engineering takeaway — fill from the actual diff.
