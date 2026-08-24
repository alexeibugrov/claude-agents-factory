#!/usr/bin/env bash
# UserPromptSubmit hook: nudge to run /harvest-lessons when the operator signals task finalize.
# Stdout on exit 0 is injected as context, so a match adds the reminder; no match stays silent.
set -euo pipefail

payload="$(cat)"

if command -v jq >/dev/null 2>&1; then
  prompt="$(printf '%s' "$payload" | jq -r '.prompt // empty' 2>/dev/null || true)"
else
  prompt="$payload"
fi

finalize_re="finali[sz]e|wrap (this )?up|wrap it up|write the (task )?(entry|report)|(task|we'?re|we are|that'?s|all|i'?m) (is |been )?done|let'?s (wrap|finali[sz]e)"

if printf '%s' "$prompt" | grep -qiE "$finalize_re"; then
  printf 'Reminder: this looks like task finalize. Run /harvest-lessons to route this session'\''s operator feedback into skills / conventions / CLAUDE.md before writing report.md (task-flow finalize step).\n'
fi

exit 0
