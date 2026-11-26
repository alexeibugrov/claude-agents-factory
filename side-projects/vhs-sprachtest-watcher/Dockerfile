FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /usr/local/bin/

# Fixed uid so the VM's ./data bind mount can be chowned deterministically.
RUN groupadd -r -g 10001 appuser && useradd -r -u 10001 -g appuser -m -d /home/appuser appuser

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY watcher/ ./watcher/
RUN /app/.venv/bin/python -c "import watcher.main" && chown -R appuser:appuser /app

USER appuser

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

CMD ["python", "-m", "watcher", "run"]
