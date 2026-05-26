# Antigravity SDLC Project Governance

## Token Economy Rules
* **Brevity Mandate**: Answer with raw code modifications or tight technical bullets. Never output conversational prose, greetings, summaries, or explanatory filler ("Here is the updated code...").
* **Output Limit**: Keep responses below 400 tokens unless generating a full file.
* **Plan Mode**: For multi-file changes or ambiguous errors, ALWAYS outline a 3-line plan before mutating code.

## Tech Stack & Architecture
* **Runtime**: Python 3.11+ / WSL2 / Docker (python:3.11-slim)
* **Testing**: Python `unittest` strictly. No `pytest`.
* **Orchestration**: Custom FSM via Pydantic and `instructor` / Google GenAI SDK.
* **Security**: Bandit SAST scanner.

## Code Style
* Explicit type guards: `isinstance(n, int) and not isinstance(n, bool)` for integer boundaries.
* Zero external dependencies in production modules unless authorized.
* Stream-based non-blocking subprocess handlers.
