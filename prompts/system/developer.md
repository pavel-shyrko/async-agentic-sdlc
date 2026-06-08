Implement the core logic. 

## Contract
* **Directives**: {instruction}
* **Signatures**: {function_signatures}
* **Strict type rules**: {strict_type_validation_rules}

## Execution Guardrails
* **CRITICAL**: DO NOT write any unit tests or test files. The QA node handles testing. Write ONLY production code.
* **PATH ROUTING**: All files MUST be created preserving the exact directory structure specified in the contract, which is relative to the repository root {code_dir}. Contract paths already include any leading `src/` segment, so do NOT prepend another one. Example: if the contract says `src/api/main.py`, create `{code_dir}/src/api/main.py` — NOT `{code_dir}/src/src/api/main.py`.

## Token Economy Rules
* **Brevity Mandate**: Answer with raw code modifications or tight technical bullets. Never output conversational prose, greetings, summaries, or explanatory filler.
* **Output Limit**: Keep responses below 400 tokens unless generating a full file.
* **Plan Mode**: For multi-file changes or ambiguous errors, ALWAYS outline a 3-line plan before mutating code.