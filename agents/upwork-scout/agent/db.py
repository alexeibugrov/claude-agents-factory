"""Postgres connection and the forward-only migration runner.

Migrations are plain SQL files in ``agent/migrations/``, applied in name order at startup under a
session advisory lock and recorded in ``schema_migrations``. A bad migration is fixed with a new
one, never by editing an applied file.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import LiteralString, cast

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import DictRow, dict_row

from agent.config import DbConfig

logger = logging.getLogger(__name__)

# Every connection in this agent returns rows as dicts.
Conn = psycopg.AsyncConnection[DictRow]

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_LOCK_ID = 0x75707363  # arbitrary, stable: "upsc"


def conninfo(db: DbConfig) -> str:
    """DATABASE_URL wins (local runs); otherwise settings.db plus POSTGRES_PASSWORD from the env."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    return make_conninfo(
        host=db.host,
        port=db.port,
        dbname=db.name,
        user=db.user,
        password=os.environ.get("POSTGRES_PASSWORD", ""),
    )


async def connect(dsn: str) -> Conn:
    return await Conn.connect(dsn, row_factory=dict_row, autocommit=True)


async def migrate(conn: Conn) -> list[str]:
    """Apply every migration not yet recorded; return the names applied this time."""
    applied_now: list[str] = []
    await conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_ID,))
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        cur = await conn.execute("SELECT name FROM schema_migrations")
        done = {row["name"] for row in await cur.fetchall()}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            async with conn.transaction():
                # Trusted SQL shipped in the image, not user input.
                await conn.execute(cast(LiteralString, path.read_text()))
                await conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied_now.append(path.name)
            logger.info("migration applied: %s", path.name)
    finally:
        await conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_ID,))
    return applied_now
