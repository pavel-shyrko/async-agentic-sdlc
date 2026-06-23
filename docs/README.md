# Documentation

The front door to the **token-burners-factory** docs. Start with the architecture, then drill into setup,
decisions, or release history as needed.

## 🧭 Start here
| If you want to… | Read |
|---|---|
| Understand **what the system is and how it's built** | [ARCHITECTURE.md](ARCHITECTURE.md) — C4 context / container / FSM diagrams (Mermaid) |
| **Run it locally** | [guides/setup.md](guides/setup.md) → [guides/docker-on-windows.md](guides/docker-on-windows.md) |
| **Deploy autonomously** (`--scaffold-deploy`) | [guides/devops_setup.md](guides/devops_setup.md) — GitHub org → GCP WIF (passwordless CI/CD) |
| Know **why** a design choice was made | [decisions/](decisions/README.md) — the ADR log (0000–0021) |
| See **what changed each release** | [../CHANGELOG.md](../CHANGELOG.md) + [releases/](releases/) write-ups |
| Find the **distilled engineering lessons** | [../PRACTICUM.md](../PRACTICUM.md) |
| See **what's still open** | [BACKLOG.md](BACKLOG.md) |

## 📂 Layout
```
docs/
  ARCHITECTURE.md       # C4 L1/L2/L3 + end-to-end sequence (Mermaid)
  guides/               # environment setup
    setup.md
    docker-on-windows.md
    devops_setup.md       # GitHub org → GCP WIF (passwordless deploy)
  decisions/            # Architecture Decision Records (MADR) + index
    README.md
    0000-…md … 0021-…md
  releases/             # per-iteration release write-ups
    iteration_15/ … iteration_21/
  BACKLOG.md            # open, deferred fixes (prioritized)
```

## 🗂️ Beyond docs/
- **[../README.md](../README.md)** — project mission, quick-start CLI, FinOps, and the meta-tool skills.
- **[../CLAUDE.md](../CLAUDE.md)** — CLI governance, dev commands, and architecture guardrails.
- **`.claude/rules/`** — auto-loaded engineering knowledge (path-scoped: a rule loads only when you touch a
  file its `paths:` frontmatter matches — no manual step). Notable:
  [repo-module-map](../.claude/rules/repo-module-map.md) (where things live),
  [pipeline-fsm-loops](../.claude/rules/pipeline-fsm-loops.md) (the FSM cycle),
  [agent-contracts](../.claude/rules/agent-contracts.md) (per-agent I/O),
  [agent-provider-model-map](../.claude/rules/agent-provider-model-map.md) (Gemini vs Claude routing),
  [config-constant-convention](../.claude/rules/config-constant-convention.md) (env-overridable knobs),
  [subprocess-and-external-call-safety](../.claude/rules/subprocess-and-external-call-safety.md) (sanitize
  every argv + time-bound every blocking call),
  [debugging-protocol](../.claude/rules/debugging-protocol.md) (diagnose a run).
- **`.claude/skills/`** — invokable meta-tools (type `/name`, or let Claude auto-trigger them from their
  description): `/adr-generation`, `/docs-sync`, `/claude-context-sync` (sync the rules + skills above to the
  code), `/practicum-update`, `/iteration-release` (orchestrates the four sync skills + the archive),
  `/analyze-run` (diagnose a run), `/agent-role-scaffold` (add a new structured agent role end-to-end).
  (Full usage in [../README.md](../README.md) → Developer Meta-Tools.)
- **`prompts/`** — the runtime agent prompts (`prompts/system/*.md`) and gated skill fragments
  (`prompts/skills/*.md`). These configure the pipeline agents themselves, not the docs.
