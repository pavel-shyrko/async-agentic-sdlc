# Skill: Factual Documentation Synchronization (Changelog & README)

## Context
Execute this skill to update factual project state tracking after code changes. Focus strictly on "What" changed.

## Protocol
1. **Diff Analysis**: Read the recent commits or `git diff`.
2. **CHANGELOG Update**:
   - Target `CHANGELOG.md`.
   - Strictly follow the "Keep a Changelog" format.
   - Map changes to standard blocks: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
   - Translate raw code diffs into human-readable engineering features/fixes. Do not dump raw commit messages.
3. **README Alignment**:
   - Target `README.md`.
   - Scan for out-of-sync factual data: new CLI arguments (e.g., flags), environment variables, altered directory structures, or updated execution commands.
   - Apply targeted diff patches to the relevant sections to reflect the current state.

## Output Format
Apply changes directly to the file system or provide strict `diff` blocks. End with a raw checklist of updated files. Zero conversational text.