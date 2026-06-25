---
paths:
  - "**/*.md"
---

# Documentation paths are relative or portable — never machine-absolute

Rules, skills, prompts, `CLAUDE.md`, and docs are read by many contributors whose clones live in
different locations. NEVER hardcode a machine-specific absolute path — `c:\code\token-burners-factory`,
`/mnt/c/code/token-burners-factory`, `/c/code/token-burners-factory`, `C:\Users\<name>\…`,
`/home/<name>/…` — in any of them. Such a path is true on exactly one machine.

**What to write instead:**
- **Repo files / cross-references** — repo-root-relative paths (`src/nexus/runner.py`,
  `prompts/skills/engineering_guide.md`) or a markdown link to a sibling rule
  (`[run-layout-and-cli](run-layout-and-cli.md)`).
- **WSL commands** (`wsl -e bash -lc "…"`) — run from the repo root and let `wsl` inherit the working
  directory; drop the absolute `cd`: `wsl -e bash -lc "source venv/bin/activate && python3 -m unittest discover -s tests"`.
- **Run artifacts** — `runs/<project>/<NNN>_…/…`, relative to the repo root (SSOT
  [run-layout-and-cli](run-layout-and-cli.md)).
- **Illustrating the WSL ↔ Git-Bash mount split** — describe the prefix swap (`/mnt/c/…` ↔ `/c/…`)
  generically with a `<repo>` placeholder; do not append a concrete clone path. For the Read/Grep
  "use the Windows path" note, use a drive-letter placeholder (`C:\…`), not `c:\code\token-burners-factory`.

**Allowed absolutes** (location-independent by construction, not "where my clone lives"):
- a `~/…` WSL-home reference;
- a `/mnt/c/` *warning* about which filesystem NOT to use (see [setup.md](../../docs/guides/setup.md));
- an external URL.

**Exempt:** frozen historical artifacts under `docs/releases/iteration_*/` — they record verbatim what a
command was at release time; don't rewrite released notes.

**Why:** `/mnt/c/code/token-burners-factory` resolves only on the machine that authored it. A contributor
who clones under `~/` (the [setup.md](../../docs/guides/setup.md)-recommended ext4 location) or onto
another drive gets `No such file or directory`, and the checked-in governance leaks one person's local
layout.

**How to apply:** Before committing any rule / skill / prompt / `CLAUDE.md` / doc edit, grep your diff
for `c:\code`, `/mnt/c/code`, `/c/code`, `C:\Users`, `/home/`. If a hit is a "where my clone lives" path,
make it relative or portable per the list above.
