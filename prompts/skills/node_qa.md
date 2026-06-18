---
skill_id: node_qa
type: domain
triggers: [node, typescript, javascript]
nodes: [qa, reviewer]
---
LANGUAGE TARGET: Node.js (TypeScript/JavaScript) — concrete syntax for the Node tech stack. The
language-neutral rules (exception fidelity, import fidelity, whole-file assembly, BVA strategy) live
in the QA system prompt; this skill only maps them to Node idioms.

## Testing Framework & Layout
- Use the ecosystem-standard runner the project is configured for (jest or vitest); both expose
  `describe`/`it`/`expect`. Do NOT introduce a second test runner. Match the source language: write
  `.test.ts` for TypeScript source, `.test.js` for JavaScript source.
- Colocate the test file NEXT TO its source file as `<name>.test.<ext>` (e.g. `app.ts` →
  `app.test.ts`). NEVER create a separate `tests/` directory. Assume the contract provides the `test`
  script in `package.json` and the runner devDependency.

## Test Shape
- Group behaviors under `describe(...)`; one `it(...)` per case. Drive variants from an explicit
  array of `{name, input, expected}` iterated with `it.each(table)(...)` (jest) or a `for...of`
  loop calling `it(...)` (vitest) so each case is isolated and independently reported.

## Assertions & Errors (concrete API for the system-prompt CRITICAL RULE)
- Assert thrown errors with `expect(() => fn()).toThrow(ErrorType)` — pass the error CLASS/type only.
  NEVER `.toThrow('message')`, `.message`, or any message-derived value.

## Imports
- `import { Symbol } from '<relative module path>'` using the exact path from the topology contract /
  production snapshot.
