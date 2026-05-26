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

> Do **not** install `docker.io` via apt — Docker Engine runs in WSL2 and the CLI on Windows. See [docs/docker-on-windows.md](docs/docker-on-windows.md).

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
| `docker: command not found` | Make sure Docker Desktop is running and WSL2 integration is enabled |
| `permission denied` on docker socket | Docker Desktop manages permissions — no `usermod` needed |
| `npm: command not found` | Install Node.js per step 2 |
| WSL2 distro shows as WSL1 | `wsl --set-version Ubuntu-24.04 2` in PowerShell |
