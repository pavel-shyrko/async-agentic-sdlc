---
name: practicum-update
description: Distill a generalizable engineering lesson into PRACTICUM.md's "Key Engineering Takeaways" after a major milestone or complex iteration. Use when the user asks to update the practicum or capture an engineering takeaway/pattern/anti-pattern from recent work. Aborts if the changes were purely routine.
---

# Engineering Manifest & Practicum Update

## Context
Run after a major milestone or highly complex iteration to distill new engineering wisdom, patterns, or
anti-patterns into the project's executive summary (`PRACTICUM.md`).

## Protocol
1. **Context Gathering**: Read the latest additions to `CHANGELOG.md` and the most recently generated `docs/decisions/*.md` file.
2. **Analysis**: Determine if the recent changes yielded a *generalizable engineering lesson* (e.g. handling LLM context limits, managing agent state, overriding model biases, FinOps optimizations). If the changes were purely routine (e.g. fixing a minor bug, updating a README), abort with: "No new engineering takeaways derived."
3. **Drafting the Takeaway**:
   - Formulate a strong, concise title for the concept.
   - Write 2-3 sentences explaining the fundamental problem and the generalized architectural solution.
4. **Target Alignment**:
   - Read `PRACTICUM.md`.
   - Append the new takeaway to the `## Key Engineering Takeaways` list.
   - Use the exact format: `* **[Concept Name]** *([Link to relevant ADR])*: [Explanation]`.

## Output Format
Apply the changes directly to `PRACTICUM.md` or output a strict `diff` block. Zero conversational text.
