# Platform Paved Road — single source of truth for executable runtimes.
# The SA selects an `environment_id` from this registry; downstream agents and the Docker
# adapter look up the canonical image + commands here, so no agent can invent a tech stack.
# `language_id` keys the per-language QA test profile (see QA_LANGUAGE_PROFILES).
#
# Gate execution (src/executor/nodes/gates.py + docker_adapter.py):
#   image        custom sandbox image built by scripts/build_sandbox_images.sh — carries the test
#                runner + writable HOME/cache (stock images lack pytest etc. and EPERM on /.cache).
#   sandbox_env  env vars injected into the container so the non-root --user run has writable caches.
#   setup_cmd    dependency restore, run in a NETWORK-ON phase before the network-OFF build/test.
#   build_cmd    compile/typecheck only (NEVER runs tests) — the post-Developer compile gate.
#   test_cmd     the functional-test command (network-OFF).
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
        "setup_cmd": "pip install -r requirements.txt 2>/dev/null || true",
        "sandbox_env": {"HOME": "/tmp", "XDG_CACHE_HOME": "/tmp/.cache", "PYTHONDONTWRITEBYTECODE": "1"},
        "language_id": "python",
        "description": "Python 3.12 core runtime (pytest; Semgrep SAST).",
    },
    "go-1.23-cli": {
        "image": "sdlc-sandbox/go:latest",
        "build_cmd": "go build ./...",
        "test_cmd": "go test ./...",
        "setup_cmd": "go mod download",
        "sandbox_env": {"HOME": "/tmp", "GOCACHE": "/tmp/.cache/go-build", "GOPATH": "/tmp/go", "GOMODCACHE": "/tmp/go/pkg/mod"},
        "language_id": "go",
        "description": "Go 1.23 CLI runtime, full compile toolchain (go test; Semgrep SAST).",
    },
    "node-20-web": {
        "image": "sdlc-sandbox/node:latest",
        "build_cmd": "npm run build --if-present",
        "test_cmd": "npm test",
        "setup_cmd": "npm ci || npm install",
        "sandbox_env": {"HOME": "/tmp", "npm_config_cache": "/tmp/.npm"},
        "language_id": "node",
        "description": "Node.js 20 / JS / React (node, npm — frontend build & tests; Semgrep SAST).",
    },
    "dotnet-10-sdk": {
        "image": "sdlc-sandbox/dotnet:latest",
        "build_cmd": "dotnet build",
        "test_cmd": "dotnet test",
        "setup_cmd": "dotnet restore",
        "sandbox_env": {"HOME": "/tmp", "DOTNET_CLI_HOME": "/tmp", "NUGET_PACKAGES": "/tmp/nuget", "XDG_DATA_HOME": "/tmp/.local"},
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
        "source_exts": (".py",),
        "test_prefix": "test_",
        "test_suffix": ".py",
        "module_ref_style": "dotted",
        "framework_label": "unittest (pytest-discovered)",
        "package_markers": ("__init__.py",),
    },
    "go": {
        "layout": "colocated",
        "source_exts": (".go",),
        "test_prefix": "",
        "test_suffix": "_test.go",
        "module_ref_style": "path",
        "framework_label": "Go testing (go test ./...)",
        "package_markers": ("go.mod", "go.sum"),
    },
    "node": {
        "layout": "colocated",
        "source_exts": (".ts", ".tsx", ".js", ".jsx"),
        "test_prefix": "",
        "test_suffix": ".test",   # extension is appended from the source file (.test.ts / .test.js)
        "module_ref_style": "path",
        "framework_label": "jest/vitest (npm test)",
        "package_markers": ("package.json", "package-lock.json", "tsconfig.json", "yarn.lock"),
    },
    "dotnet": {
        "layout": "colocated",
        "source_exts": (".cs",),
        "test_prefix": "",
        "test_suffix": "Tests.cs",
        "module_ref_style": "namespace",
        "framework_label": "xUnit (dotnet test)",
        "package_markers": (),  # *.csproj excluded via the generic non-source filter below
    },
}

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
