---
name: devkit-test
description: Use when the user says "test", "run tests", "fast tests", "all tests", "smoke test the tests", or when `devkit-task`'s check loop invokes this skill.
allowed-tools: Bash
---

Run the test suite for vmctl. If `$ARGUMENTS` contains the word `fast`, run the fast variant (unit tests only); otherwise run the full suite.

## Commands

- **python (pytest)**
  - run: `uv run pytest`
  - fast: `uv run pytest -m 'not integration'`

## Reporting

After running:

- **Exit 0** → report a one-line summary (e.g. "47 tests passed in 1.2s") and stop.
- **Non-zero exit** → show the failing test names and the first 20 lines of relevant output. Do not re-run automatically; surface the failure and wait for direction.

## Notes

- This skill is invoked by `devkit-task`'s check loop as part of the standard verification sequence. It is also user-facing via natural language ("run the tests", "are the tests passing", etc.).
- If multiple language sections are listed above, run each in order. A non-zero exit from any section stops the sequence — fix that one before moving on.
- The `fast` variant is for tight inner-loop verification during `/devkit-task`. The full variant is for `/devkit-commit` pre-flight or when the user asks for "all tests".
