"""towerctl gateway: the API edge.

Owns: auth, agent registry, run lifecycle, the OpenAPI contract.
Emits: run.created. Consumes: nothing (runner reports back via /internal).

M0 storage is in-memory (single process). M1 swaps in Postgres behind the
same handlers — the API contract does not change.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException
from towerctl_core.bus import bus_from_env
from towerctl_core.events import RUN_CREATED, Event
from towerctl_core.models import AgentSpec, Run, RunCreate, RunStatus, RunUpdate

app = FastAPI(title="towerctl gateway", version="0.1.0")

bus = bus_from_env(group="gateway")
AGENTS: dict[str, AgentSpec] = {}
RUNS: dict[str, Run] = {}


def _keys(env: str) -> set[str]:
    return {k.strip() for k in os.environ.get(env, "dev-key").split(",") if k.strip()}


def require_api_key(x_api_key: str = Header(default="")) -> str:
    if x_api_key not in _keys("TOWERCTL_API_KEYS"):
        raise HTTPException(401, "invalid API key")
    return x_api_key


def require_internal_key(x_api_key: str = Header(default="")) -> str:
    if x_api_key not in _keys("TOWERCTL_INTERNAL_KEYS"):
        raise HTTPException(401, "invalid internal key")
    return x_api_key


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "agents": len(AGENTS), "runs": len(RUNS)}


# -- public API ------------------------------------------------------------- #

@app.post("/v1/agents", response_model=AgentSpec, dependencies=[Depends(require_api_key)])
def create_agent(spec: AgentSpec) -> AgentSpec:
    AGENTS[spec.id] = spec
    return spec


@app.get("/v1/agents", response_model=list[AgentSpec], dependencies=[Depends(require_api_key)])
def list_agents() -> list[AgentSpec]:
    return list(AGENTS.values())


@app.post("/v1/runs", response_model=Run, dependencies=[Depends(require_api_key)])
def create_run(req: RunCreate) -> Run:
    if req.agent_id not in AGENTS:
        raise HTTPException(404, f"unknown agent {req.agent_id}")
    run = Run(agent_id=req.agent_id, input=req.input, metadata=req.metadata)
    RUNS[run.id] = run
    bus.publish(
        Event(topic=RUN_CREATED, payload={"run_id": run.id, "agent_id": run.agent_id})
    )
    return run


@app.get("/v1/runs", response_model=list[Run], dependencies=[Depends(require_api_key)])
def list_runs() -> list[Run]:
    return sorted(RUNS.values(), key=lambda r: r.created_at, reverse=True)


@app.get("/v1/runs/{run_id}", response_model=Run, dependencies=[Depends(require_api_key)])
def get_run(run_id: str) -> Run:
    if run_id not in RUNS:
        raise HTTPException(404, "no such run")
    return RUNS[run_id]


# -- internal API (runner only) ---------------------------------------------- #

@app.patch(
    "/internal/runs/{run_id}", response_model=Run, dependencies=[Depends(require_internal_key)]
)
def update_run(run_id: str, upd: RunUpdate) -> Run:
    if run_id not in RUNS:
        raise HTTPException(404, "no such run")
    run = RUNS[run_id]
    data = run.model_dump()
    data.update(upd.model_dump(exclude_none=True))
    run = Run(**data)
    if upd.status in (RunStatus.SUCCEEDED, RunStatus.FAILED) and run.finished_at is None:
        run.finished_at = datetime.now(timezone.utc)
    RUNS[run_id] = run
    return run
