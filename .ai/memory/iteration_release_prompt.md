---
name: iteration-release-prompt
description: Generic prompt template for analyzing and documenting iteration releases with architectural context
metadata:
  type: reference
---
# Iteration Release Documentation Prompt Template

Analyze the current state of the codebase and document the release of Iteration [ITERATION_NUMBER] ([SHORT_TECHNICAL_FEATURE_NAME]).

## === ARCHITECTURAL CONTEXT FOR ITERATION [ITERATION_NUMBER] ===

In this iteration, the following problem was resolved: [DESCRIPTION_OF_THE_ARCHITECTURAL_OR_LOGICAL_PROBLEM_BEFORE_CHANGES].

### Key implementations:

1. **[COMPONENT/FEATURE 1]**:
   - [Specific code/model changes].
   - [Architectural benefit gained or bug eliminated].

2. **[COMPONENT/FEATURE 2]**:
   - [Specific code/model changes].
   - [Architectural benefit gained or bug eliminated].

3. **[CHANGES IN AGENT PROMPTS/CONSTRAINTS]** (if applicable):
   - [Core of the new constraint or rule].
   - [Which anti-pattern it prevents].

## === GOVERNING SKILLS (`.ai/skills/`) ===

This is a metadata-synchronization task, so `CLAUDE.md` mandates reading and following the
relevant skill files in `.ai/skills/` before mutating any document. Each TASK step below is
driven by one skill — load it first and obey its Protocol and Output Format:

- **`.ai/skills/adr_generation.md`** — generate the Architecture Decision Record (MADR format,
  next free sequence number in `docs/adr/`). Aborts if no core architectural change occurred.
- **`.ai/skills/docs_sync.md`** — factual sync of `CHANGELOG.md` (Keep a Changelog blocks) and
  `README.md` (new CLI flags, env vars, directory/topology, execution commands).
- **`.ai/skills/practicum_update.md`** — distill the generalizable engineering lesson into the
  `## Key Engineering Takeaways` list in `PRACTICUM.md`, formatted
  `* **[Concept]** *([ADR link])*: [explanation]`.

## === TASK ===

1. **ADR** — run `.ai/skills/adr_generation.md`: create `docs/adr/NNNN-[slug].md` (next sequence
   number) documenting the iteration's architectural decision in MADR format
   (Title, Status, Context, Decision, Consequences).
2. **Archive** — create `docs/archive/iteration_[ITERATION_NUMBER]/iteration_[ITERATION_NUMBER]_README.md`.
   Structure: Problem Statement, Implemented Solutions, Metrics/Logs analysis. Link it to the ADR.
3. **CHANGELOG + README** — run `.ai/skills/docs_sync.md`: add the release section to
   `CHANGELOG.md` (linked to the new ADR) and patch `README.md` for any new CLI args, env vars,
   directory/topology, or execution-graph changes.
4. **PRACTICUM** — run `.ai/skills/practicum_update.md`: add a "Development Steps" row and a new
   "Key Engineering Takeaways" bullet capturing [MAIN_ENGINEERING_TAKEAWAY_OF_THIS_ITERATION],
   pointing the ADR reference at the file created in step 1.
5. **Verify** — every cross-link resolves (ADR ↔ CHANGELOG ↔ PRACTICUM ↔ archive) and every path
   used matches the current repository topology.

## Placeholders to customize:

- `[ITERATION_NUMBER]` — numeric iteration identifier
- `[SHORT_TECHNICAL_FEATURE_NAME]` — concise feature/fix name
- `[DESCRIPTION_OF_THE_ARCHITECTURAL_OR_LOGICAL_PROBLEM_BEFORE_CHANGES]` — problem statement
- `[COMPONENT/FEATURE N]` — specific component modified
- `[Specific code/model changes]` — details of implementation
- `[Architectural benefit gained or bug eliminated]` — impact/value
- `[CHANGES IN AGENT PROMPTS/CONSTRAINTS]` — optional agent/constraint updates
- `[MAIN_ENGINEERING_TAKEAWAY_OF_THIS_ITERATION]` — key learning/pattern
