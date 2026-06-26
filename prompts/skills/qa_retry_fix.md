---
skill_id: qa_retry_fix
type: stateful
nodes: [qa]
---
CRITICAL FIX INSTRUCTION: Analyze the Validation Failure Context. Extract the previous code ONLY for the specific module you are currently testing, apply the fixes, and output ONLY the raw test code. DO NOT include `=== FILE ===` markers in your output.

VERBATIM-FIRST RULE: If the qa_diagnostic_payload contains a verbatim code snippet (e.g. a class body, a method, a helper stub), copy it EXACTLY as the starting point — do NOT paraphrase, summarize, or regenerate from scratch. Apply only the minimal surrounding changes needed to make it compile and pass.

DOMAIN TRAPS — re-read before any edit: if domain skills are loaded, re-execute their MANDATORY PRE-WRITE SCAN section before touching any test. A pattern missed in the previous cycle (e.g. FakeHttpResponseFeature for OnStarting, Assert.ThrowsAny for BCL-derived exceptions) MUST be applied now. Do not assume the previous test was structurally correct except for the gate failure.
