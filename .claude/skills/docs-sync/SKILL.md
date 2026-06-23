---
name: docs-sync
description: Factually synchronize CHANGELOG.md (Keep a Changelog format), README.md, and docs/ARCHITECTURE.md after code changes. Use when the user asks to update the changelog or README, sync docs to recent commits/diff, or reflect new CLI flags, env vars, directory structure, execution commands, agent roles, FSM routes, planes/containers, budget/FinOps or cost-reporting changes, or new run-store report artifacts. Focuses strictly on "what" changed.
---

# Factual Documentation Synchronization (Changelog, README & Architecture)

## Context
Update factual project-state tracking after code changes. Focus strictly on "What" changed.

## Protocol
1. **Diff Analysis**: Read the recent commits or `git diff`.
2. **CHANGELOG Update**:
   - Target `CHANGELOG.md`.
   - Strictly follow the "Keep a Changelog" format.
   - Map changes to standard blocks: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
   - Translate raw code diffs into human-readable engineering features/fixes. Do not dump raw commit messages.
3. **README Alignment**:
   - Target `README.md`.
   - Scan for out-of-sync factual data across ALL of these surfaces (not just CLI flags — every one drifts independently):
     - **Agent roster / Model Routing Matrix** — the enumerated list of structured roles (TechLead, QA, Reviewer, TechWriter, Arbiter, DevOps, PO/SA/TPM). A new agent role MUST be added here.
     - **Numbered capabilities list** — the "Custom FSM Engine / Model Routing / … / Fast-Fail Guardrail / Autonomous Contract Self-Healing" items; a new engine behavior gets a new item or extends one.
     - **Environment variables / tunable constants** — NOT only CLI flags: new `*_MODEL`, budgets, and FSM knobs (`PIPELINE_MAX_RETRIES`, `ARBITER_TRIGGER_ATTEMPT`, `MAX_CONTRACT_AMENDMENTS`, `ARBITER_AMENDMENT_RETRY_BONUS`, etc.) belong in the relevant prose. Name each env var explicitly.
     - **FinOps / budget / cost-reporting** — the "Monitoring Token Usage & Costs (FinOps)" section. A change to *what is gated* (e.g. money-only vs token ceiling), the budget scope (per-ticket vs application-wide `PIPELINE_APP_BUDGET_USD` / `--budget`), or *what is reported* (per-agent → +per-plane +time, a new `app_finops_report.json`) MUST be reflected here AND in `docs/guides/setup.md`'s env-var reference table — both drift independently from the ARCHITECTURE FinOps section.
     - **Directory structure tree** — new modules/dirs (e.g. a new `src/.../<role>.py` agent or a new `src/shared/core/*.py`) and the per-line role/file comments.
     - **`prompts/system/` role-prompt list** — the structure tree enumerates the per-role prompt files (`po, sa, tpm, techlead, developer, qa, reviewer, techwriter, …`). A new role's `prompts/system/<role>.md` MUST be added here — this is a SEPARATE enumeration from the `agents/` list and drifts independently (a role can be in one and missing from the other).
     - **ADR sequence range** — strings like `0000–0016` / `(MADR) 0000–NNNN`; the upper bound must equal the highest `docs/decisions/NNNN-*.md` on disk. This range appears in MORE THAN ONE file (README ×N + `docs/decisions/README.md`) — bump every occurrence.
     - **Doc version / iteration stamps** — footer/byline strings like `as of … v0.16.0` or `reflects the Arbiter iteration` (in `docs/ARCHITECTURE.md` and any other stamped doc) must bump to this release's version/name.
     - **CLI arguments / execution commands** and **Developer Meta-Tools** (the `.claude/skills/` list — add a new `/skill`).
   - Apply targeted diff patches to the relevant sections to reflect the current state.
4. **Architecture Diagram Sync** (`docs/ARCHITECTURE.md`):
   - This is the C4 model (L1 System Context / L2 Containers / L3 Executor FSM) + the end-to-end
     `sequenceDiagram` + the component-reference table, all in GitHub-native Mermaid
     (`flowchart`/`sequenceDiagram` — never C4-plugin syntax, which GitHub won't render).
   - **Trigger — only when this iteration changed *structure*, not behavior.** Skip this step entirely for
     pure bugfixes/tuning. Re-sync when any of these changed:
     - **A new/removed agent role** (a `src/{nexus,development,deployment}/agents/*.py` or plane module + its `ROLE_MODELS`
       entry) → add/remove the node in the relevant L2/L3 diagram AND the component-reference table row.
     - **A new/removed/re-routed FSM state or decision edge** (e.g. a new routing target like Arbiter, a new
       gate, a changed `while`/deadlock/breaker condition in `src/nexus/runner.py`) → update the **L3
       Executor FSM** flowchart to match [pipeline-fsm-loops](../../rules/pipeline-fsm-loops.md). Don't
       duplicate that rule's prose — keep the diagram faithful and cross-reference it.
     - **A new external system** (a new provider/CLI/service the engine talks to) → L1 System Context node + arrow.
     - **A new plane / container / store** (a new top-level `src/` plane, prompt store, sandbox image class,
       or run-store artifact such as `app_finops_report.json`) → L2 Containers diagram + boundary.
     - **A FinOps / budget / cost-reporting change** (the breaker's gate changing — e.g. money-only vs a
       token ceiling; the budget scope going application-wide + threaded; or telemetry gaining a dimension
       like per-plane / time) → update the **L3 Executor FSM** breaker checkpoints/edges, the dedicated
       **FinOps & the application budget** section (keep its mini-diagram faithful), AND the
       component-reference rows for `config.py` / `observability.py` / `models.py`. This is the trigger that
       was missed for E5 — treat any change under `enforce_financial_circuit_breaker` / `PipelineTelemetry` /
       `run_batch` budget accounting as structural for ARCHITECTURE purposes.
   - **Drift sweep (same idiom as the README sweep):** grep `docs/ARCHITECTURE.md` for an existing peer of the
     new element (a sibling role name, a neighbouring FSM node, another container) and confirm the new element
     appears in BOTH the diagram AND the component-reference table. Presence in only one is a sync miss.
   - Keep diagrams grounded strictly in the current code — no invented or aspirational components.
5. **Peer-enumeration drift sweep** (mechanical, mandatory — this is what catches the misses that recur):
   The recurring failure is an enumeration that lives in MORE THAN ONE file, so a single-file scan passes
   while a sibling file silently lies — and it is often drift carried from a PRIOR release, not this
   iteration's addition. So **re-verify the full peer-sets every release, not only what changed.** For each
   set below, pick one existing **peer** member, `grep -rn` it across the doc surface
   (`README.md`, `docs/ARCHITECTURE.md`, `docs/decisions/README.md`, `CLAUDE.md`, `.claude/rules/*.md`), then
   confirm EVERY other member appears in the SAME set of files. A file that lists the peer but not a sibling
   is a drift miss — patch it.
   - **Agents** — every role must appear in: README Model-Routing roster · README `agents/` tree comment ·
     README `prompts/system/` tree list · `docs/ARCHITECTURE.md` L1 agent list + component-reference table ·
     `agent-provider-model-map` rule. (Cross-check against `ls src/*/agents/*.py` + `ls prompts/system/`.)
   - **ADR range** — `ls docs/decisions/ | tail` gives the highest `NNNN`; it must equal the upper bound of
     EVERY `0000–NNNN` range string (grep `0000` across docs).
   - **Version / iteration stamps** — grep the prior release's version (e.g. `v0.16`) across docs; every hit
     that means "current state" must bump to this release.
   - **Env constants / CLI flags** — each new knob (`grep -rn "os.environ.get" src/`) named in README prose
     AND its governing rule (`config-constant-convention`, `run-layout-and-cli`).
   - **Skills** — a new `.claude/skills/<name>/` appears in README Meta-Tools AND `CLAUDE.md`.
   - **FinOps / budget** — the budget model (what's gated, the scope, what's reported) must agree across:
     README "Monitoring Token Usage & Costs" section · `docs/ARCHITECTURE.md` "FinOps & the application
     budget" section + component-reference rows · `docs/guides/setup.md` env-var table · the
     `token-budget-excludes-cache` + `run-layout-and-cli` rules. Grep a budget constant
     (`PIPELINE_APP_BUDGET_USD`) across these and confirm none still describe a removed mechanism (e.g. a
     token ceiling).

## Output Format
Apply changes directly to the file system or provide strict `diff` blocks. End with a raw checklist of updated files. Zero conversational text.
