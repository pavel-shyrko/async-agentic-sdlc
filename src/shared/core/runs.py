# Per-run directory layout + project umbrella. One project = one idea (Nexus) or one ticket (standalone
# executor), living under <runs-base>/<slug>/; every run (planning OR execution) is a numbered,
# human-readable sub-dir there, so a glance at runs/ tells you the task, the plane, and the order.
# Shared by the executor (runner.py) and the Nexus control plane so both name runs identically.
#
# The runs-base is injected (Projects(base)) rather than read from a module global, so tests stay
# hermetic by pointing a store at a temp dir.
import re
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

# Slugs are URL-ish (lowercase) for the project folder; run-dir labels (ticket ids) preserve case.
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")
_RUN_PREFIX_RE = re.compile(r"^(\d{3})_")


def slugify(text: str, max_len: int = 40) -> str:
    """Human-friendly, filesystem-safe lowercase slug for a project folder (fallback ``run``)."""
    s = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "run"


def _safe_label(text: str, max_len: int = 30) -> str:
    """Sanitise a run label (e.g. a ticket id) for a dir name, PRESERVING case and ``-._``."""
    s = _LABEL_RE.sub("-", (text or "").strip()).strip("-")
    return (s[:max_len].rstrip("-") or "run") if s else "run"


def allocate_run_dir(project_dir: Path, plane: str, label: str) -> Path:
    """Compute the next numbered run dir under ``project_dir``:
    ``NNN_<plane>_<label>_<YYYYMMDD-HHMMSS>_<uid6>`` — sortable, readable, unique (the uid suffix
    guarantees no overwrite even for two runs in the same second). Caller mkdirs the result."""
    project_dir.mkdir(parents=True, exist_ok=True)
    nums = [int(m.group(1)) for d in project_dir.iterdir()
            if d.is_dir() and (m := _RUN_PREFIX_RE.match(d.name))]
    nnn = f"{(max(nums) + 1) if nums else 1:03d}"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return project_dir / f"{nnn}_{plane}_{_safe_label(label)}_{ts}_{uuid.uuid4().hex[:6]}"


class Project(BaseModel):
    """Persisted manifest (``project.json``) for one idea/ticket umbrella — captures the target repo
    once so every later ticket run reuses it. Pure data; the filesystem lives in ``Projects``."""
    slug: str
    idea: str = ""
    repo: str | None = None
    base_branch: str = "main"
    created_at: str = ""


class Projects:
    """Filesystem-backed project store rooted at a runs/ base (injected, so tests stay hermetic)."""

    def __init__(self, base: Path):
        self.base = Path(base)

    def dir(self, slug: str) -> Path:
        return self.base / slug

    def _manifest(self, slug: str) -> Path:
        return self.dir(slug) / "project.json"

    def exists(self, slug: str) -> bool:
        return self._manifest(slug).is_file()

    def load(self, slug: str) -> Project:
        return Project.model_validate_json(self._manifest(slug).read_text(encoding="utf-8"))

    def save(self, project: Project) -> Project:
        self.dir(project.slug).mkdir(parents=True, exist_ok=True)
        self._manifest(project.slug).write_text(project.model_dump_json(indent=2), encoding="utf-8")
        return project

    def create(self, seed: str, *, idea: str = "", repo: str | None = None, base_branch: str = "main") -> Project:
        """Mint a NEW project, suffixing the slug (-2, -3, …) on collision with a different project."""
        base_slug = slugify(seed)
        slug, n = base_slug, 2
        while self.dir(slug).exists():
            slug, n = f"{base_slug}-{n}", n + 1
        return self.save(Project(
            slug=slug, idea=idea, repo=repo, base_branch=base_branch,
            created_at=datetime.now().strftime("%Y%m%d-%H%M%S"),
        ))

    def get_or_create(self, seed: str, *, idea: str = "", repo: str | None = None, base_branch: str = "main") -> Project:
        """Reuse an existing project by slug (stacking another numbered run under it), else create it —
        so repeated direct runs of the same ticket share one umbrella."""
        slug = slugify(seed)
        if self.exists(slug):
            project = self.load(slug)
            if repo and not project.repo:   # capture a repo provided on a later run
                project.repo = repo
                self.save(project)
            return project
        return self.create(seed, idea=idea, repo=repo, base_branch=base_branch)

    def run_dirs(self, slug: str) -> list[Path]:
        d = self.dir(slug)
        if not d.exists():
            return []
        return sorted(c for c in d.iterdir() if c.is_dir() and _RUN_PREFIX_RE.match(c.name))

    def latest_run(self, slug: str, plane: str | None = None) -> Path | None:
        runs = [d for d in self.run_dirs(slug) if plane is None or f"_{plane}_" in d.name]
        return runs[-1] if runs else None

    def run_by_number(self, slug: str, nnn: str | int) -> Path | None:
        prefix = f"{int(nnn):03d}_"
        return next((d for d in self.run_dirs(slug) if d.name.startswith(prefix)), None)

    def allocate(self, slug: str, plane: str, label: str) -> Path:
        return allocate_run_dir(self.dir(slug), plane, label)
