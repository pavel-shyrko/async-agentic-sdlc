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
1. **ADR** — run the `adr-generation` skill: create `docs/adr/NNNN-[slug].md` (next sequence number) in
   MADR format (Title, Status, Context, Decision, Consequences).
2. **Archive** — create `docs/archive/iteration_[ITERATION_NUMBER]/iteration_[ITERATION_NUMBER]_README.md`
   with: Problem Statement, Implemented Solutions, Metrics/Logs analysis. Link it to the ADR.
3. **CHANGELOG + README** — run the `docs-sync` skill: add the release section to `CHANGELOG.md` (linked
   to the new ADR) and patch `README.md` for any new CLI args, env vars, directory/topology, or
   execution-graph changes.
4. **PRACTICUM** — run the `practicum-update` skill: add a "Development Steps" row and a new "Key
   Engineering Takeaways" bullet capturing the main engineering lesson, pointing the ADR reference at the
   file created in step 1.
5. **Verify** — every cross-link resolves (ADR ↔ CHANGELOG ↔ PRACTICUM ↔ archive) and every path used
   matches the current repository topology.

## Placeholders to customize
- `[ITERATION_NUMBER]` — numeric iteration identifier.
- `[SHORT_TECHNICAL_FEATURE_NAME]` — concise feature/fix name.
- Problem statement, per-component changes, and the main engineering takeaway — fill from the actual diff.
