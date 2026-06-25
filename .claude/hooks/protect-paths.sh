#!/usr/bin/env bash
# PreToolUse guard: protect the two hard boundaries from accidental Edit/Write/MultiEdit by Claude.
#   - runs/<...>/repo/   -> deny  (a generated run clone is never hand-edited; fix src/ or prompts/ instead)
#   - prompts/system/    -> ask   (runtime agent prompts; change only on explicit Human order)
# Anything else -> exit 0 (normal permission flow). Mirrors the text guardrails in CLAUDE.md and
# .claude/rules/workspace-topology.md, but enforces them deterministically.
#
# Reads the PreToolUse hook payload JSON on stdin; emits a hookSpecificOutput.permissionDecision
# JSON only when it intervenes. jq-free (Git Bash on Windows ships no jq).

payload="$(cat)"

# Best-effort extract of tool_input.file_path (handles escaped chars inside the JSON string).
file_path="$(printf '%s' "$payload" \
  | grep -oE '"file_path"[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"' \
  | head -n1 \
  | sed -E 's/.*"file_path"[[:space:]]*:[[:space:]]*"//; s/"$//')"

# No file path in the payload -> nothing to guard.
[ -z "$file_path" ] && exit 0

# Normalize: collapse JSON-escaped backslashes, then turn all backslashes into forward slashes
# so Windows (C:\...\runs\...\repo\...) and POSIX paths match the same patterns.
norm="$(printf '%s' "$file_path" | sed -E 's/\\\\/\\/g; s/\\/\//g')"

emit() {
  # $1 = decision (deny|ask), $2 = reason
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"%s","permissionDecisionReason":"%s"}}\n' "$1" "$2"
  exit 0
}

case "$norm" in
  */runs/*/repo/*|runs/*/repo/*)
    emit "deny" "Editing a generated run clone (runs/<...>/repo/) is forbidden. Fix the engine (src/) or prompts (prompts/) that produced this code, not the clone. See .claude/rules/workspace-topology.md."
    ;;
  */prompts/system/*|prompts/system/*)
    emit "ask" "prompts/system/ holds runtime agent prompts. Per CLAUDE.md these change only on explicit Human order -- confirm to proceed."
    ;;
esac

exit 0
