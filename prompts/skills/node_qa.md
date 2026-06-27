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

## Test Runner Working Directory
- `npm test` runs from the **component's package directory** (e.g. `frontend/`), NOT from the repo root. All import paths are relative to `frontend/src/` — do NOT prefix imports with `frontend/`. Read each source file to verify the exact path before writing any import.
- In a fullstack monorepo, frontend tests and backend tests run independently; never import from the backend package in a frontend test.

## Imports
- `import { Symbol } from '<relative module path>'` using the exact path from the topology contract / the source file you Read. Relative paths are relative to the test file's location (e.g. `../api/client`).

## ESM Module-Level Singleton Mocking (vitest)

When the production module creates a singleton **at module level** (e.g. `const client = lib.create(...)`
executed once during import), `beforeEach` is too late — by the time it runs, `lib.create()` has already
been called with the auto-mock's default (`undefined`) return value, causing `TypeError: Cannot read
properties of undefined` on every call.

**Correct pattern — use the `vi.mock` factory argument:**
```js
const mockInstance = {
  get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
};
vi.mock('axios', () => ({
  default: { create: vi.fn(() => mockInstance) },
}));
```
The factory runs synchronously during module resolution, before any test code, so `lib.create()` returns
`mockInstance` when the module under test initialises its singleton.

**NEVER write:**
```js
// ❌ Too late — module already initialized with undefined
beforeEach(() => { axios.create.mockReturnValue(mockAxiosInstance); });
```

**NEVER assert per-call `create` counts for a singleton design:**
```js
// ❌ Wrong — the contract says "configure one instance", not "create one per call"
expect(axios.create).toHaveBeenCalledTimes(2); // after two getTasks() calls
```
If the contract mandates a pre-configured singleton, `create` is called exactly **once** at import time —
assert that at most in a single dedicated `it` block, or omit the count assertion entirely.
