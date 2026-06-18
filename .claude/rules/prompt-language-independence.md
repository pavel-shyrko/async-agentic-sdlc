---
paths:
  - "prompts/system/*.md"
  - "prompts/skills/*.md"
---

# Prompt language-independence

All agent **system prompts** (`prompts/system/*.md` — techlead, developer, qa, reviewer, po, sa, tpm) and
all **skills** (`prompts/skills/*.md`) must be written language-independently. The one exception: a skill
whose frontmatter metadata explicitly declares a language may be language-specific.

**Why:** The pipeline is multi-stack (the TechLead declares the target language into
`TechLeadContract.domain_tags`, which routes downstream agents). A normative instruction that assumes
Python (e.g. `ImportError`, `test_*.py`, `NameError`, `assertEqual`, `isclose`, `unittest`) silently
breaks for dotnet/TypeScript/etc. repos.

**How to apply:**
- Replace single-language tokens with neutral phrasing: `ImportError`/`ModuleNotFoundError` → "an unresolved-import / module-resolution error (in any language)"; `NameError` → "undefined-symbol/reference error"; `test_*.py` → "a test file"; `cli.py` → "a pre-existing consumer/entry-point file"; "compiles" → "builds".
- **Skill exemption is by frontmatter:** skills are gated in [skill-routing-frontmatter](skill-routing-frontmatter.md). `type: domain` with language `triggers` (e.g. `triggers: [python]`, files `python_qa.md`/`python_core.md`) are loaded ONLY via the language router → may be language-specific. `type: global|topology|stateful` apply to EVERY language → must be neutral.
- **Allowed even in neutral prompts:** multi-language illustrative examples that span stacks (e.g. "Python: `from ... import ...`; TypeScript: `import ... from ...`"), the TechLead language-declaration rule, schema/tool names (`files_to_modify`, `git add -A`), and concrete format sample paths that necessarily carry an extension.
- Guardrail: never edit `prompts/system/` unless explicitly ordered by the Human (CLAUDE.md).
