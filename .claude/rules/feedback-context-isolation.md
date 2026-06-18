---
paths:
  - "CLAUDE.md"
  - "prompts/skills/engineering_guide.md"
---

# Boundary constraint: CLAUDE.md vs prompts/

1. `CLAUDE.md` is STRICTLY reserved for CLI token economy, workspace boundaries, and terminal commands.
2. IT IS FORBIDDEN to place software-engineering rules, code-style guidelines, testing frameworks (e.g. "no pytest"), or security requirements in `CLAUDE.md`.
3. All runtime rules for FSM pipeline agents MUST be written to `prompts/skills/engineering_guide.md` (injected by the Python orchestrator).
4. TRIGGER: If instructed to update "project coding rules" or "style guide", you MUST mutate `prompts/skills/engineering_guide.md`, never `CLAUDE.md`.

(Distinct from the runtime Developer/QA feedback-channel isolation, which lives in
[pipeline-fsm-loops](pipeline-fsm-loops.md).)
