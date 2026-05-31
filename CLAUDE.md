# Claude Code Project Governance

## Token Economy Rules
* **Brevity Mandate**: Answer with raw code modifications or tight technical bullets. Never output conversational prose, greetings, summaries, or explanatory filler.
* **Output Limit**: Keep responses below 400 tokens unless generating a full file.
* **Plan Mode**: For multi-file changes or ambiguous errors, ALWAYS outline a 3-line plan before mutating code.

## Development Commands
* **Run Orchestrator**: `python3 orchestrator.py -f <ticket_path>`
* **Run Tests**: `python3 -m unittest discover -s tests`
* **Check Lint/Security**: `bandit -r src/`

## Session Initialization
* **At the start of every session**: read `.ai/memory/MEMORY.md` and load all linked memory files. These contain project-specific feedback and context that override default behavior.

## Project Architecture Guardrails
* Read and follow instructions from `.ai/skills/` when executing metadata synchronization tasks.
* Never modify runtime prompts inside `prompts/system/` unless explicitly ordered by the Human.
