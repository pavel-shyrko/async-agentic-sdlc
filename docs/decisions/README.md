# Architecture Decision Records

The chronological decision log for the engine, in [MADR](https://adr.github.io/madr/) format (Context →
Decision → Consequences). Each release in [../../CHANGELOG.md](../../CHANGELOG.md) links the ADR that
drove it; the distilled lessons live in [../../PRACTICUM.md](../../PRACTICUM.md). New ADRs are generated
with the `/adr-generation` skill (next free sequence number).

> Read top-to-bottom for the project's evolution, or jump by theme below. ADRs frequently *extend* earlier
> ones (e.g. 0016 extends 0001/0003/0006).

## Foundations
| ADR | Decision |
|---|---|
| [0000](0000-cloud-infra-fsm-research.md) | Custom Python/Pydantic FSM (not LangGraph); hybrid Gemini/Claude routing; context+prompt caching. |
| [0001](0001-baseline-sequential-loop.md) | Baseline sequential loop; QA boundary isolation (Developer may never write tests). |
| [0002](0002-async-qa-node-isolation.md) | Async fork-join — dedicated QA generator before code; concurrent test + SAST validation. |
| [0003](0003-dual-channel-observability.md) | Dual-channel observability (console INFO + rotating audit DEBUG); native token tracking; Gemini 2.5 routing. |

## Modularization, Sandbox & FinOps
| ADR | Decision |
|---|---|
| [0004](0004-modularization-sandbox-hardening.md) | Monolith → module architecture; dual-mount Docker (`src/` RO, `artifacts/` RW). |
| [0011](0011-secure-sandbox-and-finops-telemetry.md) | Loopback-only Docker API; real-time Financial Circuit Breaker (Decimal cost math); language-neutral contracts. |

## Git State, Sessions & Resume
| ADR | Decision |
|---|---|
| [0005](0005-git-driven-state-tracking-qa-fanout.md) | Git-diff state tracking (no glob scans); QA fan-out — one LLM call per module. |
| [0006](0006-fsm-state-serialization-resume.md) | Rolling `checkpoint.json` + `--resume`; persisted `current_attempt`; resume bypasses finished nodes. |
| [0008](0008-git-anchored-sessions-atomic-commit.md) | Git-anchored sessions; the index as unit-of-work; single atomic `feat(<ticket>):` commit on success. |

## Prompts, Schema & Skill Routing
| ADR | Decision |
|---|---|
| [0007](0007-prompt-schema-layer-separation.md) | Schema `Field`s carry structure only; behavioral rules move to system prompts. |
| [0009](0009-hybrid-skill-routing.md) | Declarative skill frontmatter (`type`/`nodes`/`triggers`) + semantic fallback — Open-Closed scaling. |
| [0010](0010-fast-fail-documentation-guardrail.md) | Zero-token lexical guardrail + graduated triage (justified / hallucinated / legacy) with capped reroutes. |

## Planes & Run Topology
| ADR | Decision |
|---|---|
| [0012](0012-virtual-separation-monorepo-planes.md) | Virtual separation: `nexus` / `executor` / `shared` planes by import discipline (logical before physical). |
| [0015](0015-unified-project-run-topology.md) | One run-layout SSOT + self-describing checkpoint (`kind`); per-project `project.json` umbrella. |

## QA Test Maintenance
| ADR | Decision |
|---|---|
| [0013](0013-structured-test-maintenance-ast-pruning.md) | QA returns deltas; the engine does deterministic AST surgery (preserve/dedupe/merge). |
| [0014](0014-language-neutral-qa-whole-file-assembly.md) | Language-neutral QA — correctness rules move to skills; whole-file assembly. |

## Self-Healing
| ADR | Decision |
|---|---|
| [0016](0016-arbiter-contract-self-healing.md) | Arbiter agent — autonomous contract self-healing (a third FSM route); fail-fast RECITATION + engine-injected baseline files. |
