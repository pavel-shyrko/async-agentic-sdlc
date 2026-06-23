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
        "language_id": "go",
        "description": "Go 1.23 CLI runtime, full compile toolchain (go test; Semgrep SAST).",
    },
    "node-20-web": {
        "image": "sdlc-sandbox/node:latest",
        "build_cmd": "npm run build --if-present",
        "test_cmd": "npm test",
        "setup_cmd": "npm ci || npm install",
        # lint_cmd: HARD lint gate via the project's own eslint. run_lint_gate FIRST checks (host-side)
        # that an eslint config is present in the clone — absent → the gate is a no-op pass (a project
        # that never adopted eslint must not hard-fail). With a config, a real lint error is a non-zero
        # exit. format_cmd (eslint --fix) auto-applies the fixable subset first.
        "lint_cmd": "npx --no-install eslint .",
        # Best-effort: only fixes if a project-local eslint is installed (--no-install never fetches).
        # Non-fatal, so a project without eslint just skips the cleanup.
        "format_cmd": "npx --no-install eslint --fix . || true",
        "sandbox_env": {"HOME": "/tmp", "npm_config_cache": "/tmp/.npm"},  # nosec B108 — in-container tmpfs paths
        # Persist the npm download cache across the restore/build/test containers + runs.
        "cache_volume": {"name": "sdlc-cache-node", "mount": "/cache", "env": {"npm_config_cache": "/cache/npm"}},
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
        "lint_cmd": "dotnet format --verify-no-changes --no-restore",
        # Best-effort: --no-restore keeps it network-OFF; removes unused usings where the SDK supports it.
        "format_cmd": "dotnet format --no-restore",
        "sandbox_env": {"HOME": "/tmp", "DOTNET_CLI_HOME": "/tmp", "NUGET_PACKAGES": "/tmp/nuget", "XDG_DATA_HOME": "/tmp/.local"},  # nosec B108 — in-container tmpfs paths
        # Persist the NuGet global-packages folder; overrides the tmpfs NUGET_PACKAGES so a package
        # restored online once is reused offline on every later container/run (the NU1301 cure).
        "cache_volume": {"name": "sdlc-cache-dotnet", "mount": "/cache", "env": {"NUGET_PACKAGES": "/cache/nuget"}},
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
#   layout         "separate"  -> tests live in a dedicated tests/ dir (pytest discovery)
#                  "colocated" -> tests sit NEXT TO the source file (go test ./..., jest, dotnet test)
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
        "layout": "colocated",
        "test_root": None,      # colocated: tests sit next to source, no separate root
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

    # Colocated: test file sits next to the source file.
    if env_language(environment_id) == "node":
        test_name = f"{stem}.test{src_ext}"          # foo.ts -> foo.test.ts
    else:
        test_name = f"{profile['test_prefix']}{stem}{profile['test_suffix']}"  # go: foo_test.go / .NET: fooTests.cs
    return (f"{directory}/{test_name}" if directory else test_name), module_ref


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
