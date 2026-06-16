---
skill_id: go_qa
type: domain
triggers: [go]
nodes: [qa, reviewer]
---
LANGUAGE TARGET: Go — test-suite rules for the Go tech stack.

## Testing Framework & Layout
- Use ONLY the standard-library `testing` package. STRICTLY BAN testify, ginkgo, gomega, and any
  third-party assertion/BDD framework.
- Colocate the test file NEXT TO its source file as `<name>_test.go` (e.g. `engine.go` →
  `engine_test.go`). NEVER create a separate `tests/` directory — `go test ./...` discovers
  `*_test.go` inside each package.
- Declare the SAME package as the file under test (white-box) so unexported and `internal/` symbols
  are reachable. Use an external `_test` package only when the contract exposes a pure public API.

## Test Shape
- One `func TestXxx(t *testing.T)` per behavior cluster. Drive cases from an explicit table — a slice
  of anonymous structs — iterated with `t.Run(tt.name, func(t *testing.T){ ... })` so each case is
  isolated and independently reported. Prefer one table-driven test over many near-duplicate funcs.

## Errors (NOT exceptions)
- Go has no exceptions. Assert error CONDITIONS only: check `if err != nil` for the no-error path, and
  `errors.Is(err, ExpectedSentinel)` for an expected sentinel/typed error declared in the contract.
- NEVER assert on `err.Error()` text, the message string, or any message-derived attribute (per the
  CRITICAL RULE). Verify only the sentinel/type via `errors.Is` / `errors.As`.

## Imports
- Import the package under test by the exact module path from the topology contract / production
  snapshot (e.g. `<module>/internal/converter`). Never guess the module path; never re-declare
  production symbols in the test file.

## Assembly Contract
- Return the COMPLETE test file content in `new_imports` + `new_test_code` and set
  `overwrite_existing` to true. The engine does not AST-merge Go — emit the whole file each time.
