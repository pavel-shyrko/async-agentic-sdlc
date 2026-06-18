import re
from pathlib import Path
from functools import lru_cache

from src.shared.core.models import GlobalPipelineContext
from src.shared.core.observability import log

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SYSTEM_DIR = _REPO_ROOT / "prompts" / "system"
_SKILLS_DIR = _REPO_ROOT / "prompts" / "skills"

PROMPT_SECTION_SEPARATOR = "\n---\n"


@lru_cache(maxsize=16)
def get_system_prompt(agent_name: str) -> str:
    path = _SYSTEM_DIR / f"{agent_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"System prompt '{agent_name}' not found at {path}")
    return path.read_text(encoding="utf-8").strip()


def _format_supported_platforms() -> str:
    """Render the Paved-Road registry as a bullet list for prompt injection."""
    from src.shared.core.environments import SUPPORTED_ENVIRONMENTS
    return "\n".join(f"- {key}: {env['description']}" for key, env in SUPPORTED_ENVIRONMENTS.items())


def _format_gitignore_templates() -> str:
    """Render the canonical per-environment .gitignore templates as labelled fenced blocks.

    The TPM copies the block whose `environment_id` matches the ticket into TASK-01 verbatim, so
    the ignore file is engine-curated (github/gitignore-sourced) — never an agent's invention that
    can ignore a same-named source directory (see GITIGNORE_TEMPLATES rationale in environments.py).
    """
    from src.shared.core.environments import SUPPORTED_ENVIRONMENTS, get_gitignore_template
    blocks = []
    for env_id in SUPPORTED_ENVIRONMENTS:
        blocks.append(f"`{env_id}`:\n```gitignore\n{get_gitignore_template(env_id).rstrip()}\n```")
    return "\n\n".join(blocks)


# Canonical README scaffold — aligned with GitHub's "About READMEs" guidance (what the project does,
# why it's useful, how to get started, how to use it, how to test, license). The TPM copies this into
# TASK-01 and fills every <...> slot with REAL content distilled from the Epic/Blueprint — so the
# README reflects the actual project, never generic filler. Build/test commands come from the env's
# Paved-Road entry (injected separately), so "Getting Started" is accurate, not invented.
README_SCAFFOLD = """# <Project Name — the real name, from the Epic/Blueprint>

<One-to-three sentences: WHAT this project does and WHY it is useful. Distil the Epic goal — concrete,
no marketing filler, no "this project is a tool that...".>

## Features
- <key user-facing capability, drawn from a Blueprint user story>
- <another concrete capability — one bullet per real feature, not aspirational>

## Tech Stack
<version-pinned runtime and libraries, copied verbatim from the Blueprint Tech Stack>

## Getting Started

### Prerequisites
<the runtime/toolchain the selected environment_id requires, with the pinned version>

### Installation & Build
```sh
<the selected environment_id's setup + build commands — see the injected per-env command table>
```

## Usage
```sh
<the exact invocation with the REAL flags/arguments from the CLI specification (e.g. -i, -o, -d)>
```

## Running Tests
```sh
<the selected environment_id's test command — see the injected per-env command table>
```

## License
<the license declared in this ticket's LICENSE file (e.g. MIT © 2026 <holder>)>
"""


def _format_env_commands() -> str:
    """Render each environment's Paved-Road setup/build/test commands for the README scaffold."""
    from src.shared.core.environments import SUPPORTED_ENVIRONMENTS
    return "\n".join(
        f"- `{env_id}`: setup `{env['setup_cmd']}` | build `{env['build_cmd']}` | test `{env['test_cmd']}`"
        for env_id, env in SUPPORTED_ENVIRONMENTS.items()
    )


def get_system_prompt_with_platforms(agent_name: str) -> str:
    """Load a system prompt and inject the engine-curated assets into its placeholders:
    ``{injected_supported_platforms_list}`` (Paved-Road registry), ``{injected_gitignore_templates}``
    (canonical .gitignore per env), ``{injected_readme_scaffold}`` (GitHub-aligned README structure),
    and ``{injected_env_commands}`` (per-env setup/build/test commands).

    Uses a brace-safe ``.replace()`` (not ``.format()``) — matching the
    ``{strict_type_validation_rules}`` convention below — so the prompt body may
    freely contain literal ``{}`` (e.g. fenced code) without crashing. ``.replace()`` is a no-op
    when a placeholder is absent, so prompts that use only some (e.g. ``sa.md``) are unaffected.
    """
    return (
        get_system_prompt(agent_name)
        .replace("{injected_supported_platforms_list}", _format_supported_platforms())
        .replace("{injected_gitignore_templates}", _format_gitignore_templates())
        .replace("{injected_readme_scaffold}", README_SCAFFOLD)
        .replace("{injected_env_commands}", _format_env_commands())
    )


def get_system_prompt_sections(agent_name: str, separator: str = PROMPT_SECTION_SEPARATOR) -> tuple[str, str]:
    """Loads a two-section system prompt (system rules `---` user template) and validates
    its structure. Raises ValueError if the separator is missing or a section is empty."""
    raw = get_system_prompt(agent_name)
    if separator not in raw:
        raise ValueError(
            f"Malformed system prompt '{agent_name}': missing required section separator "
            f"'---' (on its own line). See prompts/system/{agent_name}.md."
        )
    head, tail = (part.strip() for part in raw.split(separator, 1))
    if not head or not tail:
        raise ValueError(
            f"Malformed system prompt '{agent_name}': both the system-rules and "
            f"user-template sections must be non-empty. See prompts/system/{agent_name}.md."
        )
    return head, tail


def generate_repo_map(repo_dir: Path) -> str:
    """Render a recursive, depth-unlimited tree of ``repo_dir`` for topology-aware prompting.

    Prunes hidden dirs (``.git``, ``.venv``, ``.pytest_cache``, …) and ``__pycache__`` so the map
    reflects meaningful source/test topology. Returns "" when the dir is absent, so callers can
    inject it unconditionally.
    """
    root = Path(repo_dir)
    if not root.is_dir():
        return ""

    def _ignored(name: str) -> bool:
        return name.startswith(".") or name == "__pycache__"

    lines: list[str] = [f"{root.name}/"]

    def _walk(directory: Path, prefix: str) -> None:
        entries = sorted(
            (e for e in directory.iterdir() if not _ignored(e.name)),
            key=lambda e: (e.is_file(), e.name.lower()),  # dirs first, then files, alpha
        )
        for i, entry in enumerate(entries):
            last = i == len(entries) - 1
            connector = "└── " if last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")
            if entry.is_dir():
                _walk(entry, prefix + ("    " if last else "│   "))

    _walk(root, "")
    return "\n".join(lines)


@lru_cache(maxsize=16)
def get_skill(skill_name: str) -> str:
    path = _SKILLS_DIR / f"{skill_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Skill prompt '{skill_name}' not found at {path}")
    return path.read_text(encoding="utf-8").strip()


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """Split a skill markdown file into (frontmatter_dict, body).

    Frontmatter is the leading ``---``-delimited block. Values shaped like
    ``[a, b, c]`` become lists; everything else is a stripped scalar string.
    Stdlib-only (no pyyaml dependency). Returns ``({}, raw)`` when absent.
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.DOTALL)
    if not m:
        return {}, raw
    block, body = m.group(1), m.group(2)
    meta: dict = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        list_match = re.match(r"^\[(.*)\]$", value)
        if list_match:
            meta[key] = [item.strip() for item in list_match.group(1).split(",") if item.strip()]
        else:
            meta[key] = value
    return meta, body


async def fallback_semantic_search(pr_description: str, file_body: str) -> bool:
    """Prompt-based relevance fallback for domain skills whose tags miss the contract.

    Reuses the existing structured-LLM infra (no embeddings SDK). Returns True when
    the model scores relevance above threshold; degrades to False on any error.
    """
    from src.shared.utils.llm import run_structured_llm
    from src.shared.core.models import SkillRelevance

    prompt = (
        f"Evaluate if the following skill/rule is required for this PR.\n"
        f"PR: {pr_description}\n"
        f"Skill: {file_body}"
    )
    try:
        result, _ = await run_structured_llm(
            "reviewer",
            SkillRelevance,
            [{"role": "user", "content": prompt}],
        )
        return result.score > 0.7
    except Exception:
        return False


async def build_agent_context(
    node_name: str,
    ctx: GlobalPipelineContext,
    is_retry: bool = False,
    topology_kwargs: dict | None = None,
    inferred_tags: list[str] | None = None,
) -> str:
    """Declaratively assemble the skill context for an agent node.

    Reads every skill in ``prompts/skills/``, parses its frontmatter, and includes
    the body when the node is targeted and the type-specific gate passes:
      - ``global``   → always
      - ``topology`` → always (body is ``.format(**topology_kwargs)``-ed)
      - ``stateful`` → only on retry
      - ``domain``   → tag intersection with ``inferred_tags`` unioned with the
        contract's ``domain_tags``; on a miss, an LLM relevance fallback decides
        inclusion. ``inferred_tags`` lets a caller route deterministically before a
        contract exists (e.g. the techlead, whose contract is produced downstream).

    Only ``topology`` bodies are ``.format()``-ed; the strict-type placeholder is
    filled via a brace-safe ``.replace()`` so skill bodies may freely contain
    literal ``{}`` (e.g. code blocks) without crashing the router.
    """
    topology_kwargs = topology_kwargs or {}
    strict_rules = getattr(ctx.contract, "strict_type_validation_rules", "")
    parts: list[str] = []
    # Routing telemetry — the router was previously silent, so logs gave no way to confirm which skills
    # actually reached a node's prompt. Collected here and emitted as one line below.
    included: list[str] = []
    domain_fallback: list[str] = []
    excluded: list[str] = []

    for path in sorted(_SKILLS_DIR.glob("*.md")):
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        if node_name not in meta.get("nodes", []):
            continue
        skill_id = meta.get("skill_id", path.stem)

        skill_type = meta.get("type")
        if skill_type in ("global", "topology"):
            include = True
        elif skill_type == "stateful":
            include = is_retry
        elif skill_type == "domain":
            tags = set(inferred_tags or []) | (set(ctx.contract.domain_tags) if ctx.contract else set())
            include = bool(set(meta.get("triggers", [])) & tags)
            if not include:
                include = await fallback_semantic_search(ctx.pr_description, body)
                if include:
                    domain_fallback.append(skill_id)
        else:
            include = False

        if not include:
            excluded.append(skill_id)
            continue

        included.append(skill_id)
        body = body.replace("{strict_type_validation_rules}", strict_rules)
        if skill_type == "topology":
            body = body.format(**topology_kwargs)
        parts.append(body.strip())

    log.info(
        f"   [SKILLS] {node_name} | included: {included}"
        + (f" | domain-fallback: {domain_fallback}" if domain_fallback else "")
        + (f" | excluded: {excluded}" if excluded else "")
    )

    # Living ADR: inject the on-disk architecture state into every consuming node's context.
    # GUARD: the document does not exist on the first task — never do a bare read_text().
    repo_dir = getattr(ctx.workspace_paths, "repo_dir", None) if ctx.workspace_paths else None
    if repo_dir is not None:
        adr_path = repo_dir / "docs" / "architecture_state.md"
        adr_content = (
            adr_path.read_text(encoding="utf-8").strip()
            if adr_path.exists()
            else "(No architecture state documented yet. This is the first iteration.)"
        )
        parts.append("=== LIVING ARCHITECTURE DOCUMENT (ADR) ===\n" + adr_content)

    return "\n\n".join(parts)
