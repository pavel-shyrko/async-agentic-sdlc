# Platform Paved Road — single source of truth for executable runtimes.
# The SA selects an `environment_id` from this registry; downstream agents and the Docker
# adapter look up the canonical image + commands here, so no agent can invent a tech stack.
# `language_id` keys the per-language QA test profile (see QA_LANGUAGE_PROFILES).
#
# Gate execution (src/development/gates.py + docker_adapter.py):
#   image        custom sandbox image built by scripts/build_sandbox_images.sh — carries the test
#                runner + writable HOME/cache (stock images lack pytest etc. and EPERM on /.cache).
#   sandbox_env  env vars injected into the container so the non-root --user run has writable caches.
#   cache_volume {name, mount, env} — a PERSISTENT named docker volume for the package-download cache.
#                Survives the separate restore/build/test containers (each gets a fresh tmpfs /tmp) and
#                across runs. Mounted RW only on the network-ON restore phase, RO otherwise. Its `env`
#                overrides the tmpfs cache path so a once-restored package resolves offline thereafter.
#   setup_cmd    dependency restore, run in a NETWORK-ON phase before the network-OFF build/test.
#   build_cmd    compile/typecheck only (NEVER runs tests) — the post-Developer compile gate.
#   test_cmd     the functional-test command (network-OFF).
#   lint_cmd     OPTIONAL style/lint VERIFY command (network-OFF) — the HARD lint gate (run_lint_gate).
#                Must be non-zero-exit on any violation. This is the SSOT the DevOps-generated CI also
#                runs, so engine-green ⇒ CI-green. Paired with format_cmd, which auto-FIXES what this
#                VERIFIES (so only genuinely-unfixable findings, e.g. F841, ever reach an agent). An env
#                without lint_cmd → the lint gate is a no-op pass.
#   format_cmd   OPTIONAL deterministic cleanup run over the workspace (network-OFF) — autofixes lint +
#                formatting (strips unused imports, applies the formatter) before the lint gate verifies.
#                Best-effort/non-fatal.
#   test_compile_cmd  OPTIONAL compile-ONLY check of the QA tests (network-OFF) — builds the test
#                code but runs no test bodies; drives the pre-Reviewer QA test-compile gate.
#   empty_test_markers / ran_test_markers  OPTIONAL lowercased substrings of the test runner's output
#                that drive the orphan-test backstop (gates.ran_zero_tests) WITHOUT hardcoding any
#                language in the gate logic. empty_test_markers = the runner's "executed ZERO tests"
#                signatures; ran_test_markers = its "tests executed" signatures, which SUPPRESS the
#                backstop (multi-target safety). Omit BOTH to exempt a stack from the check entirely
#                (e.g. Go, whose per-package "[no test files]" line is not orphan-able).
#   failure_origin_markers  OPTIONAL substrings marking the ORIGIN line of a failure in this stack's
#                test/build output, so the feedback extractor keeps the root error (not just a blind tail)
#                for the Reviewer. failure_origin_markers() unions these with a cross-language generic base.
#   repo_map_ignore_dirs  OPTIONAL build/dependency OUTPUT dir names (never source) the repo-map walker
#                prunes for this stack (e.g. node_modules, bin, obj) so a fresh clone's artifacts don't
#                bloat the topology map. Hidden dirs (.git/.venv) are pruned separately by the walker.
#   comment_prefixes  OPTIONAL leading strings that mark a comment line in this stack's source files
#                (e.g. "#", "//", "<!--"), used by the documentation-guardrail scanner to check for a
#                top-of-file architectural justification. all_comment_prefixes() unions them across stacks.

# SAST is generic across all stacks — one Semgrep image (SAST_IMAGE/SAST_CMD), never per-language.

SUPPORTED_ENVIRONMENTS = {
    "python-3.12-core": {
        "image": "sdlc-sandbox/python:latest",
        "build_cmd": "python -m compileall -q .",
        # `python -m pytest` (not the bare `pytest` console script) so the sandbox cwd (/workspace) is
        # on sys.path[0] — lets QA's topology imports (`from src.converter import …`) resolve against
        # the repo-root `src` package (PEP 420 namespace; no __init__.py needed). The bare script would
        # insert only the test file's own dir, breaking cross-package imports. See BACKLOG #15.
        "test_cmd": "python -m pytest",
        # Compile-only check of the QA-generated tests (imports/collects, runs NOTHING) — surfaces
        # ImportError/SyntaxError before the Reviewer. Drives the pre-Reviewer QA test-compile gate.
        "test_compile_cmd": "python -m pytest --collect-only -q",
        "setup_cmd": "pip install -r requirements.txt 2>/dev/null || true",
        # lint_cmd: the HARD lint gate (run_lint_gate). `ruff check` catches lint rules format_cmd's
        # autofix could not apply (e.g. F841 unused-local — an *unsafe* fix ruff won't auto-apply), and
        # `ruff format --check` catches formatter drift. --no-cache on the check so ruff never leaves a
        # `.ruff_cache/` in the tree for a later `git add -A` to commit. SSOT shared with the generated CI.
        "lint_cmd": "ruff check --no-cache . && ruff format --check .",
        # format_cmd: deterministic cleanup pass — strips unused imports, autofixes safe lint, AND applies
        # the formatter (ruff format) so the lint gate's `ruff format --check` passes without rerouting the
        # (expensive) Developer for pure formatting. --exit-zero keeps a residual unfixable finding from
        # logging a spurious non-fatal warning; the pass is cleanup, not a gate. --no-cache: one-shot pass,
        # so skip the cache — otherwise ruff writes a `.ruff_cache/` into the repo that `git add -A` commits.
        "format_cmd": "ruff check --fix --exit-zero --quiet --no-cache . ; ruff format --quiet .",
        "sandbox_env": {"HOME": "/tmp", "XDG_CACHE_HOME": "/tmp/.cache", "PYTHONDONTWRITEBYTECODE": "1"},  # nosec B108 — in-container tmpfs paths
        # Persistent download cache (survives the separate restore/build/test containers + across runs);
        # mounted RW only on the network-ON restore phase. Overrides the tmpfs pip cache.
        "cache_volume": {"name": "sdlc-cache-python", "mount": "/cache", "env": {"PIP_CACHE_DIR": "/cache/pip"}},
        # Orphan-test backstop signals (gates.ran_zero_tests): pytest prints "no tests ran" for an empty
        # collection; any "<n> passed/failed/error" line proves it ran and suppresses the check.
        "empty_test_markers": ("no tests ran",),
        "ran_test_markers": (" passed", " failed", " error"),
        "failure_origin_markers": ("Traceback (most recent call", "ImportError", "ModuleNotFoundError", "cannot import name"),
        "repo_map_ignore_dirs": ("__pycache__",),
        "comment_prefixes": ("#", '"""', "'''"),
        "language_id": "python",
        "description": "Python 3.12 core runtime (pytest; Semgrep SAST).",
    },
    "go-1.23-cli": {
        "image": "sdlc-sandbox/go:latest",
        "build_cmd": "go build ./...",
        "test_cmd": "go test ./...",
        # Compile-only check: `go test -run=^$` builds every package INCLUDING `_test.go` (which
        # `go build ./...` skips) but runs ZERO tests — so QA's compile errors (unused imports,
        # undefined symbols) surface deterministically without executing/asserting. Drives the
        # pre-Reviewer QA test-compile gate.
        "test_compile_cmd": "go test -run=^$ ./...",
        "setup_cmd": "go mod download",
        # lint_cmd: HARD lint gate. `go vet` catches suspicious constructs; `test -z "$(gofmt -l .)"`
        # fails iff gofmt would reformat any file (gofmt -l lists unformatted files — a BARE PATH per
        # line, no :line:col, which classify_lint_findings handles). format_cmd (goimports/gofmt -w)
        # auto-applies the formatting this verifies.
        "lint_cmd": "go vet ./... && test -z \"$(gofmt -l .)\"",
        # goimports (NOT gofmt) removes unused imports — Go treats those as a HARD compile error, the
        # exact failure that bounced QA's tests through an extra Reviewer cycle. Baked into the image
        # (docker/go.Dockerfile); falls back to gofmt (always present) if the build couldn't fetch
        # goimports behind a proxy — gofmt still formats, just won't strip imports. Non-fatal post-QA pass.
        "format_cmd": "goimports -w . 2>/dev/null || gofmt -w .",
        "sandbox_env": {"HOME": "/tmp", "GOCACHE": "/tmp/.cache/go-build", "GOPATH": "/tmp/go", "GOMODCACHE": "/tmp/go/pkg/mod"},  # nosec B108 — in-container tmpfs paths
        # Persist the module DOWNLOAD cache (GOMODCACHE) only; the build cache (GOCACHE) stays on tmpfs.
        "cache_volume": {"name": "sdlc-cache-go", "mount": "/cache", "env": {"GOMODCACHE": "/cache/go/pkg/mod"}},
        # No empty/ran_test markers → the orphan-test backstop is EXEMPT for Go: `go test ./...` prints
        # `[no test files]` per-package even when sibling packages ran, and colocated Go tests can't be
        # orphaned the way a separate test project can — so there is no safe "ran zero" signal to key on.
        "failure_origin_markers": ("panic:", "--- FAIL", "build failed", "cannot find package"),
        "repo_map_ignore_dirs": ("vendor", "bin"),
        "comment_prefixes": ("//", "/*", "*"),
        "language_id": "go",
        "description": "Go 1.23 CLI runtime, full compile toolchain (go test; Semgrep SAST).",
    },
    "node-20-web": {
        "image": "sdlc-sandbox/node:latest",
        "build_cmd": "npm run build --if-present",
        "test_cmd": "npm test",
        "setup_cmd": "npm ci || npm install",
        # lint_cmd: HARD lint gate via the project's own eslint. SELF-GUARDS in the command itself: if the
        # clone carries no eslint config (flat eslint.config.* / legacy .eslintrc* / an "eslintConfig" key
        # in package.json) it echoes a note and exits 0 — a project that never adopted eslint must not
        # hard-fail. With a config, a real lint error is a non-zero exit. The guard lives HERE (registry),
        # NOT as a node-specific branch in gates.py, so the engine carries no language. Mirrors the dotnet
        # lint_cmd workspace self-guard. format_cmd (eslint --fix) auto-applies the fixable subset first.
        # Single line (no-newline adapter rule); valid both in sh -c (sandbox) and a GH Actions run step.
        "lint_cmd": "if ls eslint.config.js eslint.config.mjs eslint.config.cjs .eslintrc .eslintrc.* 2>/dev/null | grep -q . || grep -q '\"eslintConfig\"' package.json 2>/dev/null; then npx --no-install eslint .; else echo 'no eslint config at repo root — lint gate no-op pass'; fi",
        # Best-effort: only fixes if a project-local eslint is installed (--no-install never fetches).
        # Non-fatal, so a project without eslint just skips the cleanup.
        "format_cmd": "npx --no-install eslint --fix . || true",
        "sandbox_env": {"HOME": "/tmp", "npm_config_cache": "/tmp/.npm"},  # nosec B108 — in-container tmpfs paths
        # Persist the npm download cache across the restore/build/test containers + runs.
        "cache_volume": {"name": "sdlc-cache-node", "mount": "/cache", "env": {"npm_config_cache": "/cache/npm"}},
        # Orphan-test backstop signals (gates.ran_zero_tests): jest/vitest print "no tests found" for an
        # empty run; a "Tests:"/"passing"/"passed" summary proves it ran and suppresses the check.
        "empty_test_markers": ("no tests found", "no test files found"),
        "ran_test_markers": ("tests:", " passing", " passed"),
        "failure_origin_markers": ("Error:", "Cannot find module", "ReferenceError", "SyntaxError", "TypeError:"),
        "repo_map_ignore_dirs": ("node_modules", "dist", "build", "out", "coverage"),
        "comment_prefixes": ("//", "/*", "*"),
        "language_id": "node",
        "description": "Node.js 20 / JS / React (node, npm — frontend build & tests; Semgrep SAST).",
    },
    "dotnet-10-sdk": {
        "image": "sdlc-sandbox/dotnet:latest",
        "build_cmd": "dotnet build",
        "test_cmd": "dotnet test",
        # Serialized + retried restore: `--disable-parallel` and the image's NuGet.Config
        # `maxHttpRequestsPerSource=1` stop the parallel-TLS BURST that a transparent corporate
        # proxy/AV drops (the NU1301 deadlock); 3 attempts absorb a transient drop. Single line so it
        # passes the adapter's no-newline command validation.
        "setup_cmd": "for i in 1 2 3; do dotnet restore --disable-parallel && exit 0; sleep 5; done; exit 1",
        # lint_cmd: HARD lint gate. `dotnet format --verify-no-changes` exits non-zero iff the formatter
        # WOULD change anything (style/whitespace/unused usings). --no-restore keeps it network-OFF (the
        # restore phase ran first). format_cmd (dotnet format) auto-applies the same fixes beforehand.
        # MUST resolve a SINGLE explicit workspace target: `dotnet format` (unlike build/restore/test,
        # which prefer the solution) hard-crashes in ParseWorkspaceOptions when the CWD is ambiguous ("Both
        # a MSBuild project file and solution file found in '.'") OR empty ("no project or solution file
        # found") — exit 1, masking lint as a permanent red and looping the FSM (the latter also fired the
        # non-fatal format-pass crash before any solution existed). Resolution: prefer the root solution —
        # the newer .slnx (the .NET 10 `dotnet new sln` DEFAULT) OR the classic .sln (the dotnet_core skill
        # mandates exactly one at the root) — else a lone root .csproj (single-project repos); if NEITHER
        # resolves, SKIP cleanly (exit 0) instead of passing '.' and crashing. `dotnet format` accepts a
        # .slnx target; globbing only *.sln would MISS a .slnx and silently no-op the gate. The final
        # `dotnet format` propagates its real exit code (2 = "would change") so the verify gate still fails
        # on actual findings. Single line (no-newline adapter rule); valid in both `sh -c` (sandbox) and a
        # GH Actions run step.
        "lint_cmd": "ws=$(ls *.slnx *.sln 2>/dev/null | head -n1); ws=${ws:-$(ls *.csproj 2>/dev/null | head -n1)}; if [ -z \"$ws\" ]; then echo 'no .slnx/.sln/.csproj at repo root — nothing to verify'; exit 0; fi; dotnet format \"$ws\" --verify-no-changes --no-restore",
        # Best-effort autofix: same workspace resolution; --no-restore keeps it network-OFF; removes unused
        # usings where the SDK supports it. Skips cleanly (never crashes) when no workspace resolves.
        "format_cmd": "ws=$(ls *.slnx *.sln 2>/dev/null | head -n1); ws=${ws:-$(ls *.csproj 2>/dev/null | head -n1)}; if [ -z \"$ws\" ]; then exit 0; fi; dotnet format \"$ws\" --no-restore",
        "sandbox_env": {"HOME": "/tmp", "DOTNET_CLI_HOME": "/tmp", "NUGET_PACKAGES": "/tmp/nuget", "XDG_DATA_HOME": "/tmp/.local"},  # nosec B108 — in-container tmpfs paths
        # Persist the NuGet global-packages folder; overrides the tmpfs NUGET_PACKAGES so a package
        # restored online once is reused offline on every later container/run (the NU1301 cure).
        "cache_volume": {"name": "sdlc-cache-dotnet", "mount": "/cache", "env": {"NUGET_PACKAGES": "/cache/nuget"}},
        # Orphan-test backstop signals (gates.ran_zero_tests): `dotnet test` prints "No test is available"
        # when a *Tests.cs lands in a project the solution never compiles; a "Passed!"/"Failed!" summary
        # proves the runner executed and suppresses the check.
        "empty_test_markers": ("no test is available", "no test source files were specified", "no test projects were found"),
        "ran_test_markers": ("passed!", "failed!"),
        "failure_origin_markers": ("error CS", "error MSB", "Stack trace:", "Unhandled exception"),
        "repo_map_ignore_dirs": ("bin", "obj", "artifacts"),
        "comment_prefixes": ("//", "/*", "*", "<!--"),
        "language_id": "dotnet",
        "description": ".NET 10 SDK (full toolchain — dotnet build & dotnet test; Semgrep SAST).",
    },
}

# Generic SAST — ONE scanner for every language (replaces per-stack bandit/gosec/npm-audit). Runs in
# its own image over /workspace; scanning does not execute the code. The image VENDORS its rules
# (docker/semgrep.Dockerfile) so the scan runs fully OFFLINE (`--network none`) — `--config auto` would
# call semgrep.dev and fail behind a corporate TLS proxy. `--metrics off` suppresses the telemetry
# call; `--error` makes findings a non-zero (gate-failing) exit. Keep tag in sync with the build script.
SAST_IMAGE = "sdlc-sandbox/semgrep:latest"
SAST_CMD = "semgrep scan --error --metrics off --config /opt/semgrep-rules /workspace"


# ==========================================================================================
# QA LANGUAGE PROFILES — drive environment-aware test generation in the QA node.
# Keyed by the env's `language_id`. The QA agent NEVER hardcodes Python; it reads the profile
# for the ticket's environment_id to decide test file extension, placement, framework idioms,
# and which contract files are even testable source (vs docs/config/package markers).
#
#   layout         "separate"  -> tests live in a dedicated tests/ dir (pytest discovery), flat under test_root
#                  "colocated" -> tests sit NEXT TO the source file (go test ./..., jest)
#                  "project"   -> tests live INSIDE a separate test PROJECT dir resolved per-run from the
#                                 contract's test build-manifest (.NET: tests/<Name>.Tests/; see
#                                 resolve_test_project_dir) — NOT next to source, NOT a static root
#   source_exts    extensions QA generates tests for; everything else (.md, LICENSE, .gitignore,
#                  lockfiles, package markers) is filtered out.
# Assembly is language-neutral: the QA agent always returns the COMPLETE test file (skills-driven,
# overwrite_existing=true) — there is no per-language merge/parser in the engine.
# ==========================================================================================
QA_LANGUAGE_PROFILES = {
    "python": {
        "layout": "separate",
        "test_root": "tests",   # separate-layout: tests live under repo/<test_root>/ (SSOT for placement)
        "source_exts": (".py",),
        "test_prefix": "test_",
        "test_suffix": ".py",
        "module_ref_style": "dotted",
        "framework_label": "unittest (pytest-discovered)",
        "package_markers": ("__init__.py",),
    },
    "go": {
        "layout": "colocated",
        "test_root": None,      # colocated: tests sit next to source, no separate root
        "source_exts": (".go",),
        "test_prefix": "",
        "test_suffix": "_test.go",
        "module_ref_style": "path",
        "framework_label": "Go testing (go test ./...)",
        "package_markers": ("go.mod", "go.sum"),
    },
    "node": {
        "layout": "colocated",
        "test_root": None,      # colocated: tests sit next to source, no separate root
        "source_exts": (".ts", ".tsx", ".js", ".jsx"),
        "test_prefix": "",
        "test_suffix": ".test",   # extension is appended from the source file (.test.ts / .test.js)
        "module_ref_style": "path",
        "framework_label": "jest/vitest (npm test)",
        "package_markers": ("package.json", "package-lock.json", "tsconfig.json", "yarn.lock"),
    },
    "dotnet": {
        # "project" layout: tests live INSIDE a separate test PROJECT directory (tests/<Name>.Tests/),
        # NOT next to the source. The dir is build-defined (varies by solution name) and is resolved at
        # runtime from the TechLead contract's `*.Tests.csproj` (resolve_test_project_dir); colocating a
        # `*Tests.cs` in src/ would put it in the PRODUCTION project's glob (no xUnit ref → CS0246) and
        # contradicts the mandated src/+tests/ split. test_root stays None (resolved per-run, not static).
        "layout": "project",
        "test_root": None,
        "source_exts": (".cs",),
        "test_prefix": "",
        "test_suffix": "Tests.cs",
        "module_ref_style": "namespace",
        "framework_label": "xUnit (dotnet test)",
        "package_markers": (),  # *.csproj excluded via the generic non-source filter below
    },
}

# ==========================================================================================
# CANONICAL .gitignore TEMPLATES — sourced verbatim from github/gitignore (functional patterns;
# explanatory prose comments trimmed). Keyed by the env's `language_id`. The TPM injects the
# matching block into TASK-01's repository-preparation directive instead of inventing patterns.
#
# WHY THIS IS THE SSOT (not the agent): an agent-authored ignore file once emitted an UNANCHORED
# `json2csv` (the binary name) to ignore the compiled binary — but git applies an unanchored token
# to ANY path component, so the `cmd/json2csv/` SOURCE directory was ignored too. `git add -A`
# then silently dropped `main.go` from the production snapshot and the Reviewer rejected the run in
# a loop until the circuit breaker tripped. These templates ignore build output by EXTENSION
# (`*.exe`, `*.test`, `*.out`) and by ANCHORED dir (`/bin/`, `bin/`, `obj/`) — NEVER by a bare
# project/binary name — so a same-named source dir can never be swallowed.
# ==========================================================================================
GITIGNORE_TEMPLATES = {
    "go": (
        "# Binaries for programs and plugins\n"
        "*.exe\n*.exe~\n*.dll\n*.so\n*.dylib\n\n"
        "# Test binary, built with `go test -c`\n"
        "*.test\n\n"
        "# Code coverage profiles and other test artifacts\n"
        "*.out\ncoverage.*\n*.coverprofile\nprofile.cov\n\n"
        "# Go workspace file\n"
        "go.work\ngo.work.sum\n\n"
        "# Build output directory (anchored to repo root — never matches a source dir)\n"
        "/bin/\n\n"
        "# env file\n.env\n"
    ),
    "python": (
        "# Byte-compiled / optimized / DLL files\n"
        "__pycache__/\n*.py[cod]\n*$py.class\n\n"
        "# C extensions\n*.so\n\n"
        "# Distribution / packaging\n"
        "build/\ndist/\ndownloads/\neggs/\n.eggs/\nwheels/\n*.egg-info/\n*.egg\nMANIFEST\n\n"
        "# Unit test / coverage reports\n"
        "htmlcov/\n.tox/\n.nox/\n.coverage\n.coverage.*\ncoverage.xml\n*.cover\n.hypothesis/\n.pytest_cache/\n.cache\n\n"
        "# Type checkers\n.mypy_cache/\n.dmypy.json\n.pyre/\n.pytype/\n\n"
        "# Environments\n.env\n.venv\nenv/\nvenv/\nENV/\n"
    ),
    "node": (
        "# Logs\n"
        "logs\n*.log\nnpm-debug.log*\nyarn-debug.log*\nyarn-error.log*\n\n"
        "# Dependency directories\n"
        "node_modules/\njspm_packages/\n\n"
        "# Build output\n"
        "dist/\nbuild/\nout/\n.next\n.nuxt\n.output\n\n"
        "# Coverage\n"
        "coverage/\n*.lcov\n.nyc_output\n\n"
        "# Caches\n"
        ".npm\n.eslintcache\n.cache\n.parcel-cache\n*.tsbuildinfo\n\n"
        "# env files\n.env\n.env.*\n!.env.example\n"
    ),
    "dotnet": (
        "# Build results (anchored dir patterns — never match a source dir)\n"
        "[Bb]in/\n[Oo]bj/\n[Dd]ebug/\n[Rr]elease/\n[Dd]ebugPublic/\n[Rr]eleases/\nartifacts/\n\n"
        "# Visual Studio\n"
        ".vs/\n*.user\n*.suo\n*.userosscache\n*.sln.docstates\n\n"
        "# Test results\n"
        "[Tt]est[Rr]esult*/\n*.trx\nTestResult.xml\n\n"
        "# NuGet\n"
        "*.nupkg\nproject.lock.json\nproject.fragment.lock.json\n\n"
        "# Logs\n*.log\n"
    ),
}


def get_gitignore_template(environment_id: str) -> str:
    """Return the canonical .gitignore body for an environment_id (keyed via its language_id).

    Fails fast on an unsupported environment_id — parity with get_qa_profile — so a bad id never
    silently yields an empty ignore file.
    """
    return GITIGNORE_TEMPLATES[env_language(environment_id)]


# Doc/config artifacts that are NEVER testable source in any stack (fixes "tests for README/LICENSE").
_NON_SOURCE_NAMES = frozenset({"license", "license.md", "license.txt", "readme.md", ".gitignore", ".dockerignore"})
_NON_SOURCE_EXTS = frozenset({".md", ".txt", ".lock", ".json", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".csproj", ".sln"})


def get_qa_profile(environment_id: str) -> dict:
    """Return the QA test profile for an environment_id (keyed via its language_id).

    Raises ValueError on an unsupported environment_id so the QA node fails fast rather than
    silently defaulting to Python.
    """
    env = SUPPORTED_ENVIRONMENTS.get(environment_id)
    if env is None:
        raise ValueError(
            f"Unsupported environment_id '{environment_id}'. "
            f"Choose one of: {sorted(SUPPORTED_ENVIRONMENTS)}."
        )
    return QA_LANGUAGE_PROFILES[env["language_id"]]


def env_language(environment_id: str) -> str:
    """The language_id for an environment_id (fails fast on unsupported)."""
    env = SUPPORTED_ENVIRONMENTS.get(environment_id)
    if env is None:
        raise ValueError(f"Unsupported environment_id '{environment_id}'.")
    return env["language_id"]


def all_source_extensions() -> tuple[str, ...]:
    """Every source-file extension across all QA language profiles (e.g. ``.py``, ``.cs``, ``.ts``),
    deduped and ordered longest-first then alphabetically.

    The SSOT for any engine parser that must recognize a source/diagnostic file path (e.g. the gates'
    compile-error regex). Registry-derived ON PURPOSE: adding a language to QA_LANGUAGE_PROFILES extends
    those parsers automatically, with NO edit to the gate code — the language stays out of the engine.
    """
    exts = {ext for profile in QA_LANGUAGE_PROFILES.values() for ext in profile["source_exts"]}
    return tuple(sorted(exts, key=lambda e: (-len(e), e)))


def extension_language_map() -> dict[str, str]:
    """Map each source extension → its ``language_id`` (e.g. ``.cs`` → ``dotnet``), derived from
    QA_LANGUAGE_PROFILES.

    The SSOT for extension-based language inference (the TechLead's early skill routing). Registry-derived
    so a newly-registered language routes automatically — no edit to the agent code. Precision (e.g. not
    matching ``.cs`` inside ``.csproj``) is the CALLER's concern at match time, not this map's.
    """
    return {
        ext: language_id
        for language_id, profile in QA_LANGUAGE_PROFILES.items()
        for ext in profile["source_exts"]
    }


# Cross-language failure-origin markers appended to every env's stack-specific set — generic enough that
# an unknown/new stack still gets a useful (non-empty) marker list without a registry entry.
_GENERIC_FAILURE_MARKERS = ("ERROR:", "FAILED")


def failure_origin_markers(environment_id: str) -> tuple[str, ...]:
    """Substrings that mark the ORIGIN line of a failure in a stack's test/build output.

    Lets the feedback extractor keep the ROOT error (not just a blind tail slice) for the Reviewer. Derived
    from the env registry (per-env ``failure_origin_markers``) + a cross-language generic base — so a
    non-Python stack is no longer second-class (the Python-only bias this replaces). Unknown env → the
    generic base alone, never empty.
    """
    spec = SUPPORTED_ENVIRONMENTS.get(environment_id) or {}
    return tuple(spec.get("failure_origin_markers", ())) + _GENERIC_FAILURE_MARKERS


def all_comment_prefixes() -> tuple[str, ...]:
    """Union of comment-line prefixes across all supported environments (registry-derived).

    Used by the documentation-guardrail scanner so the engine carries no hardcoded language
    syntax. Adding a new stack: declare its ``comment_prefixes`` in SUPPORTED_ENVIRONMENTS.
    """
    seen: dict[str, None] = {}
    for spec in SUPPORTED_ENVIRONMENTS.values():
        for prefix in spec.get("comment_prefixes", ()):
            seen[prefix] = None
    return tuple(seen)


def repo_map_ignore_dirs(environment_id: str | None = None) -> frozenset[str]:
    """Directory NAMES the repo-map walker prunes as build/dependency OUTPUT (never source).

    Registry-derived (per-env ``repo_map_ignore_dirs``). With an ``environment_id``, returns THAT stack's
    dirs; WITHOUT one — the TechLead builds the map before the language is known — returns the UNION across
    all stacks, so a fresh clone's ``node_modules``/``bin``/``obj`` never bloats the topology map for any
    stack. Hidden dirs (``.git``/``.venv``/…) are pruned separately by the walker, not here.
    """
    if environment_id is not None:
        spec = SUPPORTED_ENVIRONMENTS.get(environment_id) or {}
        return frozenset(spec.get("repo_map_ignore_dirs", ()))
    return frozenset(
        d for spec in SUPPORTED_ENVIRONMENTS.values() for d in spec.get("repo_map_ignore_dirs", ())
    )


def _posix(rel_path: str) -> str:
    return rel_path.replace("\\", "/").strip("/")


def is_testable_source(environment_id: str, rel_path: str) -> bool:
    """True only for real source files of the target stack — never docs, config, lockfiles, or
    package markers. This is the single filter that stops QA writing tests for README/LICENSE/
    .gitignore/go.mod/go.sum/package.json/*.csproj etc.
    """
    profile = get_qa_profile(environment_id)
    path = _posix(rel_path)
    name = path.rsplit("/", 1)[-1]
    lower = name.lower()
    if not path or lower in _NON_SOURCE_NAMES:
        return False
    if name in profile["package_markers"]:
        return False
    dot = name.rfind(".")
    ext = name[dot:].lower() if dot > 0 else ""
    if ext in _NON_SOURCE_EXTS:
        return False
    return ext in profile["source_exts"]


def derive_test_target(environment_id: str, rel_source_path: str) -> tuple[str, str]:
    """Map a source file path to its (test_file_path, module_ref) for the target stack.

    The returned test path is relative to the tests dir for a "separate" layout (python) or
    relative to the repo root for a "colocated" layout (go/node/dotnet). ``module_ref`` is the
    identity string handed to the QA prompt so it imports/targets the right module.
    """
    profile = get_qa_profile(environment_id)
    path = _posix(rel_source_path)
    directory, _, filename = path.rpartition("/")
    dot = filename.rfind(".")
    stem = filename[:dot] if dot > 0 else filename
    src_ext = filename[dot:] if dot > 0 else ""

    style = profile["module_ref_style"]
    if style == "dotted":
        module_ref = path.rsplit(".", 1)[0].replace("/", ".") if dot > 0 else path.replace("/", ".")
    else:  # path / namespace — present the source path as-is; the skill translates it.
        module_ref = path

    if profile["layout"] == "separate":
        path_no_ext = path[: -len(src_ext)] if src_ext else path
        slug = path_no_ext.replace("/", "_")
        return f"{profile['test_prefix']}{slug}{profile['test_suffix']}", module_ref

    if profile["layout"] == "project":
        # Test source lives FLAT inside a separate test project dir (resolved by the QA node from the
        # contract via resolve_test_project_dir) — return just the bare filename, no source-dir prefix.
        return f"{profile['test_prefix']}{stem}{profile['test_suffix']}", module_ref

    # Colocated: test file sits next to the source file (go/node).
    if env_language(environment_id) == "node":
        test_name = f"{stem}.test{src_ext}"          # foo.ts -> foo.test.ts
    else:
        test_name = f"{profile['test_prefix']}{stem}{profile['test_suffix']}"  # go: foo_test.go
    return (f"{directory}/{test_name}" if directory else test_name), module_ref


def resolve_test_project_dir(files_to_modify: list[str]) -> str | None:
    """For a ``layout == "project"`` stack (.NET), find the test project's directory from the contract.

    The test build manifest (``*.Tests.csproj``) is Developer-owned build glue listed in the TechLead
    contract's ``files_to_modify`` (e.g. ``tests/JsonToCsv.Tests/JsonToCsv.Tests.csproj``). Return its
    posix PARENT dir (``tests/JsonToCsv.Tests``) so the QA node writes ``*Tests.cs`` INSIDE the project the
    test runner compiles. Returns ``None`` when no test manifest is contracted (the QA node then falls
    back to a plain ``tests/`` dir and warns — the dotnet_core skill mandates the manifest, so this is rare).
    """
    for entry in files_to_modify or []:
        path = _posix(entry)
        if path.rsplit("/", 1)[-1].endswith("Tests.csproj"):
            directory, _, _ = path.rpartition("/")
            return directory or None
    return None


# Node test files use a separate naming convention (jest/vitest) than the prefix/suffix profile.
_NODE_TEST_SUFFIXES = (".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".spec.ts", ".spec.js")


def is_test_file(environment_id: str, rel_path: str) -> bool:
    """True if ``rel_path``'s basename matches the target stack's test-file naming convention.

    Single SSOT for "is this a test file": Python ``test_*.py``, Go ``*_test.go``, .NET ``*Tests.cs``,
    Node ``*.test.*``/``*.spec.*``. Used by the QA agent (zombie disposal, test snapshot) AND by the
    production-snapshot filter so the Developer is fenced off from tests REGARDLESS of placement
    (colocated or a separate tests dir).
    """
    profile = get_qa_profile(environment_id)
    name = _posix(rel_path).rsplit("/", 1)[-1]
    if env_language(environment_id) == "node":
        return name.endswith(_NODE_TEST_SUFFIXES)
    return name.startswith(profile["test_prefix"]) and name.endswith(profile["test_suffix"])
