import re
from pathlib import Path
from functools import lru_cache

from src.core.models import GlobalPipelineContext

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SYSTEM_DIR = _REPO_ROOT / "prompts" / "system"
_SKILLS_DIR = _REPO_ROOT / "prompts" / "skills"

PROMPT_SECTION_SEPARATOR = "\n---\n"


@lru_cache(maxsize=16)
def get_system_prompt(agent_name: str) -> str:
    path = _SYSTEM_DIR / f"{agent_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"System prompt '{agent_name}' not found at {path}")
    return path.read_text(encoding="utf-8").strip()


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
    from src.utils.llm import run_structured_llm
    from src.core.models import SkillRelevance

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
) -> str:
    """Declaratively assemble the skill context for an agent node.

    Reads every skill in ``prompts/skills/``, parses its frontmatter, and includes
    the body when the node is targeted and the type-specific gate passes:
      - ``global``   → always
      - ``topology`` → always (body is ``.format(**topology_kwargs)``-ed)
      - ``stateful`` → only on retry
      - ``domain``   → tag intersection with the contract's ``domain_tags``; on a
        miss, an LLM relevance fallback decides inclusion.

    Only ``topology`` bodies are ``.format()``-ed; the strict-type placeholder is
    filled via a brace-safe ``.replace()`` so skill bodies may freely contain
    literal ``{}`` (e.g. code blocks) without crashing the router.
    """
    topology_kwargs = topology_kwargs or {}
    strict_rules = getattr(ctx.contract, "strict_type_validation_rules", "")
    parts: list[str] = []

    for path in sorted(_SKILLS_DIR.glob("*.md")):
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        if node_name not in meta.get("nodes", []):
            continue

        skill_type = meta.get("type")
        if skill_type in ("global", "topology"):
            include = True
        elif skill_type == "stateful":
            include = is_retry
        elif skill_type == "domain":
            tags = set(ctx.contract.domain_tags) if ctx.contract else set()
            include = bool(set(meta.get("triggers", [])) & tags)
            if not include:
                include = await fallback_semantic_search(ctx.pr_description, body)
        else:
            include = False

        if not include:
            continue

        body = body.replace("{strict_type_validation_rules}", strict_rules)
        if skill_type == "topology":
            body = body.format(**topology_kwargs)
        parts.append(body.strip())

    return "\n\n".join(parts)
