---
paths:
  - "docs/hackathon/**"
---

# `docs/hackathon/` is a human-gated, isolated dossier — never auto-touch it

`docs/hackathon/` holds the Cyberthone 2026 mission briefings, the judge scorecard, and our
competition notes. It is a **manually curated** record, NOT engine-synced documentation. Two hard
rules govern it:

## 1. Edit ONLY with explicit user consent
Never create, edit, delete, or restructure any file under `docs/hackathon/` on your own initiative.
Touch it **only** when the user explicitly asks for that specific change in this turn. Treat every
file here as user-owned content:
- A mission file (`missions/NN-*.md`) is a **verbatim transcription** of a received transmission —
  do not paraphrase, summarize, "improve", or correct it. Save what the user pasted, as-is.
- Do not pre-emptively draft, reorganize, or "tidy" these files because they look incomplete (the
  `_pending_` mission rows are intentional placeholders, not TODOs for you).

## 2. NEVER bundle these edits with code or other docs
This directory is **excluded from every automated sync surface**. Do not couple a `docs/hackathon/`
change to anything else:
- The metadata-sync skills (`/tbf-docs-sync`, `/tbf-adr-generation`, `/tbf-claude-context-sync`,
  `/tbf-practicum-update`, `/tbf-iteration-release`) MUST NOT read from or write to it. It is not part of the
  "peer-set" those skills reconcile against the code.
- Do not update it as a side effect of a code change, an ADR, a CHANGELOG bump, an iteration release,
  or any other documentation edit. A commit that touches `src/`/`prompts/`/`docs/decisions/`/etc. must
  not also touch `docs/hackathon/` unless the user asked for the hackathon edit by itself.
- Conversely, do not "propagate" engine changes into the hackathon docs to keep them in sync — they
  intentionally drift from the code and reflect only what the user curates.

**Why:** these are competition-submission artifacts and received briefings whose wording is graded and
whose timing matters (e.g. the Mission 00 SDLC-spec deadline). Silent edits, auto-summarization, or
sync-skill churn could corrupt a verbatim brief or a submission doc without the user noticing.

**How to apply:** if engine/doc work *seems* like it should update something here, STOP and ask the
user first; surface the suggestion, don't act on it. The default action for this directory is **propose,
never mutate**.
