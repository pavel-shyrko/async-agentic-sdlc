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

## 1. System Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv bandit
```

> Do **not** install `docker.io` via apt and do **not** use Docker Desktop. The upstream `docker-ce` Engine runs in WSL2 and the CLI on Windows — install it by following [docs/docker-on-windows.md](docs/docker-on-windows.md) (§2 Step A), which also binds the API to loopback (`127.0.0.1:2375`) only.

## 2. Node.js (inside WSL2)

If Node.js is not installed:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

## 3. Project Directory

```bash
mkdir -p ~/agentic-poc && cd ~/agentic-poc
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

## 6. Pre-pull Docker Image

```bash
docker pull python:3.11-slim
```

## 7. Claude CLI

```bash
npm install -g @anthropic-ai/claude-code
```

Then authenticate **once manually**:

```bash
claude
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
| WSL2 distro shows as WSL1 | `wsl --set-version Ubuntu-24.04 2` in PowerShell |
