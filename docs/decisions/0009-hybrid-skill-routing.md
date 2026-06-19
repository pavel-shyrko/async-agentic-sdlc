# 0009 — Hybrid Skill Routing

## Status

Accepted

## Context

Iteration 008 decomposed the monolithic inline agent prompts into discrete `prompts/skills/*.md`
files, but the composition layer (`get_skill(skill_name)`) still required each agent node to
**hardcode** the exact list of skills it loaded. That left three structural defects:

1. **Open-Closed Principle (OCP) violation** — adding a new domain guardrail (e.g. a math or
   geometry rule) meant editing and redeploying the agent's Python module to insert another
   `get_skill(...)` call. Behavior could not be extended without modifying core orchestrator code.
2. **Cross-agent context leakage** — because the node author chose the skill list by hand, broadly
   applicable rules were copy-pasted across nodes and narrow rules drifted into agents they did not
   apply to, polluting unrelated reasoning windows and causing spurious refusals.
3. **Duplicated composition + brittle injection** — every node repeated the same load-and-concatenate
   boilerplate, and naive `.format()` over a skill body crashed with `KeyError` whenever the body
   contained a literal `{}` (JSON examples, code blocks, dict literals).

## Decision

Composition was inverted into a single declarative router, `build_agent_context(node, ctx, …)` in
`src/core/prompts.py`. Nodes no longer name skills; they declare *who they are*, and skills declare
*where they apply*. Three mechanisms make this work:

- **Declarative YAML frontmatter** — every skill file carries a leading `---` block with `type`,
  `nodes`, and `triggers`. A stdlib-only parser (`_parse_frontmatter`, regex + line split, **no
  pyyaml dependency**) extracts it. The router iterates all skills, includes a skill only when the
  current node appears in its `nodes`, then applies a per-`type` gate:
  - `global` → always included;
  - `topology` → always, and its body is `.format(**topology_kwargs)`-ed for path/structure injection;
  - `stateful` → included only on a retry pass (`is_retry`);
  - `domain` → included when `triggers ∩ ctx.contract.domain_tags` is non-empty.
- **Dependency-free prompt-based semantic fallback** — on a `domain` tag miss,
  `fallback_semantic_search` issues a structured-LLM relevance check (`SkillRelevance`, reviewer
  model, reusing the existing `run_structured_llm` infra — no embeddings SDK) and includes the skill
  when the score exceeds `0.7`. Any error degrades safely to exclusion.
- **Safe `.replace()` template injection** — the `{strict_type_validation_rules}` placeholder is
  filled with a brace-safe `str.replace()`, so skill bodies may freely contain literal `{}` without
  crashing the router. Only `topology` bodies are `.format()`-ed (the one place positional template
  substitution is intended).

All four agent modules (`architect`, `developer`, `qa`, `reviewer`) were refactored to call
`build_agent_context`, eliminating every hardcoded `get_skill(...)` composition call from node code.

## Consequences

- **Pros**: OCP-compliant horizontal scaling — new domain expertise is added by dropping a tagged
  markdown file into `prompts/skills/`, with **zero** changes to the orchestrator or agent nodes;
  cross-agent leakage is eliminated because each node receives only the skills that target it;
  composition boilerplate is centralized in one router; injection is `KeyError`-safe for arbitrary
  JSON/code in skill bodies; the semantic fallback catches relevant skills whose authors forgot a
  trigger tag, all with **no new runtime dependencies** (regex parser + reuse of the structured-LLM
  path).
- **Cons / constraints**: a `domain` tag miss costs an extra LLM round-trip (added latency and
  tokens) and is probabilistic — the `0.7` threshold is hand-tuned, and a transient LLM error
  silently degrades to *exclusion*, so a relevant skill can be dropped on a bad call; the frontmatter
  parser is a deliberate YAML subset (scalar + `[a, b]` list only), so richer YAML in a skill header
  is unsupported; skill targeting now lives in file metadata rather than in code, so a malformed
  `nodes`/`type` field fails open (the skill is silently skipped) rather than raising at import time.
