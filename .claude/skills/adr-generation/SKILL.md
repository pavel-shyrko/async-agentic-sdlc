---
name: adr-generation
description: Generate an Architecture Decision Record (MADR format) documenting a systemic or architectural change. Use when the user asks to write/record an ADR, document an architectural decision, or after changes to FSM states, routing logic, new integrations, structural refactors, or dependency-injection shifts. Aborts if no core architectural change occurred.
---

# Architecture Decision Record (ADR) Generation

## Context
Document systemic or architectural changes in the codebase. Focus strictly on the "Why" and the
high-level "What".

## Protocol
1. **Diff Analysis**: Analyze the `git diff` against the base branch or target commits.
2. **Trigger Condition**: Determine if core architectural changes occurred (e.g. new FSM states, routing logic changes, new integrations, structural refactoring, dependency injection shifts). If NO, abort with: "No ADR generation required."
3. **File Creation**: Find the next available sequence number in `docs/decisions/` (e.g. if `0014-xxx.md` is the highest, use `0015-xxx.md`).
4. **MADR Formatting**:
   - `Title`: Concise technical description.
   - `Status`: Accepted.
   - `Context`: What exact problem caused this change?
   - `Decision`: What was implemented at the architecture level?
   - `Consequences`: Architectural pros and cons (e.g. token-cost reduction, increased latency, tighter isolation, strict typing).

## Output Format
Output strictly the file path and the raw markdown content. No conversational text.
