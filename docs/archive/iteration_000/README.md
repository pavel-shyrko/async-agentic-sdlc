# Snapshot 000 — Research & Infrastructure Blueprint

* **Timestamp**: May 24, 2026, 15:00 CEST
* **Research Provider**: Gemini Pro Deep Research
* **Locally Archived Artifacts**:
  * **Track 1 (Infrastructure & Costs)**: [Source Prompt](./prompt_infra.txt) | [Full PDF Report](./report_infra.pdf)
  * **Track 2 (Pipeline Architecture)**: [Source Prompt](./prompt_architecture.txt) | [Full PDF Report](./report_architecture.pdf)
* **Final Status**: ✅ COMPLETED (System Topology Defined)

---

## 1. Research Objectives & Constraints
To execute a reliable multi-agent SDLC pipeline during a 48-hour hackathon, two distinct research vectors were analyzed based on the specific engineering prompts archived above:

### Track 1: Infrastructure & Cost Architecture
* **Objective**: Evaluate local (WSL2) vs. cloud VM hosting, secure sandbox orchestration, automated Git synchronization, and Model Context Protocol (MCP) server topologies under a zero-to-low budget constraint.

### Track 2: Deterministic Pipeline Engineering
* **Objective**: Enforce machine-readable contracts between a 7-stage agent graph (Product → Planner → Architect → Developer → Reviewer → QA → DevOps), structured JSON schema enforcement, and interactive CLI worker integration.

The system targets a threshold of ≥80% human-free execution reliability under strict low-to-zero budget limits.

---

## 2. Core Comparison Matrices & Tool Evaluation

### Orchestration: LangGraph vs. Custom Python State Machine
The analysis evaluated LangGraph against an engineered custom Finite State Machine (FSM):

| Evaluation Metric | LangGraph Framework | Custom Python / Pydantic FSM |
| :--- | :--- | :--- |
| **Control Flow** | Graphs with conditional edges; native support for cyclic routing. | State machine utilizing pure programmatic loops (`while` constructs). |
| **Dependency Overhead** | Heavy reliance on the LangChain ecosystem and opinionated primitives. | Minimal; relies strictly on standard libraries (`asyncio`) and provider SDKs. |
| **Boilerplate & Learning** | High verbosity; required schema compilation, node mapping, and edge binding. | Python-native; utilizes intuitive library primitives and standard validation. |
| **Suitability for Project** | Ideal for high-level abstract prototyping and cyclic graphs. | Optimal for absolute latency control, compliance constraints, and strict execution tracing. |

> **Critical Decision**: Framework-level abstractions like LangGraph introduce unnecessary architectural bloat and hide underlying execution states. To guarantee the strict implementation of a programmatic max-3-retry circuit breaker loop that handles exceptions without crashing, **the orchestrator must be custom-built using raw Python and Pydantic validation primitives**.

### Verification & Sandboxing Layer: Cloud Run vs. Local Docker Engine
To run untrusted agent-generated code safely without environmental contamination, two approaches were compared:
* **GCP Cloud Run**: Serverless container execution with a high free tier threshold. Rejected due to strict statelessness and an ephemeral, memory-bound filesystem. Stateful terminal CLI applications (e.g., Aider, Claude Code) require deep filesystem persistence, background framework daemons, and multi-turn Git visibility across long SDLC cycles.
* **Localized Docker Sandboxing**: Selected as the superior pattern. Docker volume mapping allows restricting the agent execution space strictly to a target `/workspace` directory. This prevents privilege escalation or accidental destruction of the primary orchestrator files.

For programmatic container control within Python, **`docker-py`** was chosen over *Testcontainers* for its low-level, fine-grained lifecycle handling and direct command invocation through the `exec_run` method, although *Testcontainers* remains optimal for multi-container database provisioning.

---

## 3. Tool Access & Model Routing Strategy
Model selection was fundamentally driven by tool ecosystem integration and caching financial parameters:

1. **Gemini 2.5 Pro (High-Level Context)**: Allocated to the Product, Planner, and Architect nodes due to its multi-million token window and explicit **Context Caching** capability. For blocks passing 4,096 tokens, context can be cached remotely with a 24-hour TTL, slashing recurrent prompt processing costs by 90%.
2. **Claude 3.5 Sonnet (Lead Engineer)**: Allocated to the Developer, Reviewer, and QA nodes due to superior AST code mutation capabilities and native support inside specialized headless CLI workers (Claude Code / Aider). Utilizing Anthropic's automatic ephemeral **Prompt Caching** (minimum 1,024 token threshold) ensures rapid, sub-5-minute loop updates receive an aggressive 90% read discount.

---

## 4. Derived System Topology

### Infrastructure Setup
* **Orchestration Host**: Local execution loop hosted within **WSL2 (Ubuntu Distribution)** to ensure immediate file system access, zero hosting billing, and bypass complex IAM overhead. 
* **MCP Server Architecture**: Standard STDIO transport protocol is restricted because it spawns isolated 1:1 sub-processes, resulting in tool duplication, configuration drift, and memory exhaustion on limited hosts. The pipeline implements an **HTTP Server-Sent Events (SSE) server via FastMCP**, exposing a centralized network port (`http://127.0.0.1:8000/mcp`). Both the Python loop and the sandboxed CLI containers connect as network clients, sharing an identical Git state and search API context concurrently.

### Security & Automated State Sync
* **GitHub App Authentication**: Personal Access Tokens (PATs) are banned due to broad exposure risks. The pipeline provisions a private GitHub App actors layer that leverages cryptographically signed RS256 JWTs to fetch ephemeral, 1-hour Installation Access Tokens.
* **State Operations**: Local code management (staging, branching, committing, pushing) is executed via **GitPython**, passing the short-lived token over secure HTTPS variables. Platform operations like generating Pull Requests migrate to the **PyGithub** wrapper to securely invoke the GitHub REST API (`/pulls`) with dynamic descriptions compiled by the reasoning models.

---

## 5. Line-Item Financial Cost Model (10 Cycles / 48 Hours)

Calculations assume standard token rates for a simple CRUD application session (50,000 input / 10,000 output tokens per agent turn) across 10 continuous pipeline iterations:

| Infrastructure / Service Component | Volume / Usage Metric | Optimization Strategy Applied | Estimated Total Cost (USD) |
| :--- | :--- | :--- | :--- |
| **Compute Engine (GCP e2-micro)** | 48 Hours | Bypassed via Local Host deployment (WSL2 / Local Docker). | $0.00 |
| **Orchestrator Inference (Gemini 2.5 Pro)** | 500K Input / 100K Output | Explicit Context Caching ($0.15/1M tokens for 90% of requests). | $1.13 |
| **Implementer Inference (Claude 3.5 Sonnet)** | 500K Input / 100K Output | Anthropic Ephemeral Prompt Caching ($0.30/1M tokens read). | $1.82 |
| **Reviewer Inference (OpenAI / Codex)** | 500K Input / 100K Output | Automatic Prompt Caching (50% discount on recently read inputs). | $2.88 |
| **Source Control & Repositories** | 10 PRs / 50 Commits | GitHub App Integration + Free Tier Private Repositories. | $0.00 |
| **External Integrations** | ~100 API Queries | Brave Search API Free Tier (Up to 2,000 queries/month). | $0.00 |
| **Total Estimated Pipeline Budget** | **10 Complete Cycles** | **Context Caching optimization slashes input bills by ~90%**. | **$5.83** |