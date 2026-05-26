# Engineering Practicum: Project Evolution

Chronological log of major codebase snapshots, systemic vulnerabilities, and architectural breakthroughs.

## Key Engineering Takeaways

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
| **003** | 26 May 2026, 23:00 | Dual-channel audit logging, native token tracking, and Gemini 2.5 migration | ✅ Success (Observability locked) | [Browse](./docs/archive/iteration_003/) |
| **002** | 26 May 2026, 10:00 | Implement independent QA-Generator node & parallel validation layer | ✅ Success (Autonomous self-healing) | [Browse](./docs/archive/iteration_002/) |
| **001** | 25 May 2026, 10:00 | Establish baseline linear pipeline with sequential execution loops | ⚠️ Compromised (Agent test sabotage) | [Browse](./docs/archive/iteration_001/) |
| **000** | 24 May 2026, 15:00 | Cloud Infrastructure & Deterministic Pipeline Architecture Research | ✅ Completed (Blueprint defined) | [Browse](./docs/archive/iteration_000/) |