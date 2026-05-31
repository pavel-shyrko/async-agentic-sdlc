# Skill: Deterministic Code Mutation and Bug Fixing

## Context
Apply this skill when fixing code after a validation gate failure (Functional QA or SAST Bandit) reported by the Reviewer Agent.

## Protocol
1. **Error Analysis**: Read the `diagnostic_payload` from the state context. Extract only the failing line and the exception type. Ignore historical logs.
2. **Target Isolation**: Do not rewrite unchanged functions. Modify only the AST blocks responsible for the specific failure.
3. **Type-Guard Enforcement**: If the failure is due to implicit type conversion (e.g., Python treating `bool` as `int`), deploy explicit polymorphic runtime guards:
   ```python
   if not isinstance(param, (int, float)) or isinstance(param, bool):
       raise TypeError(...)
   ```
4. **Verification**: Run code compilation checks locally before returning control.

## Output Format

Return ONLY the modified diff block or the updated file content. Zero conversational explanations.
