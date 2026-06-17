# Backlog

Open, deferred fixes surfaced across pipeline runs. Resolved items have been removed — their fixes
live in the code, tests, and `CHANGELOG.md`; only outstanding work remains. Original item numbers are
preserved so existing cross-references stay valid.

## 4. Restrict egress during the dependency-restore phase
**Why:** the dependency-restore phase (`setup_cmd`) runs with `--network bridge`. Package managers
execute install hooks (e.g. npm `postinstall`) → an exfiltration surface for LLM-authored code. Test
execution and SAST both stay `--network none` (SAST runs fully offline — its rules are vendored into
the image), so only restore keeps a network window.
**Fix direction:** route restore through an egress-restricted proxy (allowlist package registries),
or vendor dependencies offline, so no phase has unrestricted network.

## 10. [P0] Zombie disposal is a no-op — QA regenerates the file it was told to delete
**Symptom:** log shows `🗑️ Zombie test disposed: main_test.go` then, same cycle,
`QA generated test files: [...main_test.go...]` — the Reviewer's `zombie_tests_to_delete` verdict can
never stick, so the breaker is inevitable.
**Cause:** in `run_qa_agent_node` ([qa.py:124](src/executor/agents/qa.py#L124)) disposal runs BEFORE
the generation loop, and the disposed module is still in `target_modules` (derived from
`files_to_modify` via `derive_test_target`), so QA recreates the identical test every cycle.
**Fix direction:** feed `zombie_tests_to_delete` into generation as a hard exclusion — drop any module
whose derived test path is a flagged zombie from `target_modules` (and skip writing it), so a
condemned test file is not resurrected. Disposal must persist across regeneration.

## 11. [P1] Reviewer hallucinates production defects not present in the gate output
**Symptom:** cycle 1 `code_quality_approved=false` + `dev_diagnostic_payload` "rename go.mod module
from `main`, fix circular imports" — none of which exist (`go.mod` is `github.com/godeltech/jsonconv`,
imports are correct). Burned a Developer reroute on a phantom; the real fault was entirely in the test
file.
**Fix direction:** constrain the Reviewer prompt so `code_quality_approved=false` / `dev_diagnostic_payload`
must cite a verbatim line from the actual gate output (build/test/SAST), not inferred structure; when
the only failing file refs are test files, the production verdict must default to approved.

## 13. [P1] Doc guardrail flags valid manifests/config as "undocumented" — must exempt non-source files
**Symptom:** `[GUARDRAIL] 1 undocumented new file(s): ['requirements.txt']` → fast-fail reroute to the
Developer, even though `requirements.txt` is a legitimate, correctly-formed Python dependency manifest.
**Cause:** `enforce_documentation_guardrail` ([runner.py:459](src/executor/runner.py#L459)) flags ANY
uncontracted, newly-added file whose top `GUARDRAIL_TOP_LINES` carry no comment lead-in. Manifests /
lockfiles / config (`requirements.txt`, `go.mod`/`go.sum`, `package.json`, `*.csproj`, `tsconfig.json`)
and doc artifacts often can't or shouldn't carry an architectural-justification comment — the guardrail
is meant to catch hallucinated/orphan CODE files, not infra.
**Fix direction (generic, all envs):** restrict guardrail candidates to actual stack SOURCE files via the
registry SSOT `is_testable_source(env_id, rel)` (True only for real source; already filters
docs/config/markers/lockfiles). Non-source files are never required to carry a justification comment.
Preserves the guardrail's intent for genuinely uncontracted source the Developer adds without a comment.
