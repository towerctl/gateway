"""Run/agent storage. The API contract never changes; only the store does.

MemoryStore  — default; used by tests and keyless local runs.
PostgresStore — used when DATABASE_URL is set. Two JSONB tables, pydantic
models serialized whole: minimal schema surface, durable runs (M1). A
column-per-field schema is an M2+ decision if querying needs it (ADR then).
"""

from __future__ import annotations

import os

from towerctl_core.models import AgentSpec, Run


class MemoryStore:
    def __init__(self) -> None:
        self._agents: dict[str, AgentSpec] = {}
        self._runs: dict[str, Run] = {}

    # agents
    def put_agent(self, a: AgentSpec) -> None:
        self._agents[a.id] = a

    def get_agent(self, agent_id: str) -> AgentSpec | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[AgentSpec]:
        return list(self._agents.values())

    # runs
    def put_run(self, r: Run) -> None:
        self._runs[r.id] = r

    def get_run(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[Run]:
        return sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)

    def counts(self) -> dict:
        return {"agents": len(self._agents), "runs": len(self._runs)}


class PostgresStore:
    """psycopg3, sync, tiny pool. Tables auto-created at startup."""

    def __init__(self, dsn: str) -> None:
        from psycopg_pool import ConnectionPool

        self._pool = ConnectionPool(dsn, min_size=1, max_size=4, open=True)
        with self._pool.connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, data JSONB NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, data JSONB NOT NULL, "
                "created_at TIMESTAMPTZ NOT NULL)"
            )

    def put_agent(self, a: AgentSpec) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO agents (id, data) VALUES (%s, %s) "
                "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",
                (a.id, a.model_dump_json()),
            )

    def get_agent(self, agent_id: str) -> AgentSpec | None:
        with self._pool.connection() as conn:
            row = conn.execute("SELECT data FROM agents WHERE id = %s", (agent_id,)).fetchone()
        return AgentSpec.model_validate(row[0]) if row else None

    def list_agents(self) -> list[AgentSpec]:
        with self._pool.connection() as conn:
            rows = conn.execute("SELECT data FROM agents").fetchall()
        return [AgentSpec.model_validate(r[0]) for r in rows]

    def put_run(self, r: Run) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO runs (id, data, created_at) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",
                (r.id, r.model_dump_json(), r.created_at),
            )

    def get_run(self, run_id: str) -> Run | None:
        with self._pool.connection() as conn:
            row = conn.execute("SELECT data FROM runs WHERE id = %s", (run_id,)).fetchone()
        return Run.model_validate(row[0]) if row else None

    def list_runs(self) -> list[Run]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT data FROM runs ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
        return [Run.model_validate(r[0]) for r in rows]

    def counts(self) -> dict:
        with self._pool.connection() as conn:
            a = conn.execute("SELECT count(*) FROM agents").fetchone()[0]
            r = conn.execute("SELECT count(*) FROM runs").fetchone()[0]
        return {"agents": a, "runs": r}


def store_from_env():
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        return PostgresStore(dsn)
    return MemoryStore()
