#!/bin/bash
# Annotated Git tags marking each completed SDLC iteration.
# See CHANGELOG.md and docs/adr/ for the full record behind each tag.
set -euo pipefail

git tag -a v0.0.0 -m "Iteration 000: Cloud Infra & FSM Architecture Research"
git tag -a v0.1.0 -m "Iteration 001: Baseline Sequential Loop"
git tag -a v0.2.0 -m "Iteration 002: Async Fork-Join & QA Node Isolation"
git tag -a v0.3.0 -m "Iteration 003: Dual-Channel Observability & Gemini 2.5 Routing"
git tag -a v0.4.0 -m "Iteration 004: Modularization & Sandbox Hardening"
git tag -a v0.5.0 -m "Iteration 005: Git-Driven State Tracking & QA Fan-Out Concurrency"
git tag -a v0.6.0 -m "Iteration 006: FSM State Serialization & Resume Mechanism"

echo "Run 'git push --tags' to push tags to remote."
