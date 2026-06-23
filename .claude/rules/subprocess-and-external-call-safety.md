---
paths:
  - "src/shared/utils/forge.py"
  - "src/shared/utils/subprocess_helpers.py"
  - "src/shared/utils/git_helpers.py"
  - "src/shared/utils/llm.py"
  - "src/shared/core/config.py"
  - "src/shared/core/docker_adapter.py"
  - "src/executor/runner.py"
---

# Boundary safety: sanitize every subprocess argv, time-bound every blocking external call

Production incidents across iterations (ADR [0018](../../docs/decisions/0018-auto-merge-pr-loop-closure.md),
[0020](../../docs/decisions/0020-deploy-scaffolding-and-lint-gate.md)) shared one shape — an unguarded value
crossing a process/network/library boundary. Each is fixed *at the boundary*, as a shared SSOT, never by
patching the one field/call that happened to break. When you add or edit code that spawns a subprocess,
makes a blocking external call, or sends a structured-LLM message, you MUST uphold the invariants below.

## 1. Every subprocess argv element goes through `sanitize_for_argv`

Any string that reaches `asyncio.create_subprocess_exec` / `_shell` (or `subprocess.*`) as an argv element
MUST be normalized with `sanitize_for_argv` (`src/shared/utils/subprocess_helpers.py`, the SSOT) first.

**Why:** POSIX `execvp` raises `ValueError: embedded null byte` if *any* argv element contains `\x00`, and
agent-authored text (ticket bodies, PR title/body, commit subjects) can carry corrupted glyphs (a `©`
mangled to NUL). The helper strips C0 controls + DEL while preserving `\t`/`\n`/`\r`, so multi-line bodies
survive intact.

**How to apply:** the existing seams already do this — `forge._run_gh` (`safe_args = [sanitize_for_argv(a)
for a in args]`) and `runner._run_checked` (`safe_cmd = [sanitize_for_argv(c) for c in cmd]`). A **new**
subprocess call site must do the same at the argv boundary — not by cleaning one upstream field. (Cleaning
the glyph at *ingest*, when Nexus persists `TASK-*.md` / sets `pr_description`, is a separate deferred
BACKLOG hardening — it does not replace the boundary guard.)

## 2. Every blocking external call carries a wall-clock ceiling

Any blocking call to a network service or child process MUST have a timeout, declared as an env-overridable
constant ([[config-constant-convention]]):
- **Gemini (structured LLM)** — bounded at the **client/transport layer**: `instructor_client` is built with
  `http_options=types.HttpOptions(timeout=GEMINI_REQUEST_TIMEOUT * 1000)` (`config.py`). Do NOT instead wrap
  the `run_in_executor` await in `asyncio.wait_for` — the executor thread cannot be cancelled, so that only
  orphans the worker thread and leaks the pool. Bound the *request*, not the await.
- **`gh` (forge)** — `GH_NETWORK_TIMEOUT` via `asyncio.wait_for(proc.communicate(), …)` in `forge._run_gh`.
- **`git`** — `GIT_NETWORK_TIMEOUT` in `runner._run_checked` / `git_helpers`.
- **Developer CLI** — `DEVELOPER_CLI_TIMEOUT` (hard) + `DEVELOPER_CLI_IDLE_TIMEOUT` (inactivity).

**Why:** `with_api_retry` only catches *exceptions* — a silent network stall is not one, so without a
transport ceiling a hung call hangs the whole run forever (the symptom that motivated `GEMINI_REQUEST_TIMEOUT`).
A timeout converts the stall into a raised error that the existing retry/backoff handles, then fails fast.

## 3. A system message that teaches templated-config syntax must not trip the structured-call library's parser

Before any structured call, `run_structured_llm` relocates a SYSTEM message containing Jinja-style markers
(`{{ … }}` / `{% … %}`) into a USER turn via `_relocate_jinja_system_messages` (`src/shared/utils/llm.py`,
the SSOT) — a fast-path no-op for every marker-free role.

**Why:** `instructor`'s Google-GenAI path hard-rejects Jinja markers in a *system* message
(`extract_genai_system_message` raises `ValueError: Jinja templating is not supported in system messages
with Google GenAI`). A config-teaching prompt legitimately contains them — the DevOps prompt's GitHub
Actions `${{ secrets.* }}` / `${{ vars.* }}` expressions — so every structured DevOps call crashed
deterministically (3 identical retries) before producing output. We never pass a Jinja `context`, so nothing
is rendered; the markers are literals the model must emit verbatim. The guard inspects ONLY system-role
content, so relocating to a user turn (neither guard-checked nor rendered) gets the literal through.

**How to apply:** fix it at the `llm.py` seam — NEVER by stripping the `{{ }}` the model must produce (the
generated YAML needs them) nor by escaping them in the prompt. A *new* config-generating role
(Helm/Terraform/k8s/Jinja-emitting) is covered automatically; the relocation is the SSOT for "a
templated-config prompt crosses the structured-call boundary."

**Diagnostic tell:** a hang, an `embedded null byte` traceback, or a Jinja-in-system-message `ValueError`
that escapes to `main()` is **not** an FSM halt — no `incident_report.json` is written. See
[[pipeline-fsm-loops]] and the `analyze-run` skill's boundary-crash/hang class.

Related: [[repo-module-map]] (where these seams live), [[config-constant-convention]] (the env knobs),
[[agent-provider-model-map]] (the Gemini timeout).
