#!/usr/bin/env bash
# Create a per-task clone of this repo and open it in a dev container.
#
# The task dir IS a plain clone (self-contained .git — no worktree pointers,
# no extra bind mounts):
#   <parent>/tasks/<dir>    branch <branch> from origin/<BASE_BRANCH>
#
# This is a monorepo, so the clone carries everything the task needs — the agents,
# the knowledge base, and the harness config. Nothing else is provisioned.
#
# Run from anywhere — the script self-locates relative to its own path, and the
# checkout containing it is the clone source. Run it from the MAIN checkout, not
# from a task clone.
#
# Example: .agentic/tasks/create_task.sh feat/foo-bar

set -euo pipefail

# --- config ----------------------------------------------------------------
# Branch new task clones fork from.
BASE_BRANCH="main"
# Workspace file inside this repo that VS Code opens.
WORKSPACE_FILE="claude-agents-factory.code-workspace"
# Container path the workspace is mounted at (devcontainer.json workspaceFolder).
CONTAINER_WS="/workspaces/claude-agents-factory"
# ---------------------------------------------------------------------------

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <branch>" >&2
  echo "Example: $0 feat/foo-bar" >&2
  exit 1
fi

BRANCH="$1"

# The base branch is never a task branch; also avoids colliding with the clone's
# own default branch at checkout time.
if [[ "$BRANCH" == "$BASE_BRANCH" ]]; then
  echo "ERROR: '$BRANCH' is the base branch — pick a task branch like feat/foo-bar" >&2
  exit 1
fi

# Flatten slashes in the directory name (feat/test2 → feat-test2) while keeping
# the original form for the branch name. Avoids nested tasks/feat/test2/ trees.
TASK_DIR_NAME="${BRANCH//\//-}"

# Self-locate: this script lives at <main>/.agentic/tasks/, so the checkout
# containing it — the clone source — is two levels up.
MAIN_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="$(dirname "$MAIN_DIR")"

if [[ "$(basename "$ROOT")" == "tasks" ]]; then
  echo "ERROR: running from a task clone ($MAIN_DIR). Run from the main checkout." >&2
  exit 1
fi

TASK_DIR="$ROOT/tasks/$TASK_DIR_NAME"

if [[ -e "$TASK_DIR" ]]; then
  echo "ERROR: $TASK_DIR already exists" >&2
  exit 1
fi

# Always clone fresh from the remote — the local main checkout may be behind.
# The URL is read from the main checkout so nothing is hardcoded here.
ORIGIN_URL="$(git -C "$MAIN_DIR" remote get-url origin)"

echo "==> Cloning $ORIGIN_URL -> $TASK_DIR"
git clone "$ORIGIN_URL" "$TASK_DIR"

echo "==> Branching $BRANCH from origin/$BASE_BRANCH"
git -C "$TASK_DIR" checkout -b "$BRANCH" "origin/$BASE_BRANCH"

# Build a vscode-remote:// URI that opens the workspace directly in the dev
# container, skipping the "Reopen in Container" click. The "+<hex>" is the
# lowercase hex of the host folder that holds .devcontainer/, as UTF-8 bytes.
#
# Requires on macOS: Docker Desktop running with "Allow the default Docker
# socket to be used" enabled (Settings → Advanced). Without it, you get either
# "Cannot connect to the Docker daemon at /var/run/docker.sock" or "spawn docker ENOENT".
WS_FILE_HOST="$TASK_DIR/$WORKSPACE_FILE"
HEX=$(printf '%s' "$TASK_DIR" | od -An -tx1 | tr -d ' \n')
URI="vscode-remote://dev-container+${HEX}${CONTAINER_WS}/${WORKSPACE_FILE}"

if command -v code >/dev/null 2>&1; then
  echo "==> Opening VS Code (auto-attach to dev container)"
  code --file-uri "$URI"
else
  echo
  echo "VS Code 'code' CLI not found. Open manually:"
  echo "  $WS_FILE_HOST"
fi

echo
echo "Done. First open may prompt for workspace trust (one-time)."
