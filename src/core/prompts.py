from pathlib import Path
from functools import lru_cache

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SYSTEM_DIR = _REPO_ROOT / "prompts" / "system"
_SKILLS_DIR = _REPO_ROOT / "prompts" / "skills"


@lru_cache(maxsize=16)
def get_system_prompt(agent_name: str) -> str:
    path = _SYSTEM_DIR / f"{agent_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"System prompt '{agent_name}' not found at {path}")
    return path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=16)
def get_skill(skill_name: str) -> str:
    path = _SKILLS_DIR / f"{skill_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Skill prompt '{skill_name}' not found at {path}")
    return path.read_text(encoding="utf-8").strip()
