---
name: skill_routing_frontmatter
description: "How prompts/skills/*.md are gated into an agent's context via frontmatter type/nodes/triggers in build_agent_context."
metadata: 
  node_type: memory
  type: reference
  originSessionId: dc24814e-6def-42da-ada4-51b4e799e49a
---

Skills in `prompts/skills/*.md` are declaratively assembled into an agent's prompt by `build_agent_context()` in [src/shared/core/prompts.py](src/shared/core/prompts.py). Each skill has `---`-delimited frontmatter parsed by `_parse_frontmatter` (stdlib only; `[a, b]` → list).

Gating per skill:
- `nodes: [...]` — only included for those agent nodes (techlead/developer/qa/reviewer).
- `type:` decides the include gate:
  - `global` → always included.
  - `topology` → always; body is `.format(**topology_kwargs)`-ed.
  - `stateful` → only on retry (`is_retry`).
  - `domain` → included when its `triggers` intersect `inferred_tags ∪ contract.domain_tags`; on a miss, `fallback_semantic_search` (LLM relevance > 0.7) decides.
- `{strict_type_validation_rules}` placeholder is brace-safely `.replace()`-d so skill bodies may contain literal `{}`.

The language-gated skills are `type: domain` with a language in `triggers` (e.g. `python_qa.md`, `python_core.md` → `triggers: [python]`). This is the metadata exemption referenced by [[prompt_language_independence]].
