---
paths:
  - "src/shared/core/models.py"
  - "src/nexus/*.py"
  - "src/nexus/agents/*.py"
  - "src/development/agents/*.py"
  - "src/deployment/agents/*.py"
---

# Agent output contracts & the environment_id chain

Every agent except the Developer returns a forced-structured Pydantic model via `run_structured_llm`
(the Developer is the agentic Claude CLI — see
[agent-provider-model-map](agent-provider-model-map.md)). Models live in `src/shared/core/models.py`
unless noted. Loop that consumes these: [pipeline-fsm-loops](pipeline-fsm-loops.md).

## Models (output → consumer)
- **PO** → `EpicDocument{markdown}` (`src/nexus/agents/po.py`). Stack-agnostic, no env_id. `get_system_prompt("po")`. Persisted `artifacts/epic.md`.
- **SA** → `Blueprint{environment_id, markdown}` (`src/nexus/agents/sa.py`). `get_system_prompt_with_platforms("sa")`. `run_sa` returns ONLY `markdown` → the structured `environment_id` is **discarded**; only `blueprint.md` persists.
- **TPM** → `ProjectPlan{tasks: list[TaskTicket{ticket_id, title, environment_id, description}]}` (`src/nexus/agents/tpm.py`). `get_system_prompt_with_platforms("tpm")`. Each ticket materialized as `artifacts/TASK-XX.md`. Behavior-driving: `environment_id` (validated), `ticket_id` (filename); free-text: `title`, `description`.
- **TechLead** → `TechLeadContract` with `TopologyNode{file_path, exports, depends_on}`. Behavior-driving: `files_to_modify` (scope gate), `topology_contract` (import SSOT for Dev+QA), `environment_id` (sandbox/gates/QA-profile selector), `domain_tags` (skill router; first = language), `strict_type_validation_rules` (injected into skills+QA), `core_libraries`/`architectural_constraints`/`function_signatures`/`instruction` (Developer prompt). Observability only: `shared_context`, `techlead_reasoning`.
- **QA** → `QATestSuite{overwrite_existing, new_imports, new_test_code, files_to_delete}` (per module). `files_to_delete` = QA-self-identified obsolete tests (separate from the Reviewer's `zombie_tests_to_delete`).
- **Reviewer** → `ReviewReport{code_quality_analysis, test_integrity_analysis, log_verification_analysis, code_quality_approved, test_integrity_approved, dev_diagnostic_payload, qa_diagnostic_payload, dev_evidence_citation, zombie_tests_to_delete}`. Booleans gate `all_gates_passed`; payloads route to the two isolated channels via the `reconcile_feedback_routing` SSOT (ADR 0024). The `_require_routing_coherence` validator code-enforces `payload non-empty ⟺ approval false` (so an approved side can't carry a payload) AND a non-empty `dev_evidence_citation` (verbatim gate line / code excerpt) on a production rejection — instructor re-prompts on violation (BACKLOG #11/#17/#18 resolved). `zombie_tests_to_delete` is deleted deterministically in `qa.py` before regeneration. Analysis fields are observability only.
- **TechWriter** → updates `docs/architecture_state.md` (the living ADR), injected as `=== LIVING ARCHITECTURE DOCUMENT (ADR) ===` into consuming nodes by `build_agent_context` (placeholder on first iteration).

## The environment_id chain (one validator, three hops)
`environment_id` is the Paved-Road platform key (e.g. `python-3.12-core`) and the single stack selector
for the whole executor (sandbox image, build/test/format gates, QA layout). It is validated against
`SUPPORTED_ENVIRONMENTS` (`environments.py`) by an **identical** `_validate_environment_id` field
validator on `Blueprint`, `TaskTicket`, AND `TechLeadContract` — an unsupported value is rejected at
deserialization at every hop.

Flow: SA selects it (validated, then discarded at the Nexus boundary) → TPM re-extracts it from the
blueprint markdown prose and copies it into each `TaskTicket` (validated) → it lands in `TASK-XX.md` →
TechLead copies it into `TechLeadContract` (validated). Because the structured value is lost to markdown
at the SA→TPM boundary, `sa.md` requires the SA to write the exact key VERBATIM into `## Tech Stack`
(text round-trip; structural fix tracked docs/BACKLOG.md #20).

The TechLead's `domain_tags[0]` (skill router) MUST equal the language of `environment_id` (gate router)
or skills and gates split-brain — enforced by `techlead.md` prose only, not code (docs/BACKLOG.md #19).
Known contract gaps across the suite: docs/BACKLOG.md #19–#24.
