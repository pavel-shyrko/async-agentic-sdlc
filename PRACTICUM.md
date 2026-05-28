# Engineering Practicum: Project Evolution

Chronological log of major codebase snapshots, systemic vulnerabilities, and architectural breakthroughs.

## Key Engineering Takeaways
* **Git Anchor as a State Machine** *(Detected in [Snapshot 005](./docs/archive/iteration_005/))*: Naive file-glob scanning of agent sandboxes breaks on real projects because Python runtimes silently write binary `.pyc` files, prior-cycle artifacts bleed into the next snapshot, and there is no scope boundary between "files the agent touched" and "files that happened to exist." Replacing glob scans with a two-primitive Git API (`init_sandbox_git` + `get_pipeline_snapshot_files`) solves all three: `.gitignore` blocks binary noise before it reaches the diff, `git diff <base_branch> --name-only` produces a strict causal delta, and the base-branch anchor is immovable so retries never accumulate stale state. This is a transferable pattern for any agentic system that writes files.

* **LLM Output Fan-Out to Break Token Ceiling** *(Detected in [Snapshot 005](./docs/archive/iteration_005/))*: Monolithic LLM generation of a test suite covering an entire multi-file contract hits the `max_output_tokens` wall and returns a truncated, syntactically broken file. The fix is a fan-out: one isolated LLM call per production module, results collected via `asyncio.gather`, each writing its own `test_<module_slug>.py`. This trades one large serial call for N small parallel calls — latency is bounded by the slowest module, total output tokens per call shrink to a single module's scope, and test isolation improves as a side effect. Facade modules (`__init__.py`) must be filtered before fan-out to prevent exponential coverage duplication.

* **FSM Catch-22: Architect Contract vs. Developer SOLID Compliance** *(Detected in [Snapshot 005](./docs/archive/iteration_005/))*: A deadlock emerges when the Developer agent (following DRY/SOLID) extracts shared logic into a utility file not listed in the architecture contract, and the Reviewer agent rejects this as a "contract violation." Neither agent can resolve the conflict within the current FSM cycle — the Architect cannot amend the contract retroactively, and the Developer cannot remove the helper without violating the design constraints. Resolution requires an explicit authorization rule in the Reviewer's system prompt: utility files created to enforce separation of concerns are pre-approved. This teaches a general principle: FSM gate agents must encode an explicit policy for authorized deviations, not just enforcement of the original contract.

* **The Python Type-Hierarchy Trap & Self-Healing** *(Detected in [Snapshot 004](./docs/archive/iteration_004/))*: Python's type system implicitly inherits `bool` from `int` (`isinstance(True, int)` is `True`). When Developer agents generate overly complex checks such as `if not isinstance(n, int) or isinstance(n, bool):`, it introduces cognitive load and fragile logic. Utilizing an elite Reviewer agent (Gemini 2.5 Pro) to reject this code and route strict diagnostics forces the Developer agent (Claude) to align with a precise type-identity pattern: `if type(n) is not int:`.

* **Sandbox Volume Isolation & Anti-Self-Mutation** *(Detected in [Snapshot 004](./docs/archive/iteration_004/))*: Mounting the entire working directory (`cwd`) inside execution containers exposes the pipeline's own core files to accidental or malicious modifications by run-away agent scripts. Transitioning to a strict dual-mount strategy—mounting framework code `src/` as Read-Only (`:ro`) and the volatile execution output `artifacts/` as Read-Write (`:rw`)—completely mitigates the risk of self-mutation.

* **Modularization Mandate** *(Detected in [Snapshot 004](./docs/archive/iteration_004/))*: Monolithic orchestration (500+ lines in `orchestrator.py`) has become a primary bottleneck for maintainability and security auditing. Transitioning to a decoupled, module-based architecture (Logic/Nodes/Utils) is mandatory to mitigate path-traversal risks and allow atomic testing of pipeline components.

* **Observability Bottlenecks** *(Detected in [Snapshot 003](./docs/archive/iteration_003/))*: Standard output (`print()`) is highly volatile and insufficient for autonomous trace tracking. A strict dual-channel logging system (Console INFO + Rotating Audit Log DEBUG) is required to ensure complete pipeline repeatability. Token counts must be extracted natively from structured responses, while out-of-band CLI executions (Claude CLI) must be audited through specialized session database parsers (`npx ccusage`).

* **LTS vs. Experimental Model Quotas** *(Detected in [Snapshot 003](./docs/archive/iteration_003/))*: Pinning cutting-edge experimental preview models to Free Tier accounts introduces severe API bottlenecks (429 Resource Exhausted under a 20 request/day cap). For PoC development, shifting workloads to robust mainstream versions (Gemini 2.5 Flash and Pro) balances logical reasoning capacities with highly generous execution quotas.

* **Implicit Type Hazards** *(Detected in [Snapshot 002](./docs/archive/iteration_002/))*: LLM reasoning consistently misses language-specific type inheritance constraints. Multi-agent code generation requires explicit runtime type-guards to counter architectural assumptions.

* **QA Boundary Isolation** *(Detected in [Snapshot 001](./docs/archive/iteration_001/))*: Never grant the Developer agent write permissions to the validation scope. Without absolute environment isolation, models will mutate tests to fake a successful compilation.

* **Hybrid Model Routing & Caching** *(Detected in [Snapshot 000](./docs/archive/iteration_000/))*: Multi-agent architectures are cost-prohibitive without strict model routing driven by tool access. Ingest heavy context via Gemini Context Caching, and bind active code mutations to Claude Code execution using ephemeral Prompt Caching to achieve up to a 90% input token discount.

* **The Custom Framework Mandate** *(Detected in [Snapshot 000](./docs/archive/iteration_000/))*: Generic graph frameworks (e.g., LangGraph) introduce heavy dependency bloat and rigid boilerplate. Building a custom Python/Pydantic Finite State Machine (FSM) is required for absolute latency control, programmatic circuit breaking, and native visibility into execution loops.

---

## Development Steps

| Step | Date / Time | Core Target | Result | Artifacts |
| :--- | :--- | :--- | :--- | :---: |
| **005** | 28 May 2026, 16:00 | Git-Driven State Tracking, QA Fan-Out Concurrency, brownfield support | ✅ Success (3 independent tickets verified) | [Browse](./docs/archive/iteration_005/) |
| **004** | 27 May 2026, 01:20 | Architectural decoupling & modularization, sandbox protection | ✅ Success (Self-healing verified) | [Browse](./docs/archive/iteration_004/) |
| **003** | 26 May 2026, 23:00 | Dual-channel audit logging, native token tracking, and Gemini 2.5 migration | ✅ Success (Observability locked) | [Browse](./docs/archive/iteration_003/) |
| **002** | 26 May 2026, 10:00 | Implement independent QA-Generator node & parallel validation layer | ✅ Success (Autonomous self-healing) | [Browse](./docs/archive/iteration_002/) |
| **001** | 25 May 2026, 10:00 | Establish baseline linear pipeline with sequential execution loops | ⚠️ Compromised (Agent test sabotage) | [Browse](./docs/archive/iteration_001/) |
| **000** | 24 May 2026, 15:00 | Cloud Infrastructure & Deterministic Pipeline Architecture Research | ✅ Completed (Blueprint defined) | [Browse](./docs/archive/iteration_000/) |