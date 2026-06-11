---
skill_id: deterministic_mutation
type: stateful
nodes: [developer]
---
# Skill: Deterministic Code Mutation and Bug Fixing

## Context
Apply this skill when fixing code after a validation gate failure (Functional QA or SAST) reported by the Reviewer Agent.

## Protocol
1. **Error Analysis**: Read the `diagnostic_payload` from the state context. Extract only the failing line and the exception type. Ignore historical logs.
2. **Target Isolation**: Do not rewrite unchanged functions. Modify only the AST blocks responsible for the specific failure.
3. **Type-Guard Enforcement**: If the failure is due to an implicit type conversion, deploy explicit runtime type guards per the active stack's rules (see the loaded tech-stack skill). Reject ambiguous sub-types that could pass an implicit cast.
4. **Verification**: Run code compilation checks locally before returning control.
5. **Ghost File Garbage Collection**: You are fixing a failed previous attempt. If your new solution changes the architecture or abandons files you created in the previous attempt, YOU MUST explicitly delete the obsolete files from the filesystem using shell commands to prevent dead code from failing static analysis.

## Output Format

Return ONLY the modified diff block or the updated file content. Zero conversational explanations.
