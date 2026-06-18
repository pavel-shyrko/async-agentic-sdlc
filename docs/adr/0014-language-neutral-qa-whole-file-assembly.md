# 0014 — Language-Neutral QA: Whole-File Assembly + Skills-Driven Test Correctness

## Status

Accepted (supersedes [0013](0013-structured-test-maintenance-ast-pruning.md))

## Context

ADR 0013 moved test-file surgery into the engine via a Python-only `ast.parse`/`ast.unparse` merge,
while Go/Node/.NET already used a whole-file path. This left the QA agent (`src/executor/agents/qa.py`)
carrying **per-language imperative hardcode**: the Python AST merge (`_assemble_suite`, `_is_main_guard`),
a Go package-clause guard (`_GO_PACKAGE_RE`, `_ensure_go_package_clause`, `_derive_go_package`), an
`env_language == "go"` branch, a `uses_ast` profile split, and a Python-default zombie predicate.

`run_3dc1e2043ea74ed082f47ec1744e4d8e` (Go `json2csv`) exposed the cost of trying to mechanically
"fix" model output per-language: QA emitted a root `main_test.go` declaring `package converter` next to
`main.go`'s `package main`; the Go guard only repaired a *missing* clause, not a *wrong* one, so the
build failed every cycle (`could not import "main"`) → CIRCUIT BREAKER. Extending the guard to rewrite
a wrong-but-present clause would have deepened the hardcode (and still couldn't fix "tested the wrong
unit"). The directive: remove all per-language code from the QA agent and make the model itself produce
correctly-packaged, well-placed tests, backed by the existing runtime gates.

## Decision

One language-neutral assembly path; correctness pushed to prompts/skills + the compile gate.

- **Unified assembly** — `_assemble_suite` in `qa.py` writes the model's complete file verbatim
  (`new_imports` header + `new_test_code`), with one safety net: an empty delta + existing file +
  no `overwrite_existing` keeps the existing file (an empty response never clobbers a good suite).
  Deleted: the AST merge, `_is_main_guard`, the Go package guard trio, the `env_language == "go"`
  branch, and the `uses_ast`/`fence_lang` profile keys (`environments.py`).
- **Skills carry correctness** — the language-neutral system prompt (`prompts/system/qa.md`) gains
  **TEST-FILE IDENTITY FIDELITY** (a test's package/namespace/module must match its production sibling
  in the snapshot — never a foreign one) and a **Thin / untestable module** rule (don't fabricate a
  foreign-package test for an entrypoint; test the logic where it lives). Per-language skills
  (`go_qa.md`, `python_qa.md`, `dotnet_qa.md`) state the concrete idiom; the `STRUCTURED TEST
  MAINTENANCE` section is replaced by a uniform **TEST FILE ASSEMBLY** contract (return the complete
  file, `overwrite_existing=true`, preserve still-valid cases).
- **Safety net is the runtime, not surgery** — a wrong-package test is caught by the compile gate
  (`run_build_gate` + `build_failure_is_test_only`), classified as test-only, and routed to QA via the
  Reviewer's `qa_diagnostic_payload`. `reviewer.md` gains case **(c) WRONG TEST PACKAGE/NAMESPACE** so
  the failure is sent to QA (not the Developer, who cannot edit tests — which would deadlock).

## Consequences

- **Pros**: the QA agent is fully language-neutral — adding a stack needs only a registry profile + a
  skill, no engine code; one assembly path instead of two; correctness lives where domain knowledge is
  authored (skills) and is verified by the same gates that run real builds; the wrong-package failure
  mode now self-heals through the QA channel instead of looping to the breaker.
- **Cons / constraints**: preservation of a NON-empty existing suite now depends on the model
  re-emitting it (the existing suite is always provided in-context + the prompt mandates preservation),
  rather than the engine guaranteeing it as in 0013 — accepted trade-off for zero hardcode; whole-file
  re-emission costs more output tokens than deltas for large suites; and a model that ignores the
  identity-fidelity rule still produces a broken test, but it now fails fast at the compile gate and is
  corrected on the next QA cycle rather than being silently mis-rewritten.
