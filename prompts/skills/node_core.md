---
skill_id: node_core
type: domain
triggers: [node, typescript, javascript]
nodes: [techlead, developer, reviewer]
---
LANGUAGE TARGET: Node.js (TypeScript/JavaScript) — production-code rules for the Node tech stack.

## Runtime & Sandbox
- Target Node.js 22, executed in the isolated Docker sandbox (`node:22-alpine`).
- Prefer TypeScript with `strict` mode on. The build (`tsc` / bundler) MUST pass with no type errors.

## Types & Guards
- Enable and respect strict typing: BAN `any` (use `unknown` + narrowing). Explicitly narrow
  `null`/`undefined` before use; never assume a value is present.
- Validate inputs at the boundary and reject wrong types/shapes early. Do not coerce implicitly
  (avoid `==`; use `===`).

## Error Handling
- Throw typed `Error` subclasses for invalid input (e.g. `class InvalidFormatError extends Error`);
  never throw bare strings and never silently swallow (no empty `catch`).
- Use `async`/`await` with `try/catch`; never leave a promise rejection unhandled. Distinguish errors
  by their CLASS/`instanceof`, not by message text.

## Module & Package Glue
- Follow the module system the project declares: ESM vs CommonJS per `package.json` `"type"` — match
  it consistently (import/export style). There is NO `__init__.py`-style package-init file; an
  `index.ts` barrel is OPTIONAL glue you may add when it improves imports.
- Manage dependencies and scripts in `package.json` (the `test` script + runner devDependency must
  exist for the QA gate). Create glue/entry files the build needs without waiting for the contract.
- Commit a `package-lock.json` so the toolchain restores deterministically with `npm ci` (it falls
  back to `npm install` if the lockfile is absent, but the lockfile is preferred).

## Security
- `npm audit --audit-level=high` runs before review — zero tolerance for flagged vulnerabilities.
