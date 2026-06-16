# Platform Paved Road — single source of truth for executable runtimes.
# The SA selects an `environment_id` from this registry; downstream agents and the Docker
# adapter look up the canonical image + commands here, so no agent can invent a tech stack.
# `language_id` keys the per-language QA test profile (see QA_LANGUAGE_PROFILES).

SUPPORTED_ENVIRONMENTS = {
    "python-3.12-core": {
        "image": "python:3.12-slim",
        "sast_cmd": "bandit -r .",
        "test_cmd": "pytest",
        "language_id": "python",
        "description": "Python 3.12 core runtime (slim — stable C-extension builds; bandit SAST, pytest).",
    },
    "go-1.23-cli": {
        "image": "golang:1.23-alpine",
        "sast_cmd": "gosec ./...",
        "test_cmd": "go test ./...",
        "language_id": "go",
        "description": "Go 1.23 CLI runtime, full compile toolchain (gosec SAST, go test).",
    },
    "node-20-web": {
        "image": "node:20-alpine",
        "sast_cmd": "npm audit --audit-level=high",
        "test_cmd": "npm test",
        "language_id": "node",
        "description": "Node.js 20 / JS / React (node, npm, yarn — frontend build & tests; npm audit SAST).",
    },
    "dotnet-10-sdk": {
        "image": "mcr.microsoft.com/dotnet/sdk:10.0-alpine",
        "sast_cmd": "dotnet list package --vulnerable --include-transitive",
        "language_id": "dotnet",
        "test_cmd": "dotnet test",
        "description": ".NET 10 SDK (full toolchain — dotnet build & dotnet test; vulnerable-package scan SAST).",
    },
}


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
#   uses_ast       only Python uses the ast.parse-based incremental assembly; other languages
#                  use whole-file text assembly (the model returns the complete suite).
# ==========================================================================================
QA_LANGUAGE_PROFILES = {
    "python": {
        "layout": "separate",
        "source_exts": (".py",),
        "test_prefix": "test_",
        "test_suffix": ".py",
        "module_ref_style": "dotted",
        "fence_lang": "python",
        "uses_ast": True,
        "framework_label": "unittest (pytest-discovered)",
        "package_markers": ("__init__.py",),
    },
    "go": {
        "layout": "colocated",
        "source_exts": (".go",),
        "test_prefix": "",
        "test_suffix": "_test.go",
        "module_ref_style": "path",
        "fence_lang": "go",
        "uses_ast": False,
        "framework_label": "Go testing (go test ./...)",
        "package_markers": ("go.mod", "go.sum"),
    },
    "node": {
        "layout": "colocated",
        "source_exts": (".ts", ".tsx", ".js", ".jsx"),
        "test_prefix": "",
        "test_suffix": ".test",   # extension is appended from the source file (.test.ts / .test.js)
        "module_ref_style": "path",
        "fence_lang": "typescript",
        "uses_ast": False,
        "framework_label": "jest/vitest (npm test)",
        "package_markers": ("package.json", "package-lock.json", "tsconfig.json", "yarn.lock"),
    },
    "dotnet": {
        "layout": "colocated",
        "source_exts": (".cs",),
        "test_prefix": "",
        "test_suffix": "Tests.cs",
        "module_ref_style": "namespace",
        "fence_lang": "csharp",
        "uses_ast": False,
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
