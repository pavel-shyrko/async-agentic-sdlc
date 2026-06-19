# 0013 — Structured Test Maintenance via AST-Aware Pruning & Smart Appending

## Status

Superseded by [0014](0014-language-neutral-qa-whole-file-assembly.md) — the AST-aware Python-only
merge was removed to eliminate per-language hardcode in the QA agent. QA now uses one language-neutral
whole-file assembly path; test correctness (packaging/namespace/placement) is driven by skills + the
compile-gate→QA retry loop rather than engine-side surgery.

## Context

When the QA agent regenerated tests for a module that already had a test file (a new ticket touching
an existing module, or a self-heal retry), it performed a **blind overwrite** — the final
`open(test_path, "w")` wrote whatever the model returned, destroying every prior test case if the
model regenerated from scratch ("State Cascade Destruction").

The first fix had the model return the **entire merged file** (read the existing suite, inject it into
the prompt, ask the model to preserve-and-append) with a code-side guard that, on detecting dropped
cases, redirected output to a uniquely-suffixed `test_<slug>_v2.py` file. Two defects remained:

1. **LLM whole-file merging is lossy and non-deterministic.** Asking the model to re-emit a large
   existing suite verbatim plus new cases burns output tokens, invites truncation, and risks
   hallucinating or silently mutating untouched tests — the merge correctness depends entirely on the
   model.
2. **Zombie files.** The `_v2.py` / `_v3.py` fallback accumulated parallel test files across cycles,
   fragmenting coverage and leaving stale duplicates the snapshot and runner then had to reconcile.

The root problem: a probabilistic model was made responsible for a **deterministic** file-surgery
operation (preserve N existing cases, add M new ones, remove K obsolete ones).

## Decision

Move the file surgery out of the model and into the engine. The model returns only **deltas**; a
deterministic Python routine using the standard-library `ast` module applies them in place.

- **Delta schema** — `QATestSuite` (`src/shared/core/models.py`) is replaced with three fields:
  `new_imports` (str, new import lines only), `new_test_code` (str, only the NEW classes/functions),
  and `obsolete_test_names` (list[str], exact names of now-invalid existing tests). The
  `clean_markdown_fences` validator is bound to both code fields.
- **Prompt** — the QA system prompt (`prompts/system/qa.md`) replaces the "output the entire merged
  file" rule with a `STRUCTURED TEST MAINTENANCE` rule: never re-emit the file; return new code, new
  imports, and the names of obsolete cases for the engine to prune.
- **AST-aware assembly** — `_assemble_suite` in `src/executor/agents/qa.py` parses the on-disk file
  (`ast.parse`), drops top-level `ClassDef`/`FunctionDef`/`AsyncFunctionDef` nodes whose name is in
  `obsolete_test_names`, re-serialises with `ast.unparse`, then assembles
  `deduped_imports + pruned_body + new_test_code + main_guard`. Hardening: imports are deduplicated
  against the existing body (no `import unittest` stacking); segments are joined with blank-line
  separators so nothing fuses into a `SyntaxError`; any `if __name__ == "__main__"` guard is relocated
  to the very end so appended classes are defined before `unittest.main()`; all I/O is explicit
  `utf-8`; a `try/except SyntaxError` falls back to append-without-prune so a malformed file never
  crashes the node. The result is always written back to the **original** `test_path` — no `_v2`
  files.

## Consequences

- **Pros**: test maintenance is now deterministic — preservation of untouched cases is guaranteed by
  the engine, not the model's goodwill; output tokens shrink to the delta (the model never re-emits the
  existing suite), removing the truncation/hallucination surface of whole-file merges; zombie `_v2`
  files are eliminated, so one module maps to exactly one stable test file; obsolete cases are removed
  surgically by name rather than by trusting the model to omit them; and the assembly is robust against
  the common failure modes (duplicate imports, concatenation `SyntaxError`, misplaced `__main__`
  guard, non-utf8 locales, an unparseable on-disk file).
- **Cons / constraints**: pruning operates on **top-level** `tree.body` only — an obsolete name that is
  a *method* nested inside a class is not removed (the model must instead drop the enclosing class or
  rewrite it in `new_test_code`); `ast.unparse` normalises the existing file, discarding comments and
  exact formatting (acceptable for machine-generated suites, but the on-disk file will not byte-match
  what a human wrote); and correctness now depends on the model reporting accurate
  `obsolete_test_names` — a wrong name silently prunes nothing (safe) or, if it matches a still-valid
  case, removes a test that should have stayed (the model owns that judgement, the engine owns the
  mechanism).
