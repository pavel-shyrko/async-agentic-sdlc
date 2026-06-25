# 0025 — Tooling Failures Are Environment Misconfigurations, Not Agent Defects

## Status

Accepted (extends [0003](0003-dual-channel-observability.md), [0016](0016-arbiter-contract-self-healing.md),
[0020](0020-deploy-scaffolding-and-lint-gate.md), [0024](0024-routing-coherence-reconciler.md))

## Context

Two `--auto-execute` batches halted on failures that no agent could fix, because the engine misclassified a
**tooling/parsing** fault as an agent-fixable **code** defect. Both are the same root error: a failure the
Developer/QA are structurally incapable of repairing was fed into the agent self-heal loop instead of being
surfaced as an environment incident.

- **Python (`python-3.12-core`) — a malformed `lint_cmd`.** The HARD lint gate ran
  `ruff format --check --extend-exclude=.sdlc_deps .`. `ruff format` does not accept `--extend-exclude`
  (only `ruff check` does), so it exited 2 with `error: unexpected argument '--extend-exclude' found` on
  **every** cycle — a permanently-red gate. Because lint findings are routed to agents and a lint failure
  is excluded from the deadlock guard, the red gate folded into the budgeted cycle. The lint-**blind**
  Reviewer approved both code and tests; the Arbiter, seeing a fully-green review under a failed pipeline,
  returned `root_cause=unrecoverable, route=halt`. 0/3 tickets merged on a one-flag typo.

- **.NET (`dotnet-10-sdk`) — MSBuild diagnostics that the engine could not parse.** `dotnet build` compiles
  the **whole solution including the test project**, violating the build gate's invariant that `build_cmd`
  never touches tests. QA's test-compile errors (CS0182, CS0029) therefore surfaced in the production build
  gate. The backstop `build_failure_is_test_only` should have diverted them to QA — but `_FILE_REF_RE`
  parsed only **colon-style** diagnostics (`path:line:col`), and MSBuild emits **parenthesis-style**
  (`path(line,col):`). With no file references parsed, the classifier returned "not test-only", so the
  test-compile errors were rerouted to the **Developer** (who cannot edit tests). The Developer burned its
  compile-reroute budget and functional cycles on an unfixable error; the genuine production bug (the CLI
  discarded `rootCommand.Invoke(args)`'s exit code) was starved of budget and the run hit "Retries
  exhausted". The same regex gap also silently broke `classify_lint_findings` for .NET.

The pre-existing `build_failure_is_environmental` already embodies the correct principle for one such class
(an unreachable package feed → fail fast with an environment incident, never reroute the Developer). These
two faults are the same shape in two other places.

## Decision

Treat a **tooling-invocation failure** and a **diagnostic-parse gap** as engine/environment concerns, fixed
at their shared, language-agnostic seams — never by patching one stack or rerouting an agent.

- **Format-agnostic diagnostic parsing.** `_FILE_REF_RE` (`src/development/gates.py`) now accepts both the
  colon suffix (`file.ext:line[:col]`) and the MSBuild parenthesis suffix (`file.ext(line,col):`). The
  source-extension alternation stays registry-derived (`all_source_extensions`), so the parser remains
  language-agnostic — a stack whose compiler uses the parenthesis form (.NET, `tsc --pretty false`) is now
  classified by the same regex with no per-language branch. This repairs `build_failure_is_test_only` (QA
  test-compile errors route to QA, not the Developer) and `classify_lint_findings` (prod/test lint split)
  for every MSBuild-format stack at once.

- **Lint tooling errors are environment failures.** A new `lint_failure_is_tooling` (`gates.py`) detects a
  CLI-invocation signature (`unexpected argument`, `unrecognized option`, `unknown flag`, `usage:`,
  `command not found`, …) in the lint output — strong, word-boundary markers so a real finding
  (`file:line: RULE message`) is never misread. When the step-3.6 lint gate fails with that signature, the
  runner calls `_abort_with_incident` with an `ENVIRONMENT/LINT-TOOLING HALT` header instead of folding the
  failure into the budgeted cycle. This mirrors `build_failure_is_environmental`: a tooling failure the
  agents cannot repair fails fast with a precise, fix-the-engine incident. It is the **one** narrow
  exception to "a lint failure is always agent-fixable" (ADR 0020); a genuine lint nit still rides the
  budgeted cycle.

- **Registry correctness.** The `python-3.12-core` `lint_cmd`/`format_cmd` now pass `--exclude` (which
  `ruff format` supports) instead of `--extend-exclude` (which only `ruff check` supports). Per the
  engine-language-agnostic rule, stack-specific commands live in `SUPPORTED_ENVIRONMENTS`; this is a
  correction to that registry entry, not engine logic.

## Consequences

- A malformed `lint_cmd` in any stack now halts with an actionable environment incident (the raw tool error
  is captured in `error_trace`) instead of a misleading Arbiter `unrecoverable` verdict — and no
  Developer/QA budget is spent on it.
- .NET (and any MSBuild-format stack) test-compile failures route to QA; the Developer is no longer starved
  of cycles by errors it cannot fix.
- The classification seams (`_FILE_REF_RE`, `lint_failure_is_tooling`) are conservative by construction, so
  a genuine code defect or style finding is never reclassified as an environment fault.
- A residual remains out of scope: even with cycles reclaimed, an agent may still fail to land a correct
  fix within budget (the .NET exit-code bug). That is the ordinary retry-budget contract, not a
  misclassification, and is unchanged here.

## Notes

Diagnostic seams: `_FILE_REF_RE` / `build_failure_is_test_only` / `lint_failure_is_tooling` /
`classify_lint_findings` in `src/development/gates.py`; the step-3.6 lint loop and the environment-incident
fast-fail in `src/nexus/runner.py`; the `lint_cmd`/`format_cmd` registry entries in
`src/shared/core/environments.py`. Related rules: `engine-language-agnostic`,
`deploy-scaffolding-and-ci-parity`, `pipeline-fsm-loops`, `debugging-protocol`.
