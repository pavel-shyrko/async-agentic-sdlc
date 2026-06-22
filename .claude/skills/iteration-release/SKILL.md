---
name: iteration-release
description: Document a full iteration release end-to-end — ADR + archive + CHANGELOG/README sync + PRACTICUM takeaway, with all cross-links resolved. Use when the user asks to document or release an iteration. Orchestrates the adr-generation, docs-sync, and practicum-update skills in sequence.
argument-hint: "[iteration-number] [short-feature-name]"
---

# Iteration Release Documentation

Document the release of Iteration `[ITERATION_NUMBER]` (`[SHORT_TECHNICAL_FEATURE_NAME]`). This is a
metadata-synchronization workflow that runs three sub-skills in order. Each step is driven by one skill —
follow its Protocol and Output Format.

## Architectural context to capture
Before mutating any document, establish: the architectural/logical problem that existed before the
changes, the key implementations (specific code/model changes + the benefit gained or bug eliminated),
and any agent-prompt/constraint changes (the new rule + the anti-pattern it prevents).

## Tasks
1. **ADR** — run the `adr-generation` skill: create `docs/decisions/NNNN-[slug].md` (next sequence number) in
   MADR format (Title, Status, Context, Decision, Consequences). **If the architectural ADR for this
   change was already created during implementation** (a large feature often lands its own ADR with the
   code), do NOT create a duplicate — `adr-generation` aborts when no *new* architectural change remains;
   identify the existing `docs/decisions/NNNN` and use it as this iteration's ADR for all the cross-links below.
2. **Archive** — create `docs/releases/iteration_[ITERATION_NUMBER]/iteration_[ITERATION_NUMBER]_README.md`
   with: Problem Statement, Implemented Solutions, Metrics/Logs analysis (use real numbers — e.g.
   `git diff --stat <prev-tag-or-commit>` for the footprint, plus any validation-run outcomes). Link it to
   the ADR (and the ADR/CHANGELOG should link back to it).
3. **CHANGELOG + README + ARCHITECTURE** — run the `docs-sync` skill (follow its full checklist): add the
   release section to `CHANGELOG.md` (linked to the new ADR + the archive) and patch `README.md`. Then run
   docs-sync's **Peer-enumeration drift sweep** (its Protocol step 5) — the mechanical sibling-grep over
   agents, the `prompts/system/` list, the ADR `0000–NNNN` range, version/iteration stamps, env knobs, and
   skills. **Re-verify the FULL peer-sets, not just what this iteration added** — these enumerations carry
   drift from PRIOR releases (a role added two releases ago can still be missing from one doc), and a
   release is the moment to catch it. **If this iteration changed structure** (a new/removed agent role, an
   FSM state/route, an external system, or a plane/container/store), docs-sync's **Architecture Diagram
   Sync** step also updates the C4 diagrams + component table in `docs/ARCHITECTURE.md` — skip it only for
   pure behavior/bugfix iterations.
4. **PRACTICUM** — run the `practicum-update` skill: add one or more new "Key Engineering Takeaways"
   bullet(s) at the TOP of that section, each capturing a generalizable lesson and linking the iteration's
   ADR (from step 1). (Only add a "Development Steps" row if that table actually exists in the current
   `PRACTICUM.md` — the present structure is the Takeaways list, so do not invent a table.)
5. **Verify** — concretely confirm every cross-link resolves and every path matches the current topology:
   the ADR, archive, and any referenced rule/skill files EXIST on disk; relative paths from the archive
   (`../../decisions/…`, `../../../CHANGELOG.md`) and the CHANGELOG/README/PRACTICUM (`./docs/decisions/…`) point at real
   files; and the CHANGELOG version heading + ADR slug match. Then run the drift-sweep grep checks
   mechanically (don't eyeball): the highest `docs/decisions/NNNN` equals the upper bound of every
   `0000–NNNN` range string; no stale prior-version stamp (`v<old>`) remains in any doc that means "current
   state"; the agent/prompt/skill peer-sets resolve to identical file-hit sets (per docs-sync step 5); and
   `ls src/*/agents/*.py` + `ls prompts/system/` match what the README enumerates. Fix any miss before finishing.

## Placeholders to customize
- `[ITERATION_NUMBER]` — numeric iteration identifier.
- `[SHORT_TECHNICAL_FEATURE_NAME]` — concise feature/fix name.
- Problem statement, per-component changes, and the main engineering takeaway — fill from the actual diff.
