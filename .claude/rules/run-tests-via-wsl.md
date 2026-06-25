# Run tests / bandit / python through WSL

Always run this project's test suite, `bandit`, and any `venv/bin/python` invocation through **WSL**,
never the Windows interpreter.

**Why:** The Windows `python` (3.13, under `~/AppData/.../Python313`) does NOT have the project
dependencies (`instructor`, `google.genai`, …) → `ModuleNotFoundError`. The project `venv/` is a
WSL-created venv (POSIX `venv/bin/` layout, Python 3.12, symlinked to `/usr/bin/python3`); from
Windows/Git-Bash that `python` symlink is a **broken link**, so it only resolves inside WSL.

**How to apply:** Wrap commands and run them **from the repo root** — `wsl` inherits the current working
directory, so no absolute `cd` is needed (and a hardcoded one breaks on every other clone), e.g.
- tests: `wsl -e bash -lc "source venv/bin/activate && python3 -m unittest discover -s tests"`
- bandit: `wsl -e bash -lc "venv/bin/bandit -r src/"`

If config fails to build the genai client at import (it constructs at module-import time), set a dummy
`GEMINI_API_KEY=test-key` before the command — a dummy suffices for the mocked suites.

**Path translation when reading run artifacts:** the `Bash` tool runs **Git Bash**, where the drive is
mounted at `/c/...`; the user runs commands in **WSL**, where it is `/mnt/c/...`. So a `/mnt/c/...` run
path the user pastes must be rewritten by swapping the `/mnt/c` prefix for `/c` (e.g.
`/mnt/c/<repo>/runs/...` → `/c/<repo>/runs/...`) when you `cd`/`cat`/`grep` it from the Bash tool — a
verbatim `/mnt/c/...` path fails `No such file or directory`. (Prefer the dedicated Read/Grep tools with
the repo-relative Windows path to sidestep this.)

Related: [debugging-protocol](debugging-protocol.md).
