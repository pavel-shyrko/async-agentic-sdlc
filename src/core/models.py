import os
import re
from pathlib import Path
from pydantic import BaseModel, Field, field_validator

# ==========================================
# ARTIFACT DIRECTORY STRUCTURE (canonical defaults)
# ==========================================
# Base is env-overridable so parallel pipelines can target separate trees.
ARTIFACTS_DIR = Path(os.environ.get("PIPELINE_ARTIFACTS_BASE", "artifacts"))
CODE_DIR = ARTIFACTS_DIR / "code"
TESTS_DIR = ARTIFACTS_DIR / "tests"
LOGS_DIR = ARTIFACTS_DIR / "logs"
REPORTS_DIR = ARTIFACTS_DIR / "reports"

class WorkspacePaths(BaseModel):
    code_dir: Path = CODE_DIR
    tests_dir: Path = TESTS_DIR
    logs_dir: Path = LOGS_DIR
    reports_dir: Path = REPORTS_DIR

    def model_post_init(self, __context) -> None:
        for d in (self.code_dir, self.tests_dir, self.logs_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)

# ==========================================
# CONTRACTS & PIPELINE STATE
# ==========================================
class ArchitectureContract(BaseModel):
    files_to_modify: list[str] = Field(description="List of target source file paths.")
    instruction: str = Field(description="Technical directives for the Developer Agent.")
    function_signatures: str = Field(description="Function names, arguments, types, and exceptions.")
    strict_type_validation_rules: str = Field(description="Type validation rules for the implementation.")
    architecture_reasoning: str = Field(description="Justification for the chosen design.")

class QATestSuite(BaseModel):
    test_code: str = Field(description="Raw Python code only.")

    @field_validator("test_code")
    @classmethod
    def clean_markdown_fences(cls, v: str) -> str:
        """Ensures generated code is cleaned from accidental markdown fences."""
        v = re.sub(r"^```python\s*", "", v, flags=re.IGNORECASE)
        v = re.sub(r"^```\s*", "", v)
        v = re.sub(r"\s*```$", "", v)
        return v.strip()

class ReviewReport(BaseModel):
    code_quality_analysis: str = Field(description="Audit text for production code quality.")
    test_integrity_analysis: str = Field(description="Audit text for test integrity.")
    log_verification_analysis: str = Field(description="Analysis text for test runner and scanner output.")
    code_quality_approved: bool = Field(description="Boolean flag indicating production code approval status.")
    test_integrity_approved: bool = Field(description="Boolean flag indicating test integrity approval status.")
    diagnostic_payload: str = Field(description="Fix instructions returned on rejection.")

class GlobalPipelineContext(BaseModel):
    pr_description: str
    base_branch: str = "main"
    workspace_paths: WorkspacePaths = Field(default_factory=WorkspacePaths)
    contract: ArchitectureContract | None = None
    production_code_snapshot: str = ""
    test_code_snapshot: str = ""
    error_trace: str = ""
    review_report: ReviewReport | None = None
    current_attempt: int = 1

    def needs_test_regeneration(self) -> bool:
        """Whether QA must (re)generate tests before the next cycle.

        Recovers ephemeral regeneration intent from the last persisted review report so a
        rejected-tests checkpoint cannot bypass QA on resume: regenerate when the review
        rejected the test suite, or when no validated test snapshot exists yet.
        """
        if self.review_report and not self.review_report.test_integrity_approved:
            return True
        return not self.test_code_snapshot

    def save_checkpoint(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load_checkpoint(cls, path: Path) -> "GlobalPipelineContext":
        raw = path.read_text(encoding="utf-8")
        return cls.model_validate_json(raw)
