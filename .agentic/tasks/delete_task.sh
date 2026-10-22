#!/usr/bin/env bash
# Remove a task dir created by create_task.sh.
#
# Refuses to delete while the task clone has uncommitted changes or unpushed
# commits; -f overrides. Local branches die with the clone; -b also deletes the
# task branch on origin.
#
#   $0 <branch>         remove the task dir (safety checks on)
#   $0 <branch> -f      remove even with uncommitted/unpushed work
#   $0 <branch> -b      also delete the remote branch on origin
#
# Example: .agentic/tasks/delete_task.sh feat/foo-bar

set -euo pipefail

# --- config ----------------------------------------------------------------
# This repo's default branch — never a valid target for -b.
BASE_BRANCH="main"
# ---------------------------------------------------------------------------

FORCE=0
DELETE_REMOTE_BRANCH=0
BRANCH=""

for arg in "$@"; do
  case "$arg" in
    -f)
      FORCE=1
      ;;
    -b)
      DELETE_REMOTE_BRANCH=1
      ;;
    -*)
      echo "ERROR: unknown flag $arg" >&2
      exit 1
      ;;
    *)
      if [[ -n "$BRANCH" ]]; then
        echo "ERROR: branch given more than once ($BRANCH, $arg)" >&2
        exit 1
      fi
      BRANCH="$arg"
      ;;
  esac
done

if [[ -z "$BRANCH" ]]; then
  echo "Usage: $0 <branch> [-f] [-b]" >&2
  echo "  -f  delete even with uncommitted changes / unpushed commits" >&2
  echo "  -b  also delete the remote branch on origin" >&2
  exit 1
fi

# Match the dir-name flattening done by create_task.sh (feat/test2 → feat-test2).
TASK_DIR_NAME="${BRANCH//\//-}"

# Self-locate: this script lives at <main>/.agentic/tasks/, so the main checkout
# is two levels up and the task dirs sit in its <main>-tasks/ sibling.
MAIN_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TASK_DIR="${MAIN_DIR}-tasks/$TASK_DIR_NAME"

if [[ ! -d "$TASK_DIR" ]]; then
  echo "ERROR: $TASK_DIR does not exist" >&2
  exit 1
fi

# Every git repo in the task dir. Normally just the task clone itself; the scan is
# depth-3 so a stray nested checkout is still safety-checked rather than silently removed.
REPOS=()
while IFS= read -r gitdir; do
  REPOS+=("$(dirname "$gitdir")")
done < <(find "$TASK_DIR" -maxdepth 3 -name .git \( -type d -o -type f \) | sort)

# Not a task clone (no .git found) — bash 3.2 aborts on empty-array expansion
# under set -u, and there is nothing to safety-check anyway.
if [[ ${#REPOS[@]} -eq 0 ]]; then
  echo "WARN: no git repos found in $TASK_DIR — removing as a plain directory" >&2
  rm -rf "$TASK_DIR"
  echo "Done."
  exit 0
fi

DIRTY=0
for repo in "${REPOS[@]}"; do
  label="${repo#"$TASK_DIR"}"
  label="${label:-<task clone>}"
  if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
    echo "WARN: uncommitted changes in ${label#/}" >&2
    DIRTY=1
  fi
  if [[ -n "$(git -C "$repo" log --branches --not --remotes --oneline 2>/dev/null | head -1)" ]]; then
    echo "WARN: unpushed commits in ${label#/}" >&2
    DIRTY=1
  fi
done

if ((DIRTY)) && ((!FORCE)); then
  echo "ERROR: task dir has uncommitted/unpushed work (see above). Rerun with -f to delete anyway." >&2
  exit 1
fi

if ((DELETE_REMOTE_BRANCH)); then
  # Never point remote deletion at the base branch, whatever state the dir is in.
  if [[ "$BRANCH" == "$BASE_BRANCH" ]]; then
    echo "ERROR: refusing -b for base branch '$BRANCH'" >&2
    exit 1
  fi
  # Via the main checkout: this runs on the host, where its origin's credentials work.
  echo "==> Deleting remote branch $BRANCH on origin"
  git -C "$MAIN_DIR" push origin --delete "$BRANCH" || echo "(no remote branch $BRANCH — skipped)"
fi

echo "==> Removing $TASK_DIR"
rm -rf "$TASK_DIR"

echo
echo "Done."
