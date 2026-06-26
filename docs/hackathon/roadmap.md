Hey, Token Burners! The hackathon deadline (June 28) is fast approaching, and our goal is ambitious. GHOSTWIRE isn't just the simple echo server from your tests; it's a serious full-stack beast (FastAPI + React + Vector DB + LLM).

Your Factory (SDLC Pipeline) is already highly optimized for basic applications, but to ingest a monster like Ghostwire and autonomously deploy it to GCP, it lacks a few critical nodes.

Here is the detailed analysis of the current state and a roadmap of what needs to be built.

---

### 🟢 What Is Already Done (Your Strengths)

Based on the provided logs, commit history (`CHANGELOG.md`), and architectural decisions (`PRACTICUM.md`), you have a rock-solid foundation (scoring ~100-110 points out of 135 on the Judge Cheat Sheet):

* **Rigid FSM Orchestrator (Nexus Plane):** You ditched the unpredictable LangGraph for a deterministic state machine. The pipeline (PO → SA → TPM → TechLead → Developer → QA → Reviewer → DevOps) runs on strict contracts.
* **QA Isolation & Docker Sandbox:** Your QA agent generates and executes tests in isolated containers, preventing the Developer agent from cheating.
* **Autonomous Self-Healing:** The Factory can read crashed linter logs, test failures, and gcloud deployment errors (like the `allow-unauthenticated` flag issue) and fix itself.
* **DevOps Infrastructure:** You have a working flow for Google Cloud Run deployments, Github Actions generation, URL parsing, and auto-publishing to the README.
* **Cost Optimization:** Prompt caching (Gemini/Claude) is implemented, which saves the budget (Criterion 7 on the Score Card).
* **WSL RAM Issue Resolved:** You configured `tmpfs` for Docker tests, saving disk I/O and memory during parallel tasks.

---

### 🔴 What Needs To Be Done (Gaps for the GHOSTWIRE Project)

GHOSTWIRE will break your current Factory if you feed it in right now. Why?

* **Missing Fullstack Archetype (React + FastAPI):** In `_project_src.txt`, your `_DEVOPS_SKILLS` are hardcoded to `("devops_rest_api", "devops_crud_app", "devops_cli_tool")`. The Factory doesn't know how to deploy a React SPA paired with FastAPI.
* **Heavy Infrastructure Integration (Vector DB & PostgreSQL):** Ghostwire requires Weaviate/Pinecone and Postgres. Currently, your QA agent spins up simple Python containers. Testing Ghostwire will require running `docker-compose` with a database inside the sandbox, otherwise, the RAG system tests will fail.
* **Secret Management:** Ghostwire modules use the Claude API. Keys cannot be hardcoded. Your DevOps agent must know how to configure GCP Secret Manager and pass secrets to Cloud Run, while the QA agent needs to mock external APIs or use test keys.
* **Specific RAG Context (Retrieval-Augmented Generation):** The Architect and Developer agents need examples and skills (in the `prompts/skills/` folder) on how to write code for vector databases and embeddings, otherwise, they will hallucinate non-existent libraries.

---

### 🗺️ Roadmap: How to Upgrade the Factory for GHOSTWIRE

Divide these tasks among the team and execute them in parallel.

#### Step 1: Expand Architectural Archetypes (TODAY)

* Add a `devops_fullstack` archetype to `src/shared/core/environments.py` and the skill registry with instructions for building React.
* Update DevOps prompts to write a multi-stage `Dockerfile` (build React statically and serve it via FastAPI to keep everything in one Cloud Run container).
* Create `skill_rag_engineering.md` in `prompts/skills/` to guide the Developer agent on using Weaviate without hallucinating libraries.

#### Step 2: Upgrade the QA Sandbox (TOMORROW MORNING)

* Modify the container logic in the QA Node to use `Testcontainers` or generate a `docker-compose.test.yml` if a database is detected.
* Add strict instructions to `PRACTICUM.md` requiring the QA agent to mock all Claude API calls using `pytest-mock` or `responses`.

#### Step 3: GCP Secret Injection (TOMORROW AFTERNOON)

* Update DevOps deployment scripts (`deploy.yml`) to securely handle API keys.
* Add a gcloud execution step that maps Github Secrets directly to Cloud Run environment variables using `--set-env-vars`.

#### Step 4: Dry-Run and Tuning (TOMORROW EVENING)

* Run the full pipeline: `python3 main.py --idea "$(cat '05 GHOSTWIRE - Corporate Intelligence Grid.md')" --auto-execute --budget 10`
* Monitor for frontend build failures ensuring the Architect correctly separates `/backend` and `/frontend` directories.
* Increase pipeline timeouts to accommodate the longer React build times inside GitHub Actions.

#### Step 5: Demo Preparation (JUNE 28, MORNING)

* Audit the cost report (Criterion 7) to prove to the judges how Prompt Caching saved tokens on heavy prompts.
* Validate that the final README successfully publishes the live Cloud Run URL for the Ghostwire UI.

> **Major tip for the demo:** The Cyberthone 2026 jury will evaluate **how autonomously your Factory built Ghostwire**, not just Ghostwire itself. If the Factory stumbles on vector DB tests but *finds and fixes the error itself* (Self-healing loop), you will secure gold-tier points (120-135 pts). Deliberately leave evidence in the logs showing how the Arbiter or DevOps agents resolved conflicts!

Good luck, Token Burners! 👾🔥