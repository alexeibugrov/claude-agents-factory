# upwork-scout image. Build context is this directory (agents/<name>/), never the repo root:
# agents are self-contained, so an unrelated agent's files can neither enter this image nor
# invalidate its build cache.
#
# The claude-agent-sdk wheel bundles a self-contained per-arch `claude` CLI, so there is no Node
# layer here. Auth is the owner's Claude SUBSCRIPTION via CLAUDE_CODE_OAUTH_TOKEN (supplied at
# runtime from the VM's .env file); ANTHROPIC_API_KEY stays UNSET.
FROM python:3.12-slim

# uv resolves and installs from the committed uv.lock, so the image is reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /usr/local/bin/

# ca-certificates for the bundled CLI's HTTPS to Anthropic; libstdc++ for its dynamic deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Non-root with a writable HOME: the bundled CLI writes session/cache state into ~/.claude even
# when auth comes from the token. Fixed uid/gid so the operator can chown the VM's bind-mount
# deterministically.
RUN groupadd -r -g 10001 appuser && useradd -r -u 10001 -g appuser -m -d /home/appuser appuser

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Dependencies first, as their own layer: source edits then rebuild in seconds.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY agent/ ./agent/
RUN uv sync --locked --no-dev

# Fail the BUILD, not the first live request, if the bundled CLI is missing from the wheel or the
# package does not import.
RUN /app/.venv/bin/python -c "import os, claude_agent_sdk as s; p=os.path.join(os.path.dirname(s.__file__),'_bundled','claude'); assert os.path.exists(p), 'bundled claude CLI missing from wheel'; print('bundled CLI:', p)" \
    && /app/.venv/bin/python -c "import agent.main; print('agent.main import OK')"

RUN chown -R appuser:appuser /app

USER appuser

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HOME=/home/appuser

CMD ["python", "-u", "-m", "agent.main"]
