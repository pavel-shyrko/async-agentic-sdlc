# Nexus Control Plane — per-run state + checkpoint. Mirrors the executor's run-dir contract so a
# control-plane run is isolated under runs/run_<uuid>/ with logs/, reports/, and artifacts/, and can
# be resumed from reports/checkpoint.json. Kept separate from the executor's GlobalPipelineContext
# (which is git-/contract-shaped); Nexus only needs the idea, the phase outputs, and telemetry.
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.shared.core.models import RUNS_BASE, PipelineTelemetry

# Ordered control-plane phases. completed_phase holds the last FINISHED phase; resume skips any phase
# at or before it (reusing the persisted epic/blueprint), then continues from the next.
PHASES = ("PO", "SA", "TPM")


class NexusState(BaseModel):
    """Serializable state for one Nexus run — also the --resume checkpoint payload."""
    kind: Literal["nexus"] = "nexus"   # discriminator so main() can route a --resume checkpoint
    raw_idea: str
    run_dir: Path
    telemetry: PipelineTelemetry = Field(default_factory=PipelineTelemetry)
    epic_text: str = ""
    blueprint_text: str = ""
    tasks: list[dict] = Field(default_factory=list)
    completed_phase: str = ""          # "", "PO", "SA", "TPM"

    @classmethod
    def new(cls, raw_idea: str, run_dir: Path | None = None) -> "NexusState":
        """Mint a fresh run state, defaulting the run dir to RUNS_BASE/run_<uuid> (env-overridable)."""
        run_dir = run_dir or (RUNS_BASE / f"run_{uuid.uuid4().hex}")
        return cls(raw_idea=raw_idea, run_dir=Path(run_dir))

    # --- per-run meta dirs (recomputed from run_dir, never persisted — like WorkspacePaths.for_run) ---
    @property
    def logs_dir(self) -> Path:
        return self.run_dir / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.run_dir / "reports"

    @property
    def artifacts_dir(self) -> Path:
        return self.run_dir / "artifacts"

    @property
    def checkpoint_path(self) -> Path:
        return self.reports_dir / "checkpoint.json"

    def ensure_dirs(self) -> None:
        """Create the run meta-dirs (logs/reports/artifacts). Idempotent; safe on resume."""
        for d in (self.logs_dir, self.reports_dir, self.artifacts_dir):
            d.mkdir(parents=True, exist_ok=True)

    def is_done(self, phase: str) -> bool:
        """True if ``phase`` already finished in a prior run (resume should skip it)."""
        return self.completed_phase in PHASES[PHASES.index(phase):]

    def mark_done(self, phase: str) -> None:
        self.completed_phase = phase

    # --- checkpoint (same JSON dump/load pattern as GlobalPipelineContext) ---
    def save_checkpoint(self) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load_checkpoint(cls, path: Path) -> "NexusState":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
