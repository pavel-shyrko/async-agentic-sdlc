# Run tests / bandit / python through WSL

Always run this project's test suite, `bandit`, and any `venv/bin/python` invocation through **WSL**,
never the Windows interpreter.

**Why:** The Windows `python` (3.13, under `~/AppData/.../Python313`) does NOT have the project
dependencies (`instructor`, `google.genai`, …) → `ModuleNotFoundError`. The project `venv/` is a
WSL-created venv (POSIX `venv/bin/` layout, Python 3.12, symlinked to `/usr/bin/python3`); from
Windows/Git-Bash that `python` symlink is a **broken link**, so it only resolves inside WSL.

**How to apply:** Wrap commands, e.g.
- tests: `wsl -e bash -lc "cd /mnt/c/code/token-burners-factory && source venv/bin/activate && python3 -m unittest discover -s tests"`
- bandit: `wsl -e bash -lc "cd /mnt/c/code/token-burners-factory && venv/bin/bandit -r src/"`

If config fails to build the genai client at import (it constructs at module-import time), set a dummy
`GEMINI_API_KEY=test-key` before the command — a dummy suffices for the mocked suites.

**Path translation when reading run artifacts:** the `Bash` tool runs **Git Bash**, where the drive is
mounted at `/c/...`; the user runs commands in **WSL**, where it is `/mnt/c/...`. So a run path the user
pastes (`/mnt/c/code/token-burners-factory/runs/...`) must be rewritten to `/c/code/token-burners-factory/runs/...`
when you `cd`/`cat`/`grep` it from the Bash tool — a verbatim `/mnt/c/...` path fails `No such file or
directory`. (Prefer the dedicated Read/Grep tools with the Windows path `c:\code\...` to sidestep this.)

Related: [debugging-protocol](debugging-protocol.md).
