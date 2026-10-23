"""Shared fixtures: a throwaway Postgres cluster (pytest-postgresql) and a migrated DB per test.

DB tests need the PostgreSQL server binaries. In the devcontainer they live off PATH in
/usr/lib/postgresql/<ver>/bin; without them the DB tests skip rather than fail.
"""

from __future__ import annotations

import glob
import shutil
import uuid

import psycopg
from psycopg import sql
import pytest
from pytest_postgresql import factories

from agent import db

_PG_CTL = shutil.which("pg_ctl") or next(
    iter(sorted(glob.glob("/usr/lib/postgresql/*/bin/pg_ctl"), reverse=True)), None
)

postgresql_proc = factories.postgresql_proc(executable=_PG_CTL) if _PG_CTL else None


if _PG_CTL:

    @pytest.fixture
    async def conn(postgresql_proc):
        """A fresh, migrated database per test."""
        proc = postgresql_proc
        name = f"t_{uuid.uuid4().hex[:12]}"
        base = f"host={proc.host} port={proc.port} user={proc.user} dbname=postgres"
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        connection = await db.connect(f"host={proc.host} port={proc.port} user={proc.user} dbname={name}")
        await db.migrate(connection)
        try:
            yield connection
        finally:
            await connection.close()

else:

    @pytest.fixture
    async def conn():
        pytest.skip("PostgreSQL server binaries (pg_ctl) not found")
