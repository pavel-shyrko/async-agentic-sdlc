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
    files_to_modify: list[str] = Field(description="Target production source files to modify or instantiate.")
    instruction: str = Field(description="Strict technical directives for the Developer Agent.")
    function_signatures: str = Field(description="Exact names, arguments, types, and expected exceptions.")
    strict_type_validation_rules: str = Field(description="Explicit rules regarding language-specific sub-types, like whether bool inputs must raise TypeError or be treated as integers.")
    architecture_reasoning: str = Field(description="Detailed step-by-step engineering justification for the chosen design constraints and type guards.")

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
    code_quality_analysis: str = Field(description="Detailed audit of production code for readability, cleanliness, and algorithmic correctness.")
    test_integrity_analysis: str = Field(description="Strict test validation for determinism, contract coverage, and absence of Test Softening (try-except bypasses).")
    log_verification_analysis: str = Field(description="Analysis and interpretation of Docker test results and Bandit scanner output.")
    code_quality_approved: bool = Field(description="Set to True only if production code is fully ready for release.")
    test_integrity_approved: bool = Field(description="Set to True only if tests are written without loopholes or softening.")
    diagnostic_payload: str = Field(description="Detailed fix instructions for the Developer or QA Agent in case of rejection.")

class GlobalPipelineContext(BaseModel):
    pr_description: str
    base_branch: str = "main"
    workspace_paths: WorkspacePaths = Field(default_factory=WorkspacePaths)
    contract: ArchitectureContract | None = None
    production_code_snapshot: str = ""
    test_code_snapshot: str = ""
    error_trace: str = ""
    review_report: ReviewReport | None = None
