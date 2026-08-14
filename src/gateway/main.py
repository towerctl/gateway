"""towerctl gateway: the API edge.

Owns: auth, agent registry, run lifecycle, the OpenAPI contract.
Emits: run.created. Consumes: nothing (runner reports back via /internal).

Storage: MemoryStore by default; PostgresStore when DATABASE_URL is set (M1).
The API contract is identical either way — see gateway/store.py.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException
from towerctl_core.bus import bus_from_env
from towerctl_core.events import RUN_CREATED, Event
from towerctl_core.models import AgentSpec, Run, RunCreate, RunStatus, RunUpdate

from gateway.store import store_from_env

app = FastAPI(title="towerctl gateway", version="0.2.0")

bus = bus_from_env(group="gateway")
store = store_from_env()


def _keys(env: str) -> set[str]:
    return {k.strip() for k in os.environ.get(env, "dev-key").split(",") if k.strip()}


def require_api_key(x_api_key: str = Header(default="")) -> str:
    # internal keys are a superset: the runner reads public endpoints too
    if x_api_key not in (_keys("TOWERCTL_API_KEYS") | _keys("TOWERCTL_INTERNAL_KEYS")):
        raise HTTPException(401, "invalid API key")
    return x_api_key


def require_internal_key(x_api_key: str = Header(default="")) -> str:
    if x_api_key not in _keys("TOWERCTL_INTERNAL_KEYS"):
        raise HTTPException(401, "invalid internal key")
    return x_api_key


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, **store.counts(), "storage": type(store).__name__}


# -- public API ------------------------------------------------------------- #

@app.post("/v1/agents", response_model=AgentSpec, dependencies=[Depends(require_api_key)])
def create_agent(spec: AgentSpec) -> AgentSpec:
    store.put_agent(spec)
    return spec


@app.get("/v1/agents", response_model=list[AgentSpec], dependencies=[Depends(require_api_key)])
def list_agents() -> list[AgentSpec]:
    return store.list_agents()


@app.post("/v1/runs", response_model=Run, dependencies=[Depends(require_api_key)])
def create_run(req: RunCreate) -> Run:
    if store.get_agent(req.agent_id) is None:
        raise HTTPException(404, f"unknown agent {req.agent_id}")
    run = Run(agent_id=req.agent_id, input=req.input, metadata=req.metadata)
    store.put_run(run)
    bus.publish(
        Event(topic=RUN_CREATED, payload={"run_id": run.id, "agent_id": run.agent_id})
    )
    return run


@app.get("/v1/runs", response_model=list[Run], dependencies=[Depends(require_api_key)])
def list_runs() -> list[Run]:
    return store.list_runs()


@app.get("/v1/runs/{run_id}", response_model=Run, dependencies=[Depends(require_api_key)])
def get_run(run_id: str) -> Run:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    return run


# -- internal API (runner only) ---------------------------------------------- #

@app.patch(
    "/internal/runs/{run_id}", response_model=Run, dependencies=[Depends(require_internal_key)]
)
def update_run(run_id: str, upd: RunUpdate) -> Run:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    data = run.model_dump()
    data.update(upd.model_dump(exclude_none=True))
    run = Run(**data)
    if upd.status in (RunStatus.SUCCEEDED, RunStatus.FAILED) and run.finished_at is None:
        run.finished_at = datetime.now(timezone.utc)
    store.put_run(run)
    return run
