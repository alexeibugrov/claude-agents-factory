# Hooks

## UserPromptSubmit

`finalize-harvest-reminder.sh` reads the prompt from the hook JSON on stdin and, when it matches task-finalize phrasing (`finalize`, `wrap this up`, `write the task entry`, `task/we're/all … done`, …), prints a one-line reminder to run [`/harvest-lessons`](../skills/harvest-lessons/SKILL.md). Stdout of a `UserPromptSubmit` hook is injected as context on exit 0, so a match nudges and a non-match stays silent — fail-open, never blocking. Wired in [.claude/settings.json](../settings.json) under `hooks.UserPromptSubmit`. It is the forcing function for the end-of-task knowledge harvest (see [`task-flow`](../skills/task-flow/SKILL.md) finalize).

Restart the Claude Code session after editing `settings.json` or any hook script — hook config is read once at session start.
