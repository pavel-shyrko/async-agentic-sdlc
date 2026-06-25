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
- **SA** → `Blueprint{environment_id, markdown}` (`src/nexus/agents/sa.py`). `get_system_prompt_with_platforms("sa")`. `run_sa` returns ONLY `markdown` → the structured `environment_id` is **discarded**; only `blueprint.md` persists. The SA also selects a **deployment target** (from `SUPPORTED_DEPLOY_TARGETS`, injected as `{injected_supported_deploy_targets_list}`) and records it + its runtime constraints in the markdown `## Deployment Target` section — prose-threaded exactly like `environment_id` (a validated structured `deploy_target_id` field is the tracked structural fix, docs/BACKLOG.md #35). It likewise records the selected platform's **`authoring_contract`** (surfaced on each `{injected_supported_platforms_list}` entry) in a `## Runtime Contract` section — chiefly the dependency-manifest convention the toolchain restores from (e.g. python → `requirements.txt`) — prose-threaded the same way (the runtime-axis twin of the deploy `runtime_constraints`).
- **TPM** → `ProjectPlan{tasks: list[TaskTicket{ticket_id, title, environment_id, description}]}` (`src/nexus/agents/tpm.py`). `get_system_prompt_with_platforms("tpm")`. Each ticket materialized as `artifacts/TASK-XX.md`. Behavior-driving: `environment_id` (validated), `ticket_id` (filename); free-text: `title`, `description`. Propagates the Blueprint's `## Runtime Contract` (the dependency manifest) onto `TASK-01` as scaffold glue — NOT the reconcile-only baseline file (`.gitignore`, the only one the TPM/Developer still own; README/LICENSE/CHANGELOG are TechWriter-owned).
- **TechLead** → `TechLeadContract` with `TopologyNode{file_path, exports, depends_on}`. Behavior-driving: `files_to_modify` (scope gate), `topology_contract` (import SSOT for Dev+QA), `environment_id` (sandbox/gates/QA-profile selector), `domain_tags` (skill router; first = language), `strict_type_validation_rules` (injected into skills+QA), `core_libraries`/`architectural_constraints`/`function_signatures`/`instruction` (Developer prompt). Observability only: `shared_context`, `techlead_reasoning`.
- **QA** → `QATestSuite{overwrite_existing, new_imports, new_test_code, files_to_delete}` (per module). `files_to_delete` = QA-self-identified obsolete tests (separate from the Reviewer's `zombie_tests_to_delete`).
- **Reviewer** → `ReviewReport{code_quality_analysis, test_integrity_analysis, log_verification_analysis, code_quality_approved, test_integrity_approved, dev_diagnostic_payload, qa_diagnostic_payload, dev_evidence_citation, zombie_tests_to_delete}`. Booleans gate `all_gates_passed`; payloads route to the two isolated channels via the `reconcile_feedback_routing` SSOT (ADR 0024). The `_require_routing_coherence` validator code-enforces `payload non-empty ⟺ approval false` (so an approved side can't carry a payload) AND a non-empty `dev_evidence_citation` (verbatim gate line / code excerpt) on a production rejection — instructor re-prompts on violation (BACKLOG #11/#17/#18 resolved). `zombie_tests_to_delete` is deleted deterministically in `qa.py` before regeneration. Analysis fields are observability only.
- **TechWriter** → `DocumentationUpdate{architecture_document, readme, changelog, usage_guide}` (`src/development/agents/techwriter.py`). Owns the human-facing docs set: it rewrites `docs/architecture_state.md` (the living ADR — injected as `=== LIVING ARCHITECTURE DOCUMENT (ADR) ===` into consuming nodes by `build_agent_context`, placeholder on first iteration), `README.md`, and the root `CHANGELOG.md` cumulatively on each successful ticket, and writes `LICENSE` deterministically (engine-curated Apache 2.0 via `boilerplate.render_apache_license` — NOT an LLM field; written ONLY when absent, RECITATION-safe). `usage_guide` (→ `docs/USAGE.md`, the end-user guide for the compiled/deployed app) is authored ONLY on the batch's **final ticket** — gated by `GlobalPipelineContext.is_final_ticket`, which `run_batch` sets via `run_executor(..., is_final_ticket=(ticket == tickets[-1]))` (set fresh each call, never trusted from the checkpoint; single-ticket paths leave it False). First-vs-subsequent ticket is detected by file-absence on disk (resume-safe). Uses `get_system_prompt_with_platforms("techwriter")` (fills `{injected_readme_scaffold}` + `{injected_env_commands}`). The README pre-seeds the `DEPLOYMENT_URL`/`RELEASE_URL` marker pairs (so the E4/E6 deploy/release workflow injects the live URL in place) and a `## Documentation` section linking `CHANGELOG.md` / `docs/architecture_state.md` / `docs/USAGE.md`. The Developer/TPM no longer own README/LICENSE — `build_gitignore_baseline_block` on `TASK-01` is `.gitignore`-only.

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
(text round-trip; structural fix tracked docs/BACKLOG.md #20). The **deployment target** rides the same
prose channel: SA writes it into `## Deployment Target`, the TPM copies its runtime constraints into the
relevant tickets' architectural-constraints, and the DevOps phase otherwise derives it from the archetype
(`deploy_target_for_archetype`). A validated structured `deploy_target_id` chain is the parallel hardening
(docs/BACKLOG.md #35). The **runtime authoring contract** rides the same prose channel: the selected env's
registry `authoring_contract` is surfaced on `{injected_supported_platforms_list}`, the SA writes it into
`## Runtime Contract`, and the TPM propagates the dependency-manifest requirement onto `TASK-01` — so the
manifest the toolchain restores from (`dependency_manifest(env_id)`) is actually scaffolded, keeping the
authoring side from drifting off the `setup_cmd` restore (the requirements.txt-vs-pyproject.toml halt class).

The TechLead's `domain_tags[0]` (skill router) MUST equal the language of `environment_id` (gate router)
or skills and gates split-brain — enforced by `techlead.md` prose only, not code (docs/BACKLOG.md #19).
Known contract gaps across the suite: docs/BACKLOG.md #19–#24.
