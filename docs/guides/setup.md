# Setup & First Run Guide

This is the single, top-to-bottom path from a clean Windows machine to your **first successful pipeline
run**. Follow the steps in order — each one ends with a quick *verify* so you never carry a broken step
forward. Docker internals (daemon, loopback, corporate CA, NU1301) live in their own deep-dive,
[docker-on-windows.md](docker-on-windows.md), linked at the one point you need it.

## What you're setting up

The engine is a deterministic multi-agent SDLC orchestrator with two planes: a **Nexus** control plane that
turns an idea into a plan (Epic → Blueprint → tickets), and an **Executor** worker plane that builds each
ticket through an FSM (TechLead → QA → Developer → gates → Reviewer). The structured roles run on **Google
Gemini**; the **Developer** runs on the **Claude Code CLI**; the build/test/SAST gates run in **Docker**
sandboxes. See [ARCHITECTURE.md](../ARCHITECTURE.md) for the full picture.

Mentally, you set up **four things** — WSL2 + Docker, Node + Claude CLI, a Python venv, and a Gemini API
key — then you **plan a project** and **execute its tickets**.

## Prerequisites at a glance

| What | Why | Installed in |
|---|---|---|
| WSL2 + Ubuntu 24.04 | The whole toolchain runs inside Linux (the Windows interpreter lacks the deps) | Step 0 |
| Docker Engine (`docker-ce` in WSL2, **not** Docker Desktop) | Runs the sandboxed build/test/SAST gates | Step 1 |
| `python3-venv`, `python3-pip`, `bandit` | Engine runtime + SAST linter (`bandit` must be on PATH) | Step 2 |
| Node.js via **nvm** (Linux paths only) | Hosts the Claude CLI | Step 3 |
| Python 3.12 venv + `requirements.txt` | The orchestrator's own dependencies | Step 5 |
| Claude Code CLI (**logged in once**) | The agentic Developer; auth is a login, **not** an API key | Step 6 |
| Sandbox images (`sdlc-sandbox/*`) | Per-language gate runtimes + Semgrep; **no auto-pull** | Step 7 |
| `GEMINI_API_KEY` | Credential for every structured agent | Step 8 |

> **The engine enforces this at startup.** `check_environment()` (`src/shared/core/config.py`) exits with a
> `🚨 CRITICAL` error unless `docker`, `claude`, and `bandit` are all on PATH **and** `GEMINI_API_KEY` is
> set. The [pre-flight self-check](#pre-flight-self-check) below mirrors it so you pass on the first try.

---

## 0. WSL2 Setup

In PowerShell (as Administrator):

```powershell
wsl --install -d Ubuntu-24.04
```

Restart, open the **Ubuntu** terminal, and create a user when prompted.

> **CRITICAL — work on the Linux filesystem, never `/mnt/c/`.** Clone and run the project under your WSL
> home (`~/...`, an ext4 virtual disk). Running from `/mnt/c/...` causes `EPERM`/permission failures, slow
> I/O, and — worst — makes `npm -g` link the **Windows** `claude.exe` across the interop boundary, which
> stalls the Developer agent. Every tool (`node`, `npm`, `claude`, `python`) must resolve to a path under
> `~/`. You verify this in Steps 3 and 6.

**All remaining steps run inside the WSL2 Ubuntu terminal.**

## 1. Docker Engine

Install the upstream **`docker-ce`** Engine inside WSL2 and expose its API on loopback only. Do this now by
following **[docker-on-windows.md](docker-on-windows.md) §2 (WSL server) and §3 (Windows client)**, then
return here. That guide owns the daemon config, the `127.0.0.1:2375` binding, the lazy-loader profile, and
the corporate CA.

> Do **not** install `docker.io` via apt and do **not** use Docker Desktop.

**Verify** (the daemon is up and reachable):

```bash
docker run --rm hello-world
```

## 2. System Packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv bandit
```

`bandit` is the SAST linter; the startup check requires it on PATH. **Verify:** `which bandit`.

## 3. Node.js (inside WSL2, via nvm)

Install Node **inside Linux** with `nvm` — never a Windows/Scoop `node`. `nvm` keeps everything under
`~/.nvm`, sidestepping NTFS permission and antivirus conflicts.

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc          # or re-open the terminal
nvm install --lts
nvm use --lts
```

**Verify** Node resolves to a Linux path (must start with `/home/...`, never `/mnt/c/...`):

```bash
which node    # expected: /home/<you>/.nvm/versions/node/v.../bin/node
```

## 4. Get the Project (on the Linux filesystem)

```bash
mkdir -p ~/projects && cd ~/projects
git clone <repo-url> async-agentic-sdlc && cd async-agentic-sdlc
```

(See the `/mnt/c/` warning in Step 0 — this is why the project lives under `~/`.)

## 5. Python venv + Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` is the single source of truth for the engine's dependencies (`instructor`,
`google-genai`, `pydantic`, `bandit`, `pytest`, `jsonref`). **Verify:**
`python3 -c "import instructor, google.genai, pydantic, jsonref"`.

## 6. Claude Code CLI

With the nvm Node active (Step 3), install the CLI globally — this pulls the **Linux** build, not
`claude-code-win32-x64`:

```bash
npm install -g @anthropic-ai/claude-code
```

**Verify** it resolves to a Linux path (NOT `/mnt/c/.../claude.exe`):

```bash
which claude    # expected: /home/<you>/.nvm/versions/node/v.../bin/claude
```

**Authenticate once, interactively** — the Developer agent uses this login. There is **no
`ANTHROPIC_API_KEY`**; the CLI caches credentials under `~/.claude/`:

```bash
claude          # complete the login prompt, then exit
```

Pin the orchestrator's Developer agent to this exact binary so it never resolves to a Windows `claude.exe`
on PATH (read via `CLAUDE_CLI_BIN` in `src/shared/core/config.py`):

```bash
echo 'export CLAUDE_CLI_BIN=$(which claude)' >> ~/.bashrc
source ~/.bashrc
```

## 7. Build the Sandbox Images

The gates run tests + SAST inside per-environment images plus a generic Semgrep image. **Build them once**
(re-run after editing any `docker/*.Dockerfile`) — there is **no auto-pull**, so a run fails immediately if
they're missing:

```bash
bash scripts/build_sandbox_images.sh
```

This builds `sdlc-sandbox/{python,go,node,dotnet}:latest` plus `sdlc-sandbox/semgrep:latest` (SAST rules
**vendored** so the scan runs fully offline). The tags must match `SUPPORTED_ENVIRONMENTS[...]["image"]` and
`SAST_IMAGE` in `src/shared/core/environments.py`.

> **Behind a corporate network:** the first build of each stack restores its packages online into a
> persistent docker cache volume; later runs resolve offline. This needs only the corporate **CA** in the
> WSL trust store — see [docker-on-windows.md](docker-on-windows.md) §4 (CA install) and §6 (restore /
> proxy / NU1301 details). You do **not** need `HTTP_PROXY` for the transparent corporate egress.

## 8. Gemini API Key

```bash
export GEMINI_API_KEY="your_actual_key_here"
# persist it:
echo 'export GEMINI_API_KEY="your_actual_key_here"' >> ~/.bashrc && source ~/.bashrc
```

Get your key at [Google AI Studio](https://aistudio.google.com/app/apikey). Never commit real keys. All
other knobs (budgets, timeouts, retry caps) are optional with sane defaults — see the
[Environment variable reference](#environment-variable-reference).

---

## Pre-flight self-check

Run this from the project root with the venv active. It mirrors what the engine validates at startup, so if
it passes, the orchestrator's own `check_environment()` will too:

```bash
which docker claude bandit                              # all three must resolve
which node claude | grep -q /home && echo "node/claude on Linux fs ✓"
[ -n "$GEMINI_API_KEY" ] && echo "GEMINI_API_KEY set ✓"
docker images | grep sdlc-sandbox                       # expect 5 images
claude -p "ping" >/dev/null 2>&1 && echo "claude authenticated ✓"
source venv/bin/activate && python3 -c "import instructor, google.genai, pydantic, jsonref" && echo "python deps ✓"
```

If any line is silent or errors, fix it before running — the engine exits `🚨 CRITICAL` on the first miss.

---

## First Run — the golden path

The entrypoint is `main.py`. The normal flow is **plan a project**, then **execute its tickets**.

**1. Plan** — expand an idea into an Epic, a Blueprint, and per-ticket markdown (runs the Nexus plane):

```bash
python3 main.py --idea "Build a CLI that converts JSON to CSV" --repo <url|path>
```

This writes `runs/<slug>/<NNN>_nexus_plan_<ts>_<uid>/artifacts/{epic.md, blueprint.md, TASK-01.md, …}`.
Open and skim those artifacts before executing.

**2. Execute a ticket** — run the Executor FSM for one generated ticket under the same project:

```bash
python3 main.py --run <slug> -f TASK-01
```

The Executor shallow-clones `--repo` into the run's `repo/` on a `feat/ticket-TASK-01` branch, runs the
build/test/SAST/review cycle, and makes one **atomic commit** on success. Add **`--push`** to push the
feature branch to `origin` after that commit.

**3. Resume** — after a crash or a halt, continue where the checkpoint left off:

```bash
python3 main.py --resume <slug>        # latest run; add a run number, e.g. `--resume <slug> 002`
```

(See the root [README Quick Start](../../README.md) for the legacy direct-run form
`--repo … --ticket … [-f|desc]` and more examples.)

### How you know it worked

- The log ends with `🟩 PIPELINE SUCCESS`, then `✅ Atomic commit on feat/ticket-TASK-01: …` (and
  `⬆️  Pushed feature branch to origin.` if you passed `--push`), followed by a FinOps **GRAND TOTAL** block.
- The run dir has `reports/finops_report.json` and **no** `incident_report.json`.
- Inspect the result: `git -C runs/<slug>/<run-dir>/repo log feat/ticket-TASK-01`.

### How you know it failed

- The log shows `🚨 CIRCUIT BREAKER OPEN` (retries exhausted) or `🚨 FINANCIAL CIRCUIT BREAKER OPEN`
  (budget breached), and the run writes `reports/incident_report.json`.
- Diagnose it with the **`/analyze-run`** skill (evidence-first root-cause from the checkpoint + audit log),
  per the [debugging-protocol](../../.claude/rules/debugging-protocol.md) rule. For a transient network
  blip, retry with `--resume <slug> <NNN> --reset-attempts`.

### Contributors: verify the engine itself

Tests, `bandit`, and the venv `python` are **WSL-only**. Run the suite as a smoke test:

```bash
wsl -e bash -lc "cd /mnt/c/code/async-agentic-sdlc && source venv/bin/activate && python3 -m unittest discover -s tests"
```

---

## Environment variable reference

`GEMINI_API_KEY` is the only **required** variable. Everything else is optional with the default shown.

| Variable | Default | Effect |
|---|---|---|
| **`GEMINI_API_KEY`** | — (**required**) | Credential for every structured agent (TechLead/QA/Reviewer/TechWriter/Arbiter + Nexus PO/SA/TPM). |
| `CLAUDE_CLI_BIN` | `claude` | Path to the Claude CLI binary; pin to the nvm Linux build under WSL. |
| `DEVELOPER_CLI_TIMEOUT` | `900` | Hard wall-clock ceiling (s) per Developer CLI session; child is killed+reaped on expiry. |
| `DEVELOPER_CLI_IDLE_TIMEOUT` | `120` | Inactivity ceiling (s); kills the child if it emits no output for this long. |
| `PIPELINE_BUDGET_USD` | `10.00` | Primary Financial Circuit Breaker gate (authoritative for Claude, estimated for Gemini). |
| `PIPELINE_BUDGET_TOKENS` | `1000000` | Secondary token ceiling (fresh in+out; cache excluded). |
| `PIPELINE_MAX_RETRIES` | `3` | Functional retry budget for the FSM cycle. |
| `ARBITER_TRIGGER_ATTEMPT` | `2` | First failing cycle on which the Arbiter may run. |
| `MAX_CONTRACT_AMENDMENTS` | `1` | Autonomous contract rewrites allowed per run. |
| `ARBITER_AMENDMENT_RETRY_BONUS` | `2` | Extra retry cycles granted when the contract is amended. |
| `PIPELINE_RUNS_BASE` | `runs` | Root directory for per-run session dirs. |
| `DOCKER_HOST` | (unset) | Set `tcp://127.0.0.1:2375` if the daemon isn't auto-detected (see Docker §3). |
| `RUNTIME_ENV` | (unset) | If `docker`, the startup check requires `src/` to be mounted read-only. |
| `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` | (unset) | **Explicit-proxy sites only** — propagated into the network-ON restore phase; the transparent corporate egress needs none. |
| `SDLC_SANDBOX_TAG` / `CORP_CA_PATH` | `latest` / corp path | Build-time only — consumed by `scripts/build_sandbox_images.sh`. |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `🚨 CRITICAL: Binary '<x>' not found in PATH` | Install the missing tool (`docker`/`claude`/`bandit`) and ensure it's on PATH — re-run the [pre-flight self-check](#pre-flight-self-check). |
| `🚨 CRITICAL: GEMINI_API_KEY is not set` | `export GEMINI_API_KEY=…` and persist it in `~/.bashrc` (Step 8). |
| `Unable to find image 'sdlc-sandbox/…'` / image pull fails | You skipped Step 7 — run `bash scripts/build_sandbox_images.sh`. There is no auto-pull; behind a corp proxy see [docker-on-windows.md](docker-on-windows.md) §6. |
| git `could not read Password … terminal prompts disabled` | Use `https://<user>:<token>@github.com/…` (a **bare token fails** — token is the password, not the user), or SSH. Note: a token in the URL persists into `project.json` and the clone's `.git/config` — prefer a credential helper or a throwaway token. |
| Run halts with `CIRCUIT BREAKER` + `incident_report.json` | Diagnose with `/analyze-run`. If the cause was a transient network/API blip, retry with `--resume <slug> <NNN> --reset-attempts`. |
| `RUNTIME_ENV=docker but 'src/' is writable` | In container mode `src/` must be immutable — mount it read-only (`:ro`) or run as a non-root user. |
| `docker: command not found` | Start the WSL2 engine: `sudo service docker start` (or `wsl -d Ubuntu -u root service docker start` from PowerShell). Confirm `docker-ce` per [docker-on-windows.md](docker-on-windows.md) §2 Step A. |
| `permission denied` on docker socket | Add your user to the `docker` group: `sudo usermod -aG docker $USER`, then restart WSL (`wsl --shutdown`). |
| `Cannot connect to the Docker daemon at tcp://127.0.0.1:2375` | The engine is down or `DOCKER_HOST` is wrong — start it and set `DOCKER_HOST=tcp://127.0.0.1:2375` (Docker §3). |
| `npm: command not found` | Install Node.js per Step 3. |
| `npm install -g` fails with `EPERM` / installs `claude-code-win32-x64` | You're on `/mnt/c/`. Move the project to `~/` and use nvm Node (Steps 3–4); `which node` must be a `/home/...` path. |
| Developer agent hangs with no console output | `claude` is resolving to a Windows `claude.exe`. Run `which claude`; if it shows `/mnt/c/...`, reinstall via nvm and set `CLAUDE_CLI_BIN=$(which claude)` (Step 6). The session is also bounded by `DEVELOPER_CLI_IDLE_TIMEOUT` / `DEVELOPER_CLI_TIMEOUT`. |
| WSL2 distro shows as WSL1 | `wsl --set-version Ubuntu-24.04 2` in PowerShell. |
