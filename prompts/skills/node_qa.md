---
skill_id: node_qa
type: domain
triggers: [node, typescript, javascript]
nodes: [qa, reviewer]
---
LANGUAGE TARGET: Node.js (TypeScript/JavaScript) — test-suite rules for the Node tech stack.

## Testing Framework & Layout
- Use the ecosystem-standard runner the project is configured for (jest or vitest); both expose
  `describe`/`it`/`expect`. Do NOT introduce a second test runner. Match the source language: write
  `.test.ts` for TypeScript source, `.test.js` for JavaScript source.
- Colocate the test file NEXT TO its source file as `<name>.test.<ext>` (e.g. `app.ts` →
  `app.test.ts`). NEVER create a separate `tests/` directory. The contract MUST provide a `test`
  script in `package.json` and the runner devDependency — assume that scaffolding exists.

## Test Shape
- Group behaviors under `describe(...)`; one `it(...)` per case. Drive variants from an explicit
  array of `{name, input, expected}` iterated with `it.each(table)(...)` (jest) or a `for...of`
  loop calling `it(...)` (vitest) so each case is isolated and independently reported.

## Assertions & Errors
- Assert thrown errors with `expect(() => fn()).toThrow(ErrorType)` — pass the error CLASS/type only.
- NEVER assert the error message string, `.message`, or any message-derived value (per the CRITICAL
  RULE). Verify only the error type.

## Imports
- `import { Symbol } from '<relative module path>'` using the exact path from the topology contract /
  production snapshot. Never deep-guess paths; never re-implement production code in the test.

## Assembly Contract
- Return the COMPLETE test file content in `new_imports` + `new_test_code` and set
  `overwrite_existing` to true. The engine does not AST-merge TS/JS — emit the whole file each time.
