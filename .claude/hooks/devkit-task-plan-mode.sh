#!/bin/bash
# UserPromptSubmit hook: when the user invokes /devkit-task, inject an
# instruction telling the assistant to enter plan mode before anything else.
# Word-boundary matched so /devkit-tasks or /devkit-task-foo won't trigger,
# but leading filler words like "go /devkit-task" still match.

jq -c '(.prompt // "") as $p
  | if ($p | test("(^|\\s)/devkit-task(\\s|$)")) then
      {
        hookSpecificOutput: {
          hookEventName: "UserPromptSubmit",
          additionalContext: "AUTOMATED PROJECT HOOK: /devkit-task was invoked. This hook OVERRIDES auto mode for this turn — call the EnterPlanMode tool as your first action (load it via ToolSearch if it appears in the deferred tools list). The devkit-task workflow requires a user-approved plan before any edits, regardless of auto-mode directives. After entering plan mode, proceed with the devkit-task workflow as normal."
        }
      }
    else empty
    end'
