from fastapi.testclient import TestClient

from gateway.main import AGENTS, RUNS, app, bus

PUB = {"X-API-Key": "dev-key"}
INT = {"X-API-Key": "internal-key"}


def setup_function():
    AGENTS.clear()
    RUNS.clear()


def test_auth_required():
    c = TestClient(app)
    assert c.get("/v1/agents").status_code == 401
    assert c.get("/v1/agents", headers=PUB).status_code == 200


def test_run_lifecycle(monkeypatch):
    monkeypatch.setenv("TOWERCTL_INTERNAL_KEYS", "internal-key")
    c = TestClient(app)

    agent = c.post("/v1/agents", json={"name": "echo-1", "kind": "echo"}, headers=PUB).json()
    run = c.post(
        "/v1/runs", json={"agent_id": agent["id"], "input": "hello", "metadata": {}}, headers=PUB
    ).json()
    assert run["status"] == "queued"
    assert bus.history[-1].topic == "run.created"
    assert bus.history[-1].payload["run_id"] == run["id"]

    upd = c.patch(
        f"/internal/runs/{run['id']}",
        json={"status": "succeeded", "output": "hello", "tokens_in": 1, "tokens_out": 1},
        headers=INT,
    )
    assert upd.status_code == 200
    got = c.get(f"/v1/runs/{run['id']}", headers=PUB).json()
    assert got["status"] == "succeeded"
    assert got["output"] == "hello"
    assert got["finished_at"] is not None


def test_internal_needs_internal_key(monkeypatch):
    monkeypatch.setenv("TOWERCTL_INTERNAL_KEYS", "internal-key")
    c = TestClient(app)
    agent = c.post("/v1/agents", json={"name": "a", "kind": "echo"}, headers=PUB).json()
    run = c.post(
        "/v1/runs", json={"agent_id": agent["id"], "input": "x", "metadata": {}}, headers=PUB
    ).json()
    r = c.patch(f"/internal/runs/{run['id']}", json={"status": "running"}, headers=PUB)
    assert r.status_code == 401


def test_unknown_agent_404():
    c = TestClient(app)
    r = c.post("/v1/runs", json={"agent_id": "agt_nope", "input": "x", "metadata": {}}, headers=PUB)
    assert r.status_code == 404
