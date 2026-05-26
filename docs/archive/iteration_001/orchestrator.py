import os
import subprocess
import instructor
from pydantic import BaseModel, Field
from google import genai

# ==========================================
# CONTRACTS (Artifact Standards)
# ==========================================
class TaskDefinition(BaseModel):
    files_to_modify: list[str] = Field(
        description="List of files to create or modify (e.g. ['math_lib.py']). Do not include test files — protection against Agentic Escape."
    )
    instruction: str = Field(
        description="Detailed technical instruction for the developer."
    )
    test_command: str = Field(
        description="Bash command to run QA in a python:3.11-slim container (e.g. pip install pytest -q && pytest test_math_lib.py)."
    )

# ==========================================
# AGENT NODES
# ==========================================

def run_architect_node(business_requirement: str) -> TaskDefinition:
    """Architect node: translates business requirements into a strict JSON contract."""
    print("\n[Architect Node] Generating contract (Gemini 2.5 Flash)...")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("🚨 Error: GEMINI_API_KEY environment variable is not set")
        exit(1)

    # Initialize Gemini client with instructor wrapper
    client = instructor.from_genai(
        client=genai.Client(api_key=api_key),
        mode=instructor.Mode.GENAI_STRUCTURED_OUTPUTS,
    )

    sys_prompt = (
        "You are a System Architect. Decompose the business requirement into a strict JSON contract. "
        "Test execution environment: empty python:3.11-slim image. "
        "CRITICAL RULE: The Developer writes ONLY the production code. "
        "NEVER instruct the Developer to write, modify, or create tests. "
        "Tests already exist in the QA environment."
    )

    task_spec = client.chat.completions.create(
        model="gemini-2.5-flash",
        response_model=TaskDefinition,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": business_requirement}
        ]
    )

    print(f"[Architect Node] Success. Contract generated:\n{task_spec.model_dump_json(indent=2)}")
    return task_spec


def run_developer_node(task: TaskDefinition, error_trace: str = "") -> None:
    """Developer node: invokes Claude Code via bash with strict context isolation."""
    print("\n[Developer Node] Generating code (Claude)...")

    prompt = f"Execute the task: {task.instruction}."
    if error_trace:
        prompt += f"\nPrevious test run failed. Fix the CODE but do NOT modify the tests:\n{error_trace}"

    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"] + task.files_to_modify
    try:
        subprocess.run(
            cmd,
            check=True,
            text=True,
            stdin=subprocess.DEVNULL  # CRITICAL: disable interactivity
        )
    except subprocess.CalledProcessError as e:
        print(f"[Developer Node] Error (Exit code {e.returncode})")


def run_qa_node(task: TaskDefinition) -> tuple[bool, str]:
    """QA node: runs tests inside an ephemeral Docker container."""
    print("\n[QA Node] Running tests in Docker...")
    current_dir = os.getcwd()

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{current_dir}:/workspace",
        "-w", "/workspace",
        "python:3.11-slim",
        "bash", "-c", task.test_command
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print("[QA Node] ✅ Tests passed!")
        return True, ""
    else:
        print(f"[QA Node] ❌ Tests failed (Exit code {result.returncode})")
        return False, result.stderr or result.stdout

# ==========================================
# ORCHESTRATOR (DAG State Machine)
# ==========================================

def main():
    # Hardcoded Product node input (for testing)
    pr_description = "Implement a factorial function factorial(n) in math_lib.py. Raise ValueError for negative input. Tests are located in test_math_lib.py."
    print(f"[Product Node] Request initiated: {pr_description}")

    # 1. Build architectural contract (LLM API)
    task = run_architect_node(pr_description)

    # 2. Initialize state machine parameters
    max_retries = 3
    attempt = 0
    error_trace = ""

    # 3. Developer <-> QA loop
    while attempt < max_retries:
        attempt += 1
        print(f"\n--- Iteration {attempt}/{max_retries} ---")

        run_developer_node(task, error_trace)
        success, stderr = run_qa_node(task)

        if success:
            print(f"\n🚀 End-to-end pipeline completed successfully on iteration {attempt}.")
            exit(0)
        else:
            error_trace = stderr

    print("\n🚨 Circuit Breaker Open: Retry limit exceeded. Human intervention required.")
    exit(1)

if __name__ == "__main__":
    main()
