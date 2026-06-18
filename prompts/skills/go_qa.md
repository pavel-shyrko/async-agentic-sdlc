---
skill_id: go_qa
type: domain
triggers: [go]
nodes: [qa, reviewer]
---
LANGUAGE TARGET: Go — concrete syntax for the Go tech stack. The language-neutral rules (error
fidelity, import fidelity, whole-file assembly, BVA strategy) live in the QA system prompt; this skill
only maps them to Go idioms.

## File Header (MANDATORY — a missing clause makes the file un-parseable Go)
- The test file's VERY FIRST line MUST be `package <pkg>` (white-box) — the SAME package its
  `colocated production sibling` declares in the PRODUCTION CODE SNAPSHOT — BEFORE any `import`. NEVER
  start the file with `import`. Use an external `_test` package only when the contract exposes a pure
  public API. (e.g. a root `main_test.go` next to `package main`'s `main.go` must be `package main`,
  never `package converter`.)
- `new_imports` MUST therefore begin with the `package <pkg>` line, then the `import (...)` block.
- Shape every Go test file exactly like this:

```
package converter

import (
	"testing"
)

func TestConvert(t *testing.T) { /* table-driven cases */ }
```

## Testing Framework & Layout
- Use ONLY the standard-library `testing` package. STRICTLY BAN testify, ginkgo, gomega, and any
  third-party assertion/BDD framework.
- Colocate the test file NEXT TO its source file as `<name>_test.go` (e.g. `engine.go` →
  `engine_test.go`). NEVER create a separate `tests/` directory.

## Test Shape
- One `func TestXxx(t *testing.T)` per behavior cluster. Drive cases from an explicit table — a slice
  of anonymous structs — iterated with `t.Run(tt.name, func(t *testing.T){ ... })`.
- FLAG PARSING (CRITICAL): NEVER exercise the global `flag.CommandLine` / `flag.Parse` / package-level
  `flag.String` from a test. Registering the same flag twice in one process PANICS with
  `flag redefined: <name>`. Construct a FRESH `flag.NewFlagSet(tt.name, flag.ContinueOnError)` inside
  each case and parse against it. If the production parser only reads global flags it is untestable:
  assert that via the contract's signature (it should accept a `*flag.FlagSet` or an args slice).

## Errors (concrete API for the system-prompt CRITICAL RULE — Go has no exceptions)
- Assert error CONDITIONS only: `if err != nil` for the no-error path, and
  `errors.Is(err, ExpectedSentinel)` / `errors.As` for an expected sentinel/typed error from the
  contract. NEVER assert on `err.Error()` text or any message-derived attribute.

## Imports
- Import the package under test by the exact module path from the topology contract / production
  snapshot (e.g. `<module>/internal/converter`).
