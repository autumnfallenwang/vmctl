---
name: devkit-task
description: Use when the user types /devkit-task or says "work on this", "let's build X", "implement X", "fix this bug", "what's next". The daily workhorse — reads project context, plans, gates on user approval, implements, runs the check loop, and optionally records.
allowed-tools: Read, Write, Edit, Bash
disable-model-invocation: true
---

The daily workhorse. Implements one task end-to-end with a human plan-approval gate. Sub-skills handle verification (lint / typecheck / test) and recording (milestone notes / knowledge capture). Commit is a separate explicit step invoked via `/devkit-commit`.

## Phase 1 — Read project context

Load everything needed to plan well:

1. `CLAUDE.md` — project profile, commands, decision tree.
2. `docs/architecture.md` — current system shape.
3. The **active milestone file** — highest-numbered open file under `docs/milestones/`.
4. Recent ADRs (`docs/adr/`) — at least the most recent two.
5. `knowledge/KNOWLEDGE.md` index, plus any topic files whose descriptions match the current task.
6. `git log -10 --oneline` to see what's been shipping.

If `$ARGUMENTS` was passed, treat it as the task description. Otherwise the user's most recent message defines the task.

## Phase 2 — Plan

Draft a concrete implementation plan:

- **Files to create or modify** (exact paths).
- **Types, interfaces, function signatures** to define.
- **Tests to write** (test names + what they verify).
- **Wiring changes** (imports, registrations, config).
- **Risks or open questions.**

Be concrete. Not "we'll add a helper" — `parseHeaders(input: string): Headers` in `src/lib/http.ts`. Not "write some tests" — three named test cases.

If the task is a **bug fix**, lead the plan with a hypothesis about root cause and how the fix addresses it. Don't propose changes without a hypothesis.

## Phase 3 — Plan gate (ALWAYS — the human gate)

Present the plan. Wait for explicit "go" before writing any code.

If the user has feedback, revise and present again. Iterate until "go". This gate is **non-negotiable** — even for one-line fixes, the plan loop catches misunderstandings before they cost real time.

## Phase 4 — Implement

Execute the approved plan. Create / modify files. Write tests alongside implementation, not after.

If a decision the plan didn't anticipate arises mid-implementation, **pause and surface it** to the user. Do not freelance architecture-shaping decisions.

## Phase 5 — Check loop

Run verification in sequence:

1. **REQUIRED SUB-SKILL:** Use `devkit-lint`. Wait for the result.
2. **REQUIRED SUB-SKILL:** Use `devkit-typecheck`. Wait for the result.
3. **REQUIRED SUB-SKILL:** Use `devkit-test fast`. Wait for the result.

### Recovery strategy on failure

- **Lint failure** → invoke `devkit-lint fix` for auto-fix, then re-run from step 1.
- **Type error** → read the error, fix the source, re-run from step 2.
- **Test failure** → analyze the failure, fix the source or the test (preferring source), re-run from step 3.

Retry up to **3 times total** across the whole loop. Each retry must address a different issue, not retry the same broken thing.

If still failing after 3 attempts:

- Stop, summarize what's failing and why.
- Show the relevant output.
- Ask the user how to proceed (fix manually, change approach, skip).

Do not silently loop.

## Phase 6 — Update milestone notes

**REQUIRED SUB-SKILL:** Use `devkit-update-milestone` with a one-line note summarizing what shipped. Skip if no milestone is active.

## Phase 7 — Knowledge capture (conditional)

If anything in this cycle revealed a reusable lesson — a user correction, a hard-won pattern, a configuration gotcha worth caching — ask the user:

> "Capture as a knowledge entry?"

If yes, invoke `devkit-knowledge-capture`. If no, move on.

## Phase 8 — Report

Summarize:

- **What was implemented** (1–2 sentences).
- **Check loop result** (lint / typecheck / test all passed, or what failed).
- **Milestone note** added? Yes/no.
- **Knowledge captured?** Yes/no.
- **Suggested next step:** "Smoke-test the result, then run `/devkit-commit` when you're ready to ship — or keep iterating."

## Notes

- **Never run `/devkit-commit` from this skill.** Commit is a deliberate, separate step. The user decides when to ship.
- **Never freelance architecture changes.** New components, moved boundaries, renamed exports — all require explicit user confirmation, even if they seem mechanical.
- **Disciplines baked in:**
  - *Plan-before-code:* the Phase 3 gate is the contract.
  - *Verify-before-done:* Phase 5 must pass before reporting success.
  - *Systematic-debug:* on test failure, form a hypothesis, propose a targeted fix, verify. Don't shotgun changes.
- **For "what's next" without a specific task:** read the active milestone's exit criteria, propose the next concrete task that moves toward them, then enter Phase 2.
