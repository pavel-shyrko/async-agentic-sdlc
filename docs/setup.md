# Setup & Run Guide

## Prerequisites (Windows)

- Windows 10/11 with WSL2 enabled
- Docker configured for WSL2 — see [docs/docker-on-windows.md](docs/docker-on-windows.md)
- WSL2 distro: Ubuntu 24.04 (recommended)
- Node.js + npm installed inside WSL2

## 0. WSL2 Setup (if not done)

In PowerShell (as Administrator):

```powershell
wsl --install -d Ubuntu-24.04
```

Restart, then open the Ubuntu terminal and create a user when prompted.

For Docker setup (Engine in WSL2 + CLI on Windows), follow [docs/docker-on-windows.md](docs/docker-on-windows.md).

---

All remaining steps run **inside the WSL2 terminal (Ubuntu)**.

> **CRITICAL — work on the Linux filesystem, not `/mnt/c/`.** Clone and run the project under your WSL home (`~/...`, an ext4 virtual disk), never under `/mnt/c/...`. Running from `/mnt/c/` causes `EPERM`/permission failures, slow I/O, and — worst of all — makes `npm -g` link the **Windows** `claude.exe` (`claude-code-win32-x64`) across the WSL↔Win32 interop boundary, which stalls the Developer agent's stdout pipe. Every tool (`node`, `npm`, `claude`, `python`) must resolve to a Linux path under `~/`, never `/mnt/c/`. Verify with `which node claude` at the end.

## 1. System Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv bandit
```

> Do **not** install `docker.io` via apt and do **not** use Docker Desktop. The upstream `docker-ce` Engine runs in WSL2 and the CLI on Windows — install it by following [docs/docker-on-windows.md](docs/docker-on-windows.md) (§2 Step A), which also binds the API to loopback (`127.0.0.1:2375`) only.

## 2. Node.js (native, inside WSL2 via nvm)

Install Node **inside Linux** with `nvm` — do not use a Windows/Scoop `node`. `nvm` keeps everything under `~/.nvm` (Linux fs), which sidesteps NTFS permission and antivirus conflicts.

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc          # or re-open the terminal
nvm install --lts
nvm use --lts
```

Verify Node resolves to a Linux path (must start with `/home/...`, never `/mnt/c/...`):

```bash
which node    # expected: /home/<you>/.nvm/versions/node/v.../bin/node
```

## 3. Project Directory (on the Linux filesystem)

Clone/place the project under your WSL home, never under `/mnt/c/`:

```bash
mkdir -p ~/projects && cd ~/projects
# git clone <repo-url> async-agentic-sdlc && cd async-agentic-sdlc
```

## 4. Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

## 5. Install Python Dependencies

```bash
pip install --upgrade pip
pip install instructor google-genai pydantic bandit pytest jsonref
```

## 6. Build the Sandbox Images

The runtime gates run tests + SAST inside per-environment sandbox images (test runner + writable
caches baked in) plus a generic Semgrep image for SAST. Build them once (re-run after editing any
`docker/*.Dockerfile`):

```bash
bash scripts/build_sandbox_images.sh
```

This builds `sdlc-sandbox/{python,go,node,dotnet}:latest` plus `sdlc-sandbox/semgrep:latest` (the
generic SAST scanner with rules **vendored** so it runs fully offline — no `semgrep.dev` call, which
fails behind a corporate TLS proxy). The tags must match `SUPPORTED_ENVIRONMENTS[...]["image"]` and
`SAST_IMAGE` in `src/shared/core/environments.py`.

**Dependency restore behind the corporate network:** the **first** run of each stack restores its
packages **online** into a persistent docker cache volume (`sdlc-cache-{python,go,node,dotnet}`);
every later run resolves **offline** from that volume, so a flaky proxy can no longer cause a
`NU1301`/feed-unreachable halt. This needs only the corporate **CA** in the WSL trust store — no
`HTTP_PROXY` for the (transparent) Godeltech egress. See
[docker-on-windows.md](docker-on-windows.md) §4 for the CA install and §6 for the full restore /
proxy / NU1301 details.

## 7. Claude CLI (native Linux build)

With the nvm Node active (step 2), install the CLI globally — this pulls the **Linux** build, not `claude-code-win32-x64`:

```bash
npm install -g @anthropic-ai/claude-code
```

Verify it resolves to a Linux path (NOT `/mnt/c/.../claude.exe`):

```bash
which claude    # expected: /home/<you>/.nvm/versions/node/v.../bin/claude
```

Then authenticate **once manually**:

```bash
claude
```

Pin the orchestrator's Developer agent to this exact binary so it never resolves to a Windows `claude.exe` on PATH (read by `CLAUDE_CLI_BIN` in `src/shared/core/config.py`):

```bash
echo 'export CLAUDE_CLI_BIN=$(which claude)' >> ~/.bashrc
source ~/.bashrc
```

## 8. Environment Variables

```bash
export GEMINI_API_KEY="your_actual_key_here"
```

> Get your key at [Google AI Studio](https://aistudio.google.com/app/apikey). Never commit real keys to version control.

Optional FinOps control — the cumulative token budget for the Financial Circuit Breaker (default `1000000`):

```bash
export PIPELINE_BUDGET_TOKENS="1000000"
```

Optional — wall-clock ceiling (seconds) for one Developer CLI session; on expiry the child is killed+reaped so a stalled `claude` can't hang the run (default `900`):

```bash
export DEVELOPER_CLI_TIMEOUT="900"
```

To persist across sessions, add to `~/.bashrc`:

```bash
echo 'export GEMINI_API_KEY="your_actual_key_here"' >> ~/.bashrc
source ~/.bashrc
```

## 9. Run the Orchestrator

```bash
python3 orchestrator.py
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `docker: command not found` | Start the WSL2 engine: `sudo service docker start` (or `wsl -d Ubuntu -u root service docker start` from PowerShell). Confirm `docker-ce` is installed per [docs/docker-on-windows.md](docs/docker-on-windows.md) §2 Step A. |
| `permission denied` on docker socket | Add your user to the `docker` group: `sudo usermod -aG docker $USER`, then restart WSL (`wsl --shutdown`). |
| `Cannot connect to the Docker daemon at tcp://127.0.0.1:2375` | The engine is down or `DOCKER_HOST` is unset/wrong — start the engine and ensure `DOCKER_HOST=tcp://127.0.0.1:2375` (see [docs/docker-on-windows.md](docs/docker-on-windows.md) §3). |
| `npm: command not found` | Install Node.js per step 2 |
| `npm install -g` fails with `EPERM` / installs `claude-code-win32-x64` | You are on `/mnt/c/`. Move the project to `~/` and use nvm Node (steps 2–3); `which node` must be a `/home/...` path. |
| Developer agent hangs with no console output | `claude` is resolving to a Windows `claude.exe`. Run `which claude` — if it shows `/mnt/c/...`, reinstall via nvm and set `CLAUDE_CLI_BIN=$(which claude)` (step 7). The session is also bounded by `DEVELOPER_CLI_TIMEOUT`. |
| WSL2 distro shows as WSL1 | `wsl --set-version Ubuntu-24.04 2` in PowerShell |
