"""Paths, prompt identity, and the environment every Promptfoo invocation runs with."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from agent.config import AgentConfig, compose_prompt

EVALS_DIR = Path(__file__).resolve().parent
AGENT_DIR = EVALS_DIR.parent
REPO_DIR = AGENT_DIR.parent.parent
AGENT_CONFIG = AGENT_DIR / "agent_config.yaml"
SETTINGS = EVALS_DIR / "settings.yaml"

RUNS_DIR = EVALS_DIR / "runs"  # gitignored: generated configs and raw results
FEEDBACK_DIR = EVALS_DIR / "feedback"  # committed: reviewed batches, the provenance of each candidate
CANDIDATES_DIR = EVALS_DIR / "candidates"  # committed: proposed prompts, never adopted automatically
# Promptfoo's database (evals and the operator's ratings) and its cache. Inside the bind-mounted
# checkout, so reviews survive a devcontainer rebuild; gitignored.
PROMPTFOO_HOME = EVALS_DIR / ".promptfoo"
PROMPTFOO_BIN = EVALS_DIR / "node_modules" / ".bin" / "promptfoo"
MIN_NODE = (22, 22)

# The operator's verdict lives in a gradingResult component of this type (Promptfoo viewer 👍/👎).
HUMAN = "human"
# Name of the deterministic marker every output carries until the operator rates it.
REVIEW_METRIC = "human_review"

# Promptfoo splits a prompt file on lines of "---", and Nunjucks would rewrite these tokens; the
# prompt under test must reach the agent byte for byte.
_TEMPLATE_TOKENS = ("{{", "{%", "{#")


class EvalError(RuntimeError):
    """A refusal with a message for the operator; the CLI prints it and exits 2."""


ROLES = ("writer", "screener")


def prompt_sha(text: str, about_me: str | None = None) -> str:
    """Same identity as ``RoleConfig.prompt_sha`` (ABOUT ME included), so eval runs and production line up."""
    full = compose_prompt(text.strip(), about_me.strip() if about_me else None)
    return hashlib.sha256(full.encode("utf-8")).hexdigest()[:16]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    """A path as the operator types it: relative to the agent directory when inside it."""
    try:
        return str(path.resolve().relative_to(AGENT_DIR))
    except ValueError:
        return str(path)


def prompt_problems(text: str) -> list[str]:
    problems = []
    if not text.strip():
        problems.append("the prompt is empty")
    if any(line.strip() == "---" for line in text.splitlines()):
        problems.append('a line of only "---" (Promptfoo would split the file into several prompts)')
    for token in _TEMPLATE_TOKENS:
        if token in text:
            problems.append(f"template syntax {token!r} (Promptfoo/Nunjucks would rewrite it)")
    return problems


def load_prompt(path: Path) -> str:
    if not path.is_file():
        raise EvalError(f"prompt file not found: {path}")
    text = path.read_text(encoding="utf-8")
    problems = prompt_problems(text)
    if problems:
        raise EvalError(f"{rel(path)} cannot be evaluated as is: {'; '.join(problems)}")
    return text


def live_prompt(role: str = "writer") -> Path:
    """The prompt version production runs for ``role``: the file agent_config.yaml points it to."""
    file = getattr(AgentConfig.load(AGENT_CONFIG), role).system_prompt_file
    if not file:
        raise EvalError(f"the {role} prompt is inline in {rel(AGENT_CONFIG)}; pass --prompt")
    return AGENT_DIR / file


def live_about_me() -> Path | None:
    """The ABOUT ME version production appends to every role's prompt, if any."""
    file = AgentConfig.load(AGENT_CONFIG).writer.about_me_file
    return AGENT_DIR / file if file else None


def next_version(role: str = "writer") -> Path:
    """Where an adopted candidate goes: the next free prompts/<role>/v<N>.md."""
    taken = [
        int(m.group(1)) for p in (AGENT_DIR / "prompts" / role).glob("v*.md") if (m := re.fullmatch(r"v(\d+)", p.stem))
    ]
    return AGENT_DIR / "prompts" / role / f"v{max(taken, default=0) + 1}.md"


def settings() -> dict[str, Any]:
    return yaml.safe_load(SETTINGS.read_text()) or {}


def git_state() -> dict[str, Any]:
    """Commit and whether this agent's directory has uncommitted changes (the run may differ from it)."""

    def git(*args: str) -> str:
        out = subprocess.run(["git", *args], cwd=AGENT_DIR, capture_output=True, text=True, check=False)
        return out.stdout.strip()

    commit = git("rev-parse", "HEAD") or None
    dirty = git("status", "--porcelain", "--", ".")
    return {"commit": commit, "dirty": bool(dirty), "dirty_paths": dirty.splitlines()[:50]}


def _node_version() -> tuple[int, int] | None:
    try:
        out = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.match(r"v(\d+)\.(\d+)", out.strip())
    return (int(match.group(1)), int(match.group(2))) if match else None


def promptfoo_version() -> str | None:
    package = EVALS_DIR / "node_modules" / "promptfoo" / "package.json"
    return json.loads(package.read_text()).get("version") if package.is_file() else None


def promptfoo_env() -> dict[str, str]:
    """Environment for every Promptfoo call. Refuses API-key auth, like the agent's own startup."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise EvalError("ANTHROPIC_API_KEY is set; evals run on subscription auth only. Unset it.")
    env = dict(os.environ)
    # Set inside a Claude Code session; the SDK's bundled CLI refuses to start nested with it.
    env.pop("CLAUDECODE", None)
    env.update(
        PROMPTFOO_CONFIG_DIR=str(PROMPTFOO_HOME),
        PROMPTFOO_CACHE_PATH=str(PROMPTFOO_HOME / "cache"),
        PROMPTFOO_PYTHON=sys.executable,  # this venv: the provider imports the agent package
        PROMPTFOO_DISABLE_TEMPLATING="true",  # the prompt file is the system prompt, verbatim
        PROMPTFOO_DISABLE_TELEMETRY="1",
        PROMPTFOO_DISABLE_UPDATE="1",
        PROMPTFOO_DISABLE_SHARING="1",
    )
    return env


def promptfoo(*args: str, check: bool = True) -> int:
    """Run the pinned Promptfoo CLI in the foreground; returns its exit code."""
    if not PROMPTFOO_BIN.exists():
        raise EvalError(f"Promptfoo is not installed; run: npm ci --prefix {rel(EVALS_DIR)}")
    node = _node_version()
    if node is None or node < MIN_NODE:
        found = ".".join(map(str, node)) if node else "none"
        raise EvalError(
            f"Promptfoo needs Node >= {'.'.join(map(str, MIN_NODE))} (found {found});"
            " rebuild the devcontainer (it ships Node 24)"
        )
    PROMPTFOO_HOME.mkdir(parents=True, exist_ok=True)
    code = subprocess.run([str(PROMPTFOO_BIN), *args], env=promptfoo_env(), check=False).returncode
    if check and code != 0:
        raise EvalError(f"promptfoo {args[0]} exited with {code}")
    return code


def export_eval(eval_id: str, out: Path) -> dict[str, Any]:
    """Promptfoo's own export of one eval, read from its database: it carries the latest saved ratings."""
    out.parent.mkdir(parents=True, exist_ok=True)
    promptfoo("export", "eval", eval_id, "-o", str(out))
    return json.loads(out.read_text())
