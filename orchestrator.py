import os
import sys
import shutil
import subprocess
import asyncio
import instructor
from pydantic import BaseModel, Field
from google import genai

# ==========================================
# ENVIRONMENT CHECKER
# ==========================================
def check_environment():
    print("[SYSTEM] Initializing environment pre-flight check...")
    for tool in ["docker", "claude", "bandit"]:
        if not shutil.which(tool):
            print(f"🚨 CRITICAL RUNTIME ERROR: Execution binary '{tool}' not found in PATH.")
            sys.exit(1)
    if not os.environ.get("GEMINI_API_KEY"):
        print("🚨 CRITICAL RUNTIME ERROR: Environment variable GEMINI_API_KEY is vacant.")
        sys.exit(1)
    print("[SYSTEM] Environment verification completed successfully.\n")

# ==========================================
# CONTRACTS (Artifact Standards)
# ==========================================
class ArchitectureContract(BaseModel):
    files_to_modify: list[str] = Field(description="Target production source files to modify or instantiate (e.g., ['math_lib.py']).")
    instruction: str = Field(description="Strict technical directives for the Developer Agent.")
    function_signatures: str = Field(description="Exact names, arguments, types, and expected exceptions for the QA Agent to target.")

# ==========================================
# ASYNC STREAM CONSUMER UTILITY
# ==========================================
async def stream_subprocess_output(prefix: str, stream: asyncio.StreamReader):
    while True:
        line = await stream.readline()
        if not line:
            break
        print(f"{prefix} {line.decode().rstrip()}")

# ==========================================
# AGENT NODES
# ==========================================

async def run_architect_node(business_requirement: str) -> ArchitectureContract:
    print("========================================================================")
    print(f"[NODE][ARCHITECT] Synthesizing system design from requirement...")
    print("========================================================================")
    
    client = instructor.from_genai(
        client=genai.Client(api_key=os.environ.get("GEMINI_API_KEY")),
        mode=instructor.Mode.GENAI_STRUCTURED_OUTPUTS,
    )
    
    sys_prompt = "You are a Principal Architect. Define strict production file mappings and function signatures."
    
    loop = asyncio.get_running_loop()
    contract = await loop.run_in_executor(
        None, lambda: client.chat.completions.create(
            model="gemini-3.5-flash",
            response_model=ArchitectureContract,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": business_requirement}
            ]
        )
    )
    print(f"[DECISION][ARCHITECT] Contract locked:\n{contract.model_dump_json(indent=2)}\n")
    return contract

async def run_developer_node(contract: ArchitectureContract, error_trace: str = "") -> None:
    print("========================================================================")
    print(f"[NODE][DEVELOPER] Executing source code generation...")
    print("========================================================================")
    
    prompt = f"Implement the core logic. Directives: {contract.instruction}. Signatures: {contract.function_signatures}"
    if error_trace:
        prompt += f"\nFix previous validation failures:\n{error_trace}"

    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"] + contract.files_to_modify
    
    proc = await asyncio.create_subprocess_exec(*cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    await asyncio.gather(
        stream_subprocess_output("  [DEVELOPER][STDOUT]", proc.stdout),
        stream_subprocess_output("  [DEVELOPER][STDERR]", proc.stderr)
    )
    await proc.wait()

async def run_qa_generation_node(contract: ArchitectureContract) -> str:
    """Новый выделенный узел QA-Агента: Физически генерирует файл тестов."""
    print("========================================================================")
    print(f"[NODE][QA-GENERATOR] Writing physical test suite based on contract signatures...")
    print("========================================================================")
    
    test_file_name = "test_math_lib.py"
    
    # Инициируем вызов Gemini для генерации кода тестов на основе контракта
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    prompt = (
        f"You are a QA Engineer Agent. Write a comprehensive, robust Python unittest suite for the following specifications:\n"
        f"{contract.function_signatures}\n"
        f"Target module to import: {contract.files_to_modify[0].replace('.py', '')}\n"
        f"Output ONLY executable raw Python test code. Never wrap it in markdown blocks, codespans, or conversational prose."
    )
    
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None, lambda: client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
        )
    )
    
    test_code = response.text.strip().replace("```python", "").replace("```", "")
    
    with open(test_file_name, "w") as f:
        f.write(test_code)
        
    print(f"[DECISION][QA-GENERATOR] Physical test suite saved to '{test_file_name}'")
    return test_file_name

# ==========================================
# PARALLEL VALIDATION LAYER
# ==========================================

async def run_qa_unit_tests(test_file: str) -> tuple[bool, str]:
    prefix = "  [DOCKER-QA]"
    print(f"{prefix} Initializing ephemeral testing container...")
    
    # Тестовая команда жестко зашита в логику оркестратора — никаких doctest читов
    test_command = f"python3 -m unittest {test_file}"
    
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{os.getcwd()}:/workspace",
        "-w", "/workspace",
        "python:3.11-slim",
        "bash", "-c", test_command
    ]
    
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_buffer, stderr_buffer = [], []
    
    async def collect_and_print(stream: asyncio.StreamReader, buffer: list, log_prefix: str):
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode().rstrip()
            buffer.append(decoded)
            print(f"{log_prefix} {decoded}")

    await asyncio.gather(
        collect_and_print(proc.stdout, stdout_buffer, f"{prefix}[STDOUT]"),
        collect_and_print(proc.stderr, stderr_buffer, f"{prefix}[STDERR]")
    )
    await proc.wait()
    
    success = (proc.returncode == 0)
    report = "\n".join(stdout_buffer + stderr_buffer)
    print(f"{prefix} Functional verification ended. Status: {'PASSED' if success else 'FAILED'} (Code {proc.returncode})")
    return success, report

async def run_security_scan(files: list[str]) -> tuple[bool, str]:
    prefix = "  [SAST-SECURITY]"
    print(f"{prefix} Initiating bandit static analysis scan...")
    
    cmd = [sys.executable, "-m", "bandit", "-q"] + files
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_buffer, stderr_buffer = [], []
    
    async def collect_and_print(stream: asyncio.StreamReader, buffer: list, log_prefix: str):
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode().rstrip()
            buffer.append(decoded)
            print(f"{log_prefix} {decoded}")

    await asyncio.gather(
        collect_and_print(proc.stdout, stdout_buffer, f"{prefix}[STDOUT]"),
        collect_and_print(proc.stderr, stderr_buffer, f"{prefix}[STDERR]")
    )
    await proc.wait()
    
    success = (proc.returncode == 0)
    report = "\n".join(stdout_buffer + stderr_buffer)
    if success and not report.strip():
        report = "Bandit execution passed. Zero vulnerabilities identified."
        print(f"{prefix}[STDOUT] {report}")
    return success, report

# ==========================================
# MAIN ORCHESTRATOR
# ==========================================

async def main():
    check_environment()
    pr_description = "Implement factorial(n) in math_lib.py. Handle negative n with ValueError."
    
    contract = await run_architect_node(pr_description)
    
    # Генерация тестов происходит один раз на этапе планирования (до цикла разработки)
    test_file = await run_qa_generation_node(contract)

    max_retries = 3
    error_trace = ""

    for attempt in range(1, max_retries + 1):
        print("\n" + "="*80)
        print(f" STARTING ORCHESTRATION CYCLE: ITERATION {attempt}/{max_retries}")
        print("="*80)
        
        await run_developer_node(contract, error_trace)
        
        print("\n[ORCHESTRATOR] Triggering parallel validation layer against real test file...")
        results = await asyncio.gather(
            run_qa_unit_tests(test_file),
            run_security_scan(contract.files_to_modify)
        )
        
        qa_success, qa_log = results[0]
        sec_success, sec_log = results[1]
        
        print(f"\n[DECISION] Evaluation Summary -> Functional QA: {'OK' if qa_success else 'FAIL'} | Security SAST: {'OK' if sec_success else 'FAIL'}")
        
        if qa_success and sec_success:
            print("\n========================================================================")
            print(" ✅ PIPELINE SUCCESS: All explicit validation gates passed.")
            print("========================================================================")
            return
        
        failed_traces = []
        if not qa_success:
            failed_traces.append(qa_log)
        if not sec_success:
            failed_traces.append(sec_log)
            
        error_trace = "\n\n--- Component Failure Log ---\n".join(failed_traces)
        print(f"[ORCHESTRATOR] Cycle failed. Routing diagnostics to Developer Agent.")

    print("\n🚨 CIRCUIT BREAKER OPEN: Unstable state execution halted.")
    sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
