# Documentation

The front door to the **async-agentic-sdlc** docs. Start with the architecture, then drill into setup,
decisions, or release history as needed.

## 🧭 Start here
| If you want to… | Read |
|---|---|
| Understand **what the system is and how it's built** | [ARCHITECTURE.md](ARCHITECTURE.md) — C4 context / container / FSM diagrams (Mermaid) |
| **Run it locally** | [guides/setup.md](guides/setup.md) → [guides/docker-on-windows.md](guides/docker-on-windows.md) |
| Know **why** a design choice was made | [decisions/](decisions/README.md) — the ADR log (0000–0016) |
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
  decisions/            # Architecture Decision Records (MADR) + index
    README.md
    0000-…md … 0016-…md
  releases/             # per-iteration release write-ups
    iteration_15/ · iteration_16/
  BACKLOG.md            # open, deferred fixes (prioritized)
```

## 🗂️ Beyond docs/
- **[../README.md](../README.md)** — project mission, quick-start CLI, FinOps, and the meta-tool skills.
- **[../CLAUDE.md](../CLAUDE.md)** — CLI governance, dev commands, and architecture guardrails.
- **`.claude/rules/`** — auto-loaded engineering knowledge (path-scoped). Notable:
  [repo-module-map](../.claude/rules/repo-module-map.md) (where things live),
  [pipeline-fsm-loops](../.claude/rules/pipeline-fsm-loops.md) (the FSM cycle),
  [agent-contracts](../.claude/rules/agent-contracts.md) (per-agent I/O),
  [agent-provider-model-map](../.claude/rules/agent-provider-model-map.md) (Gemini vs Claude routing),
  [debugging-protocol](../.claude/rules/debugging-protocol.md) (diagnose a run).
- **`.claude/skills/`** — invokable meta-tools: `/adr-generation`, `/docs-sync`, `/practicum-update`,
  `/iteration-release`, `/analyze-run`. (Documented in [../README.md](../README.md) → Developer Meta-Tools.)
- **`prompts/`** — the runtime agent prompts (`prompts/system/*.md`) and gated skill fragments
  (`prompts/skills/*.md`). These configure the pipeline agents themselves, not the docs.
