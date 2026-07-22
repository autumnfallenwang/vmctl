#!/bin/bash
# PreToolUse(Edit|Write) hook: block direct edits to .env files.
# Secrets belong in the OS keychain or your platform's secret store, not in
# checked-in .env files. Use .env.example as a template instead.
#
# Explicit allowlist: .env.example is the template file this hook's error
# message points users to — it's safe by design (dummy values only, committed
# to the repo). Without this carve-out the hook would block its own
# recommended target.

FILE=$(jq -r '.tool_input.file_path // empty')

# Allow: .env.example template (no real secrets, by convention).
case "$FILE" in
  *.env.example|*.env.example.*)
    exit 0
    ;;
esac

# Block: .env, .env.local, .env.production, .env.development, etc.
case "$FILE" in
  *.env|*.env.*)
    echo 'BLOCKED: Do not edit .env files — they may contain secrets. Use .env.example instead.' >&2
    exit 2
    ;;
esac

exit 0
