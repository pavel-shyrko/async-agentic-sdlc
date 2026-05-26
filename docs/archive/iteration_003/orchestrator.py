import os
import re
import sys
import shutil
import subprocess
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import instructor
from pydantic import BaseModel, Field, field_validator
from google import genai
from google.genai.errors import APIError, ClientError

# ==========================================
# OBSERVABILITY & AUDIT LOGGING
# ==========================================
def setup_observability():
    """Configures dual-channel logging: clean CLI output and verbose file tracing."""
    logger = logging.getLogger("SDLC")
    logger.setLevel(logging.DEBUG)
    
    # Avoid duplicate handlers on re-runs
    if not logger.handlers:
        # CLI Handler (INFO)
        c_handler = logging.StreamHandler(sys.stdout)
        c_handler.setLevel(logging.INFO)
        c_handler.setFormatter(logging.Formatter('%(message)s'))
        
        # Persistent Audit Trail (DEBUG)
        f_handler = RotatingFileHandler("sdlc_audit.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
        f_handler.setLevel(logging.DEBUG)
        f_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] [%(funcName)s] %(message)s'))
        
        logger.addHandler(c_handler)
        logger.addHandler(f_handler)
    
    return logger

log = setup_observability()

# ==========================================
# ENVIRONMENT CHECKER
# ==========================================
def check_environment():
    log.info("🔍 Pre-flight environment check...")
    for tool in ["docker", "claude", "bandit"]:
        if not shutil.which(tool):
            log.error(f"🚨 CRITICAL: Binary '{tool}' not found in PATH.")
            sys.exit(1)
            
    if not os.environ.get("GEMINI_API_KEY"):
        log.error("🚨 CRITICAL: GEMINI_API_KEY is not set.")
        sys.exit(1)
        
    log.info("  ✓ Environment verified.\n")

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
    contract: ArchitectureContract | None = None
    test_file_name: str = ""
    production_code_snapshot: str = ""
    test_code_snapshot: str = ""
    error_trace: str = ""
    review_report: ReviewReport | None = None

# ==========================================
# ASYNC STREAM CONSUMER UTILITY
# ==========================================
async def stream_subprocess_output(prefix: str, stream: asyncio.StreamReader, buffer: list):
    while True:
        line = await stream.readline()
        if not line:
            break
        decoded = line.decode().rstrip()
        buffer.append(decoded)
        
        # Stream Claude CLI output to console for real-time visibility, log everything else to file
        if "claude" in prefix:
            log.info(f"{prefix} {decoded}")
        else:
            log.debug(f"{prefix} {decoded}")

# ==========================================
# DYNAMIC GENAI CLIENT INITIALIZER
# ==========================================
def get_genai_client() -> genai.Client:
    """Initializes the standard Google AI Studio client."""
    log.debug("Initializing Google AI Studio client via GEMINI_API_KEY")
    return genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ==========================================
# HELPER FOR GRACEFUL QUOTA ERROR HANDLING
# ==========================================
def handle_quota_error(e: ClientError):
    log.error("\n🚨 RATE LIMIT EXHAUSTED (429) DETECTED!")
    log.error("   Your project is currently hitting the Google AI Studio quota limit.")
    log.error("   Ensure your AI Studio project is on a Pay-as-you-go plan.")
    log.error("\n   Details:")
    log.error(f"   {e}")

# ==========================================
# TOKEN OBSERVABILITY HELPER
# ==========================================
def log_token_usage(agent_name: str, raw_response: any):
    """Extracts and logs token usage from Gemini API raw responses."""
    try:
        if hasattr(raw_response, 'usage_metadata') and raw_response.usage_metadata:
            usage = raw_response.usage_metadata
            in_tokens = getattr(usage, 'prompt_token_count', 0)
            out_tokens = getattr(usage, 'candidates_token_count', 0)
            total = getattr(usage, 'total_token_count', in_tokens + out_tokens)
            log.info(f"   [TOKENS] {agent_name} | Input: {in_tokens} | Output: {out_tokens} | Total: {total}")
    except Exception as e:
        log.debug(f"Failed to parse token usage for {agent_name}: {e}")

# ==========================================
# AGENT NODES
# ==========================================
async def run_architect_node(ctx: GlobalPipelineContext) -> None:
    model_name = "gemini-2.5-flash"
    log.info(f"🔷 [ROLE] Architect Agent | [MODEL] {model_name}")
    
    client = instructor.from_genai(
        client=get_genai_client(),
        mode=instructor.Mode.GENAI_STRUCTURED_OUTPUTS,
    )

    sys_prompt = "You are a Principal Architect. Define strict production file mappings, type guards, and function signatures. Be concise. No prose."
    
    max_api_retries = 3
    for api_attempt in range(1, max_api_retries + 1):
        try:
            loop = asyncio.get_running_loop()
            contract, raw_response = await loop.run_in_executor(
                None, lambda: client.chat.completions.create_with_completion(
                    model=model_name,
                    response_model=ArchitectureContract,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": ctx.pr_description}
                    ]
                )
            )
            ctx.contract = contract
            log_token_usage("Architect", raw_response)
            
            log.info(f"   [THOUGHT] {ctx.contract.architecture_reasoning}")
            log.info(f"   [ARTIFACT] Contract locked for: {ctx.contract.files_to_modify}\n")
            log.debug(f"Architect Node Output: {ctx.contract.model_dump_json(indent=2)}")
            return
        except ClientError as e:
            if e.status_code == 429:
                handle_quota_error(e)
                sys.exit(1)
            if api_attempt == max_api_retries:
                log.error(f"🚨 CRITICAL: Architect Agent API call failed after {max_api_retries} attempts.")
                raise e
            log.warning(f"Architect Agent attempt {api_attempt} failed, retrying...")
            await asyncio.sleep(2 ** api_attempt)
        except Exception as e:
            if api_attempt == max_api_retries:
                log.error(f"🚨 CRITICAL: Architect Agent API call failed after {max_api_retries} attempts.")
                raise e
            log.warning(f"Architect Agent attempt {api_attempt} failed, retrying...")
            await asyncio.sleep(2 ** api_attempt)

async def run_qa_agent_node(ctx: GlobalPipelineContext, error_trace: str = "") -> None:
    model_name = "gemini-2.5-flash"
    log.info(f"🔶 [ROLE] QA Agent | [MODEL] {model_name}")

    if not ctx.contract or not ctx.contract.files_to_modify:
        log.error("🚨 CRITICAL: Cannot generate tests without a locked Architecture Contract.")
        sys.exit(1)

    # Dynamically derive the test file name based on production code
    prod_file = ctx.contract.files_to_modify[0]
    module_name = prod_file.replace(".py", "")
    ctx.test_file_name = f"test_{prod_file}"

    client = instructor.from_genai(
        client=get_genai_client(),
        mode=instructor.Mode.GENAI_STRUCTURED_OUTPUTS,
    )

    prompt = (
        f"You are a QA Agent. Write a comprehensive, robust Python unittest suite for: {ctx.contract.function_signatures}\n"
        f"Target module to import: {module_name}\n"
        f"Strict validation rules to enforce: {ctx.contract.strict_type_validation_rules}\n"
        f"CRITICAL RULE: The generated test suite must be completely deterministic. You are STRICTLY FORBIDDEN from wrapping boundary tests or type validation checks in try-except blocks, pass statements, or conditional if-else assertions. If a type or value is invalid according to the contract, use self.assertRaises() exclusively."
    )
    if error_trace:
        prompt += f"\n\nPrevious failure feedback to address:\n{error_trace}"

    max_api_retries = 3
    for api_attempt in range(1, max_api_retries + 1):
        try:
            loop = asyncio.get_running_loop()
            suite, raw_response = await loop.run_in_executor(
                None, lambda: client.chat.completions.create_with_completion(
                    model=model_name,
                    response_model=QATestSuite,
                    messages=[
                        {"role": "system", "content": "You are an automated QA engineer producing pure Python unittest files. No markdown, no commentary."},
                        {"role": "user", "content": prompt}
                    ]
                )
            )
            
            ctx.test_code_snapshot = suite.test_code
            log_token_usage("QA Agent", raw_response)

            with open(ctx.test_file_name, "w") as f:
                f.write(ctx.test_code_snapshot)

            log.info("   [THOUGHT] Generated deterministic unittest suite targeting strict type enforcement and contract safety.")
            log.info(f"   [ARTIFACT] Instantiated test suite at '{ctx.test_file_name}'\n")
            log.debug(f"QA Agent Output written to {ctx.test_file_name}")
            return
        except ClientError as e:
            if e.status_code == 429:
                handle_quota_error(e)
                sys.exit(1)
            if api_attempt == max_api_retries:
                log.error(f"🚨 CRITICAL: QA Agent API call failed after {max_api_retries} attempts.")
                raise e
            log.warning(f"QA Agent attempt {api_attempt} failed, retrying...")
            await asyncio.sleep(2 ** api_attempt)
        except Exception as e:
            if api_attempt == max_api_retries:
                log.error(f"🚨 CRITICAL: QA Agent API call failed after {max_api_retries} attempts.")
                raise e
            log.warning(f"QA Agent attempt {api_attempt} failed, retrying...")
            await asyncio.sleep(2 ** api_attempt)

async def run_developer_node(ctx: GlobalPipelineContext, error_trace: str = "") -> None:
    model_name = "claude-4.6-sonnet (via Claude CLI)"
    log.info(f"🟩 [ROLE] Developer Agent | [MODEL] {model_name}")

    prompt = (
        f"Implement the core logic. Directives: {ctx.contract.instruction}. "
        f"Signatures: {ctx.contract.function_signatures}. "
        f"Strict type rules: {ctx.contract.strict_type_validation_rules}"
    )
    if error_trace:
        prompt += f"\n\nValidation Failure Context:\n{error_trace}"

    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"] + ctx.contract.files_to_modify

    log.debug(f"Executing Developer Subprocess: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(*cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_buffer, stderr_buffer = [], []
    
    await asyncio.gather(
        stream_subprocess_output("   [Developer Agent][STDOUT]", proc.stdout, stdout_buffer),
        stream_subprocess_output("   [Developer Agent][STDERR]", proc.stderr, stderr_buffer)
    )
    await proc.wait()
    
    log.info(f"   [TOKENS] Developer Agent | Tracked out-of-band via ccusage")

    # Save a snapshot of the fresh code into state
    prod_file = ctx.contract.files_to_modify[0]
    if os.path.exists(prod_file):
        with open(prod_file, "r") as f:
            ctx.production_code_snapshot = f.read()

    log.info(f"   [MUTATION] Modified: {ctx.contract.files_to_modify} (Exit Code: {proc.returncode})\n")
    log.debug(f"Developer code snapshot:\n{ctx.production_code_snapshot}")

async def run_reviewer_node(ctx: GlobalPipelineContext, qa_success: bool, qa_log: list[str], sec_success: bool, sec_log: list[str]) -> None:
    model_name = "gemini-2.5-pro"
    log.info(f"🔍 [ROLE] Reviewer Agent | [MODEL] {model_name}")

    client = instructor.from_genai(
        client=get_genai_client(),
        mode=instructor.Mode.GENAI_STRUCTURED_OUTPUTS,
    )

    qa_report = "\n".join(qa_log) if qa_log else "No logs produced."
    sec_report = "\n".join(sec_log) if sec_log else "No logs produced."

    user_content = (
        f"=== ORIGINAL USER REQUIREMENT ===\n{ctx.pr_description}\n\n"
        f"=== ARCHITECT CONTRACT ===\n{ctx.contract.model_dump_json(indent=2)}\n\n"
        f"=== GENERATED PRODUCTION CODE ===\n{ctx.production_code_snapshot}\n\n"
        f"=== GENERATED TEST SUITE ===\n{ctx.test_code_snapshot}\n\n"
        f"=== FUNCTIONAL TESTS RUN ({'PASSED' if qa_success else 'FAILED'}) ===\n{qa_report}\n\n"
        f"=== SAST SECURITY SCAN ({'PASSED' if sec_success else 'FAILED'}) ===\n{sec_report}"
    )

    sys_prompt = (
        "You are an elite, brutal Code Reviewer and QA Auditor. Your goal is to enforce extreme standards of code quality, "
        "type guard strictness, and test integrity. Analyze production code against the requirements, test suite against "
        "the contract (strictly reject any try-except blocks, pass, or softness), and interpret the raw runner outputs."
    )

    max_api_retries = 3
    for api_attempt in range(1, max_api_retries + 1):
        try:
            loop = asyncio.get_running_loop()
            report, raw_response = await loop.run_in_executor(
                None, lambda: client.chat.completions.create_with_completion(
                    model=model_name,
                    response_model=ReviewReport,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_content}
                    ]
                )
            )
            ctx.review_report = report
            log_token_usage("Reviewer Agent", raw_response)
            
            log.info(f"   [THOUGHT] Multi-angle review processed:")
            log.info(f"     ├─ [CODE AUDIT] {ctx.review_report.code_quality_analysis}")
            log.info(f"     ├─ [TEST AUDIT] {ctx.review_report.test_integrity_analysis}")
            log.info(f"     └─ [LOG INTERPRETATION] {ctx.review_report.log_verification_analysis}")
            log.info(f"   ├── [GATE][FUNCTIONAL-TESTS] {'PASSED' if qa_success else 'FAILED'}")
            log.info(f"   ├── [GATE][SAST-SECURITY] {'PASSED' if sec_success else 'FAILED'}")
            log.info(f"   └── [AUDIT] Code Approved: {ctx.review_report.code_quality_approved} | Tests Approved: {ctx.review_report.test_integrity_approved}\n")
            
            log.debug(f"Reviewer Node Output: {ctx.review_report.model_dump_json(indent=2)}")
            return
        except ClientError as e:
            if e.status_code == 429:
                handle_quota_error(e)
                sys.exit(1)
            if api_attempt == max_api_retries:
                log.error(f"🚨 CRITICAL: Reviewer Agent API call failed after {max_api_retries} attempts.")
                raise e
            log.warning(f"Reviewer Agent attempt {api_attempt} failed, retrying...")
            await asyncio.sleep(2 ** api_attempt)
        except Exception as e:
            if api_attempt == max_api_retries:
                log.error(f"🚨 CRITICAL: Reviewer Agent API call failed after {max_api_retries} attempts.")
                raise e
            log.warning(f"Reviewer Agent attempt {api_attempt} failed, retrying...")
            await asyncio.sleep(2 ** api_attempt)

# ==========================================
# PARALLEL RUNTIME GATES (Subprocess execution)
# ==========================================
async def run_qa_unit_tests(test_file: str) -> tuple[bool, list[str]]:
    test_command = f"python3 -m unittest {test_file}"
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{os.getcwd()}:/workspace",
        "-w", "/workspace",
        "python:3.11-slim",
        "bash", "-c", test_command
    ]

    log.debug(f"Executing QA runtime gate: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_buffer, stderr_buffer = [], []

    await asyncio.gather(
        stream_subprocess_output("docker-qa-stdout", proc.stdout, stdout_buffer),
        stream_subprocess_output("docker-qa-stderr", proc.stderr, stderr_buffer)
    )
    await proc.wait()

    # Combine stdout and stderr outputs
    total_log = stdout_buffer + stderr_buffer
    log.debug(f"QA Runtime Gate completed with exit code: {proc.returncode}")
    return (proc.returncode == 0), total_log

async def run_security_scan(files: list[str]) -> tuple[bool, list[str]]:
    # Guard block to prevent Bandit from hanging or crashing
    if not files or not all(isinstance(f, str) and f.strip() for f in files):
        log.warning("SAST Error: No target execution files specified in contract.")
        return False, ["SAST Error: No target execution files specified in contract."]

    cmd = [sys.executable, "-m", "bandit", "-q"] + files
    log.debug(f"Executing SAST security gate: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_buffer, stderr_buffer = [], []

    await asyncio.gather(
        stream_subprocess_output("bandit-stdout", proc.stdout, stdout_buffer),
        stream_subprocess_output("bandit-stderr", proc.stderr, stderr_buffer)
    )
    await proc.wait()

    total_log = stdout_buffer + stderr_buffer
    if proc.returncode == 0 and not "".join(total_log).strip():
        total_log = ["Bandit execution passed. Zero vulnerabilities identified."]

    log.debug(f"SAST Security Gate completed with exit code: {proc.returncode}")
    return (proc.returncode == 0), total_log

# ==========================================
# MAIN ORCHESTRATOR
# ==========================================
async def main():
    check_environment()
    pr_description = "Implement factorial(n) in math_lib.py. Handle negative n with ValueError."

    # Initialize unified context state
    ctx = GlobalPipelineContext(pr_description=pr_description)
    log.debug(f"Initialized global context with PR: {pr_description}")

    # 1. Architecture Phase (executed once per session)
    await run_architect_node(ctx)

    max_retries = 3
    regenerate_tests = True  # Raise the test regeneration flag for initial QA Agent run

    for attempt in range(1, max_retries + 1):
        log.info(f"🔷 Orchestration cycle {attempt}/{max_retries}")
        log.debug(f"Starting orchestration cycle {attempt}")

        # Reset accumulated errors before starting a new cycle. Developer/QA will see only clean feedback.
        current_error_trace = ctx.error_trace
        ctx.error_trace = ""

        # 2. Testing Phase (Runs initially or if the Reviewer rejects the tests)
        if regenerate_tests:
            await run_qa_agent_node(ctx, current_error_trace)
            regenerate_tests = False  # Reset the flag until the next rejection

        # 3. Development Phase (Developer fixes production code)
        await run_developer_node(ctx, current_error_trace)

        # 4. Automated Validation Phase (Runtime gates)
        log.debug("Triggering parallel validation gates (QA & Security)")
        qa_result, sec_result = await asyncio.gather(
            run_qa_unit_tests(ctx.test_file_name),
            run_security_scan(ctx.contract.files_to_modify),
        )
        qa_success, qa_lines = qa_result
        sec_success, sec_lines = sec_result

        # 5. Comprehensive Audit Phase (Reviewer Agent)
        await run_reviewer_node(ctx, qa_success, qa_lines, sec_success, sec_lines)

        # Print execution logs of utilities ONLY in case of an actual failure to CLI, but log everything to file
        if not qa_success:
            log.info("  [GATE][FUNCTIONAL-TESTS] Failure raw output:")
            for line in qa_lines:
                log.info(f"    {line}")
        if not sec_success:
            log.info("  [GATE][SAST-SECURITY] Failure raw output:")
            for line in sec_lines:
                log.info(f"    {line}")

        all_gates_passed = (
            qa_success
            and sec_success
            and ctx.review_report.code_quality_approved
            and ctx.review_report.test_integrity_approved
        )

        # Log Approval Checkpoint Status
        log.debug(f"Approval Checkpoint Status: QA={qa_success}, SAST={sec_success}, Code_Approve={ctx.review_report.code_quality_approved}, Test_Approve={ctx.review_report.test_integrity_approved}")

        if all_gates_passed:
            log.info("🟩 PIPELINE SUCCESS: All validation gates passed.")
            return

        # If the Reviewer rejected the tests specifically, raise the test regeneration flag
        if not ctx.review_report.test_integrity_approved:
            log.warning("🔶 Reviewer Agent flagged test suite anomalies. Scheduling test regeneration.")
            regenerate_tests = True

        ctx.error_trace = ctx.review_report.diagnostic_payload
        log.warning(f"🔶 Cycle {attempt} failed. Routing reviewer diagnostic to target agent.")

    # Escalation on Circuit Breaker open
    log.error("\n🚨 CIRCUIT BREAKER OPEN: Retries exhausted.")
    
    incident_file = "incident_report.json"
    with open(incident_file, "w") as f:
        f.write(ctx.model_dump_json(indent=2))
    log.error(f"  └── Incident report written to {incident_file}")
    
    # Final dump to audit log before exit
    log.debug(f"Final Incident Context Dump: {ctx.model_dump_json(indent=2)}")
    sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())