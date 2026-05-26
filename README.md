# Async Agentic SDLC

A proof-of-concept agentic pipeline that automates a software development cycle using LLM agents.

## How it works

`orchestrator.py` runs three agents in sequence:

1. **Architect** (Gemini) — takes a business requirement and produces a structured contract: files to create, implementation directives, and function signatures.
2. **Developer** (Claude CLI) — generates source code based on the contract. Re-runs on failure with the error trace.
3. **QA + Security** (parallel) — validates the output:
   - Unit tests run in an ephemeral `python:3.11-slim` Docker container
   - Static analysis via `bandit`

The cycle retries up to 3 times. If all gates pass, the pipeline exits successfully; otherwise the circuit breaker halts execution.

## Stack

- Python 3.11, asyncio
- [Gemini API](https://ai.google.dev/) via `google-genai` + `instructor`
- Claude CLI (`claude`)
- Docker (sandboxed test execution)
- `bandit` (SAST)

## Setup

See [docs/setup.md](docs/setup.md).

## Practicum

Development history, iteration logs, and engineering takeaways: [PRACTICUM.md](PRACTICUM.md).
