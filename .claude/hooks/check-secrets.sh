#!/bin/bash
# PreToolUse(Bash) hook: three single-purpose guards, all via exit 2:
#   1. Before any `git commit` / `git push` (even inside compound `&&` / `;`
#      chains, heredocs, or `bash -c "..."`), scan staged files for secrets,
#      gitignored-folder paths, and obvious secret patterns.
#   2. Block any Bash command that *writes* to a `.env` file via redirection
#      (`> .env`, `>> .env`), `tee .env`, `sed -i ... .env`, or `cp/mv X .env`.
#      Closes the gap where `block-env-edits.sh` only covers Edit/Write tools.
#   3. Force `git add` and `git commit` to be separate Bash invocations,
#      so the staged-diff scan in guard #1 actually sees the staging area.

# Bash tool input arrives as JSON on stdin; extract the command string.
CMD=$(jq -r '.tool_input.command // empty')

# ─── Guard 2: Bash write to .env ──────────────────────────────────────────
# Allow .env.example (template). Match common write patterns to a .env target.
# Patterns: `> .env`, `>>.env`, `tee .env`, `sed -i ... .env`, `cp X .env`,
# `mv X .env`. Excludes `.env.example` via the trailing word boundary.
if echo "$CMD" | grep -qE '([>]{1,2}\s*|tee\s+|sed\s+-i\s+.*\s|cp\s+\S+\s+|mv\s+\S+\s+)\.env([^.]|$)'; then
  echo 'BLOCKED: Bash command appears to write to a .env file. Secrets belong in the OS keychain or your platform secret store, not in committed .env files. Use .env.example for templates.' >&2
  exit 2
fi

# ─── Guard 3: block compound `git add ... git commit/push` in ONE invocation ──
# The hook fires before the Bash command runs, so when staging happens inside
# the same chain as the commit (e.g. `git add X && git commit`), the staging
# area is empty at scan time and any secrets sneak through. Force them apart.
if echo "$CMD" | grep -qE 'git\s+add\b' && echo "$CMD" | grep -qE 'git\s+(commit|push)\b'; then
  echo 'BLOCKED: Single Bash invocation contains both `git add` and `git commit`/`git push`. Split them — the staging area is empty when the secret scanner runs inside a compound command, defeating the gate. Run `git add ...` first, then `git commit ...` as a separate command.' >&2
  exit 2
fi

# ─── Guard 1: scan staged diff before git commit/push ─────────────────────
# Match `git commit` or `git push` anywhere in the command (no `^` anchor),
# so chains that ONLY commit (no staging) like `git commit && echo ok` still
# trigger the staged-diff scan.
echo "$CMD" | grep -qE 'git\s+(commit|push)\b' || exit 0

# Sensitive keywords in staged diffs. Exclude docs (.md), shell scripts, and
# the .claude/ ruleset — those legitimately describe the very keywords we
# scan for (the hook itself, security docs, etc.) and would false-positive.
# Real-secret patterns below still cover every file.
SECRETS=$(git diff --cached --diff-filter=ACM -S 'password' -S 'secret' -S 'api_key' -S 'apikey' -S 'token' -S 'private_key' -S 'service_account' --name-only -- ':(exclude).claude/**' ':(exclude)*.md' ':(exclude)*.sh' 2>/dev/null)

# Known secret patterns (API keys, private keys, JWKs). Exclude .md so doc
# examples of a JWK shape (`"kty": "RSA"`) don't trip. Anything actually
# encoding a key in source/config still matches.
PATTERNS=$(git diff --cached --diff-filter=ACM -G '(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36}|-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|"kty":\s*"RSA"|"kty":\s*"EC")' --name-only -- ':(exclude)*.md' 2>/dev/null)

# .env files being committed (allow .env.example).
ENVFILES=$(git diff --cached --name-only 2>/dev/null | grep -E '\.env$|\.env\.' | grep -v '\.example$')

FOUND="${SECRETS}${PATTERNS}${ENVFILES}"

if [ -n "$FOUND" ]; then
  echo "BLOCKED: Potential secrets or .env files detected in staged files:" >&2
  echo "$FOUND" | sort -u >&2
  echo "Review these files before committing. Move secrets to the OS keychain or your platform's secret store." >&2
  exit 2
fi

exit 0
