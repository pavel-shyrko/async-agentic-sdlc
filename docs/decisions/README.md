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
| [0012](0012-virtual-separation-monorepo-planes.md) | Virtual separation: `nexus` / `executor` / `shared` planes by import discipline (logical before physical). *(superseded by 0021.)* |
| [0015](0015-unified-project-run-topology.md) | One run-layout SSOT + self-describing checkpoint (`kind`); per-project `project.json` umbrella. |
| [0021](0021-physical-three-plane-split.md) | Physical split: `nexus` (control + FSM) / `development` (dev agents + gates) / `deployment` (devops + scaffold); `src/executor/` removed, lazy-import seam for the `deployment → nexus` SSOT back-edge (supersedes 0012). |
| [0022](0022-application-wide-finops-budget.md) | Application-wide **money-only** FinOps budget: one `PIPELINE_APP_BUDGET_USD` (or `--budget`) threaded as the remaining budget per ticket, accumulated in `BatchState.app_telemetry` (resume-safe + re-budgetable); token ceiling removed; per-role/per-plane/time reporting (`app_finops_report.json`). |

## QA Test Maintenance
| ADR | Decision |
|---|---|
| [0013](0013-structured-test-maintenance-ast-pruning.md) | QA returns deltas; the engine does deterministic AST surgery (preserve/dedupe/merge). |
| [0014](0014-language-neutral-qa-whole-file-assembly.md) | Language-neutral QA — correctness rules move to skills; whole-file assembly. |

## Self-Healing
| ADR | Decision |
|---|---|
| [0016](0016-arbiter-contract-self-healing.md) | Arbiter agent — autonomous contract self-healing (a third FSM route); fail-fast RECITATION + engine-injected baseline files. |
| [0024](0024-routing-coherence-reconciler.md) | Routing-coherence reconciler — code-enforces the feedback-routing invariant: `ReviewReport` biconditional validator (`payload ⟺ rejection`) + required `dev_evidence_citation` on a production rejection (#11/#18), and `reconcile_feedback_routing` makes Arbiter `developer`/`qa` routes authoritative over a Reviewer misroute (#25). |

## Orchestration & Entrypoint
| ADR | Decision |
|---|---|
| [0017](0017-nexus-executor-auto-dispatch.md) | `--auto-execute`: plan then auto-dispatch the Executor for the first ticket; extract `run_executor` / `prepare_ticket_run` (E1). |
| [0018](0018-auto-merge-pr-loop-closure.md) | `--auto-merge`: on success open + approve + squash-merge a PR into `base_branch` via a provider-agnostic `gh`-backed forge seam (E2); argv-NUL + Gemini-timeout boundary hardening. |
| [0019](0019-cyclical-multi-ticket-orchestration.md) | `--auto-execute` drives ALL planned tickets to `main` in order via `run_batch` + a resumable `BatchState`; a catchable `PipelineHalt` replaces the abort `sys.exit` so a mid-batch halt stops cleanly and `--resume` continues (E3). |
| [0023](0023-autonomous-release-tagging.md) | `--release`: as a completed build's final step `run_batch` pushes a repo-derived `v*` tag (`compute_next_tag` + `forge.push_tag`) to trip the tag-gated deploy/release workflow (E6); idempotent via `BatchState.released_tag`; decoupled from `--scaffold-deploy`; engine pushes only a tag (never holds cloud creds). |

## Deployment & Quality Gates
| ADR | Decision |
|---|---|
| [0020](0020-deploy-scaffolding-and-lint-gate.md) | `--scaffold-deploy`: a post-batch `devops` agent generates + merges the app's CI/CD config (archetype-aware Dockerfile + GitHub Actions, Cloud Run via WIF, E4); a HARD engine lint gate (`run_lint_gate`, FSM step 3.6) with a per-env `lint_cmd` SSOT makes the generated strict CI green by construction. |
