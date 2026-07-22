---
name: devkit-commit
description: Use when the user types /devkit-commit or says "commit", "ship it", "save what I have", "wrap this up". End of a work cycle — generates a commit message from the diff, optionally captures knowledge and updates milestone notes, then commits.
allowed-tools: Bash(git *), Read, Edit
disable-model-invocation: true
---

Wrap up a work cycle. Inspect the diff, draft a commit message, optionally record knowledge or milestone progress, then commit.

## Phase 1 — Inspect the diff

1. `git status` — show tracked / untracked / staged / modified.
2. `git diff` and `git diff --staged` to see what's actually changing.
3. If untracked files exist, ask the user which to include. **Never** use `git add -A` or `git add .` — risk of staging `.env` files or credentials. Add specific files by name.
4. `git log -5 --oneline` to match the repo's commit-message style (conventional commits vs. terse vs. structured).

## Phase 2 — Draft the message

Match the observed style. Default shape:

- **Subject line:** 1 line, under 72 chars, imperative mood (e.g. "Add /logout endpoint with session invalidation").
- **Body (optional):** 2–3 lines explaining the **why**, not the **what** (the diff shows what).

Present the draft and ask:

> "Commit with this message, edit it, or cancel?"

Iterate until the user approves.

## Phase 3 — Knowledge capture (conditional)

Before committing, ask whether the work surfaced any reusable lesson:

- Was there a user correction worth caching?
- Did a hard-won pattern emerge?
- Is there a constraint or convention that future sessions should know?

If yes, invoke **REQUIRED SUB-SKILL:** `devkit-knowledge-capture` and wait for its result before continuing.

## Phase 4 — Milestone update (conditional)

If a `docs/milestones/NN-*.md` file is active and the work shipped a meaningful unit, invoke **REQUIRED SUB-SKILL:** `devkit-update-milestone` to append a progress note. The note text should be a one-line summary of what shipped.

## Phase 5 — Commit

1. `git add <specific files>` — never `-A`.
2. `git commit -m "<approved message>"`.
3. `git log -1 --oneline` to confirm.

Report the resulting SHA.

## Notes

- **Never `git push`** from this skill. Push is a separate, explicit action.
- **Never amend** a previous commit unless the user explicitly asks for `--amend`.
- **Never skip hooks** (`--no-verify`). If a pre-commit hook fails, surface the failure, fix the underlying issue, and create a new commit.
- **Sensitive files:** refuse to stage `.env*`, `*.key`, `*.pem`, or anything under a path matching `credentials*`. If the user really wants to commit one, ask for explicit re-confirmation.
- **The user smoke-tests before `/devkit-commit`.** This skill assumes the work has been observed to actually work — it doesn't re-run the check loop. Use `devkit-task` for the build → verify cycle; use this skill only when the user is ready to ship.
