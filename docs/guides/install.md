# Install & Run the `tbf` CLI

How to install the factory as a `pip` package and run it via the `tbf` command — without developing the
engine. For the full first-machine walk-through (WSL2, Docker, Node, venv), see
[setup.md](./setup.md); this guide is the short path for an operator who just wants to *use* `tbf`.

> ⚠️ **Everything runs inside WSL2 (Ubuntu) on Windows — never PowerShell/cmd.** The toolchain (Python,
> Docker, the `claude` CLI, `bandit`, `gh`) is Linux-only; the Windows interpreter lacks the deps. Open the
> **Ubuntu** terminal and work on the **Linux filesystem** (`~/…`, never `/mnt/c/…`). On native Linux/macOS,
> run the commands directly.

## 0. Get into WSL

If your prompt looks like `PS C:\Users\you>` (Windows PowerShell), you're in the wrong shell. Type:

```powershell
wsl
```

The prompt changes to something like `you@host:~$` and you can verify with `uname -a` (prints `… WSL2 …`).
Everything below runs in this Linux prompt.

---

## What you need (one-time, all inside WSL2)

| # | Thing | Why | Where |
|---|-------|-----|-------|
| 1 | Python 3.12+ | runs the engine | preinstalled on Ubuntu 24.04 |
| 2 | The `tbf` package | the CLI itself | `pip install` — see below |
| 3 | `claude` CLI (`npm i -g @anthropic-ai/claude-code`) + `claude auth login` | the Developer agent | [setup.md §6](./setup.md) |
| 4 | Docker (`docker-ce` in WSL2, **not** Docker Desktop) | sandboxed build/test/lint/SAST gates | [docker-on-windows.md](./docker-on-windows.md) |
| 5 | Sandbox images (`bash scripts/build_sandbox_images.sh`) | the per-language gate toolchains | [setup.md §7](./setup.md) — needs a source clone |
| 6 | `gh` CLI + `GITHUB_TOKEN` | only for `--auto-merge` / `--auto-execute` | [setup.md §9](./setup.md) |

Steps 4–5 require a **source clone** of the repo (the Docker images are built locally, never pulled from a
registry). So even when `tbf` is pip-installed, you clone the repo once to build the images.

---

## 1. Install the CLI

```bash
# create + activate an isolated venv (keeps deps out of the system Python):
python3 -m venv ~/tbf-cli && source ~/tbf-cli/bin/activate
# your prompt now starts with (tbf-cli) — that means the venv is active.

# from the default branch (once E7 is merged to main):
pip install git+https://github.com/<org>/async-agentic-sdlc.git

# …or from a specific branch / tag before the merge:
pip install git+https://github.com/Trouvere/async-agentic-sdlc.git@feat/installable-cli

tbf --help        # should print the full CLI usage
```

- **`tbf`** is the command this installs (short for *Token Burners Factory*). It's a drop-in for
  `python3 main.py` — every flag is identical.
- **`(tbf-cli)`** in your prompt is the active venv. Leave it with `deactivate`; re-enter a later session
  with `source ~/tbf-cli/bin/activate`. The `tbf` command only exists while the venv is active.

## 2. Set credentials

```bash
export GEMINI_API_KEY="your-gemini-key"        # required always (all structured agents)
export GITHUB_TOKEN="ghp_..."                  # required for --auto-merge / --auto-execute
# export GITHUB_REVIEWER_TOKEN="ghp_..."       # optional: a real PR approval (else --admin merge)
```

Persist them in `~/.bashrc` so every session has them. The Claude side is authenticated separately by
`claude auth login` (step 3 above), **not** an env var.

**Verify the credentials:**

```bash
# 1. env vars are set (should print the values, not empty lines):
echo "$GEMINI_API_KEY"
echo "$GITHUB_TOKEN"

# 2. the Gemini key actually works — a plan-only run is the real end-to-end check (Step 3, costs ~$0.02):
tbf --idea "hello world CLI"            # ✅ ends with `📊 [FINOPS] … ✅ Nexus complete`
                                        # ❌ a 401/403/INVALID_ARGUMENT means the key is wrong/unset

# 3. GitHub token is valid + has repo scope (only if you'll use --auto-merge / --auto-execute):
gh auth status                          # or: curl -sf -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user | grep login

# 4. Claude (the Developer agent) is authenticated:
claude auth status                      # or just `claude --version` to confirm it's on PATH
```

A failed `tbf --idea` with a Gemini auth error is the clearest signal the key is bad — env vars can be
*set* but still wrong.

## 3. Run

**Plan only — also the recommended first smoke test.** Turn an idea into an Epic + Blueprint + tickets
(no code yet). This needs **only `GEMINI_API_KEY`** — no Docker, no `claude`, no `gh` — so it's the fastest
way to confirm the install works. `--repo` is optional here.

```bash
tbf --idea "Build a CLI that converts JSON to CSV"
```

Artifacts land in `~/runs/<slug>/<NNN>_nexus_plan_.../artifacts/{epic.md, blueprint.md, TASK-*.md}`
(relative to where you ran the command). A `📊 [FINOPS] GRAND TOTAL … ✅ Nexus complete` tail means success
— typically a couple of cents. Inspect the result:

```bash
ls   ~/runs/*/001_nexus_plan_*/artifacts/
cat  ~/runs/*/001_nexus_plan_*/artifacts/epic.md
```

**Plan + build everything to `main`, in one shot** — the full autonomous loop (E3–E6):

```bash
tbf --idea "Build a CLI that converts JSON to CSV" \
    --repo https://github.com/<org>/<new-repo>.git \
    --auto-execute            # plan, then drive every ticket to main (implies --auto-merge)
    # --scaffold-deploy       # also generate + merge CI/CD config (E4)
    # --release               # also push a v* release tag (E6)
    # --budget 5              # cap the whole build at $5 (money-only breaker)
```

`--auto-execute` requires `--repo` and the forge env (`gh` + `GITHUB_TOKEN`); each ticket clones `main`
fresh, so it **implies `--auto-merge`** — every ticket must land on `main` before the next builds on it.

**Execute a single ticket** under an existing project:

```bash
tbf --run <slug> -f TASK-01 [--auto-merge]
```

**Resume** after a crash or a budget halt (re-pass a larger `--budget` to add money and continue):

```bash
tbf --resume <slug>           # add a run number for a specific run, e.g. `--resume <slug> 002`
```

## 3b. Where the output lands & how to view it

Every run writes to `runs/<slug>/<NNN>_<plane>_..._<ts>_<uid>/`, created **relative to the directory you
ran `tbf` from** (run from `~` → `~/runs/…`). One run dir holds:

| Path | What |
|------|------|
| `artifacts/` | planning output — `epic.md`, `blueprint.md`, `TASK-*.md` (nexus runs only) |
| `repo/` | the cloned target repo with the generated code (executor runs only) |
| `reports/checkpoint.json` | FSM state — the `--resume` anchor |
| `reports/incident_report.json` | written only on a halt — the failure dump |
| `logs/sdlc_audit.log` | full per-run audit trail |

**View from WSL** (same terminal):

```bash
cd ~/runs/<slug>/001_nexus_plan_*/artifacts/   # tab-completes; <slug> = your idea, kebab-cased
ls
cat epic.md          # or: less epic.md
```

**View from Windows** — the WSL filesystem is a network share. Easiest is to let WSL open Explorer for you:

```bash
cd ~/runs/<slug>/001_nexus_plan_*/
explorer.exe .       # opens this exact folder in Windows Explorer
```

Or paste the UNC path into Explorer's address bar — **use your real distro name** (find it with
`wsl -l -v` in PowerShell; e.g. `Ubuntu-24.04`, not `Ubuntu`):

```
\\wsl.localhost\Ubuntu-24.04\home\<user>\runs\<slug>\001_nexus_plan_...\artifacts
```

(On older Windows builds the prefix is `\\wsl$\` instead of `\\wsl.localhost\`.)

> Want runs in one fixed place regardless of where you launch `tbf`? Set `PIPELINE_RUNS_BASE` to an
> absolute path, e.g. `export PIPELINE_RUNS_BASE=~/tbf-runs`.

## 4. Verify it worked

```bash
tbf --help                    # CLI prints usage  → install OK
docker ps                     # daemon reachable   → gates can run
claude --version              # Developer agent    → present
gh auth status                # only if using --auto-merge
```

A planning run is the cheapest smoke test (no Docker needed): `tbf --idea "..." ` then open the generated
`artifacts/epic.md`.

---

## Notes & gotchas

- **Private target repos** need non-interactive git credentials (the engine never prompts) — see
  [setup.md → Git auth](./setup.md#git-auth-private-repos).
- **Two providers, two credentials**: Gemini via `GEMINI_API_KEY`, Claude via `claude auth login`. Both are
  required for a full `--auto-execute` run.
- **Re-build the sandbox images** (`scripts/build_sandbox_images.sh`) after any `docker/*.Dockerfile` change.
- **`bandit` not found** at startup → it ships as a dependency but must resolve on PATH; the pre-flight check
  (`check_environment`) fails fast with a clear message if it doesn't.

Related: [setup.md](./setup.md) (full machine setup), [devops_setup.md](./devops_setup.md) (one-time org
config for `--scaffold-deploy`), [the root README](../../README.md).
