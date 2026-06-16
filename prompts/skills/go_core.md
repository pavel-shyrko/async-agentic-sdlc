---
skill_id: go_core
type: domain
triggers: [go]
nodes: [techlead, developer, reviewer]
---
LANGUAGE TARGET: Go — production-code rules for the Go tech stack.

## Runtime & Sandbox
- Target Go 1.23, executed in the isolated Docker sandbox (`golang:1.23-alpine`).
- The module compiles cleanly under `go build ./...`; an unused import or variable is a COMPILE
  ERROR, not a warning — never leave them in.

## Types & Guards
- Lean on the static type system; validate inputs explicitly at the boundary (e.g. reject an empty or
  multi-character `rune` where a single delimiter is required). No implicit numeric conversions —
  convert explicitly and only when safe.
- Prefer concrete types and small interfaces accepted as parameters (accept interfaces, return
  structs) for testability and dependency injection.

## Error Handling (NOT exceptions)
- Go has no exceptions. RETURN errors as the last value; check `if err != nil` and propagate.
- Define package-level sentinel errors with `errors.New(...)` (e.g. `ErrInvalidFormat`) or wrap with
  `fmt.Errorf("context: %w", err)`; downstream code distinguishes them with `errors.Is`/`errors.As`.
- NEVER `panic` for ordinary invalid input, and NEVER discard an error with `_` unless it is provably
  impossible. Do not build control flow on error message TEXT — only on the sentinel/type.

## Package & Module Glue
- Organize code by directory: every file in a directory declares the SAME `package`. There is NO
  `__init__.py` equivalent — a directory IS the package. Unexported identifiers are lowercase;
  exported ones are Capitalized.
- Manage dependencies in `go.mod` (and keep `go.sum` consistent via `go mod tidy`). Create any glue
  files the build requires (e.g. `main.go` wiring, a package entry) without waiting for the contract.
- `internal/` packages are importable only within the module subtree rooted at their parent.

## Security & Formatting
- `gosec ./...` runs before review — zero tolerance for flagged vulnerabilities.
- All code MUST be `gofmt`-clean (tabs, canonical layout).
