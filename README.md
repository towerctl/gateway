# towerctl/gateway

The API edge. Owns auth (API keys), the agent registry, run lifecycle, and
the OpenAPI contract every other component tests against.

- **Emits** `run.created` on the bus.
- **Consumes** nothing — the runner reports back via `PATCH /internal/runs/{id}`.
- Public API under `/v1/*` (`X-API-Key` from `TOWERCTL_API_KEYS`);
  internal API under `/internal/*` (`TOWERCTL_INTERNAL_KEYS`).

```bash
pip install -e .[dev]
TOWERCTL_API_KEYS=dev-key uvicorn gateway.main:app --port 8080
```

M0: in-memory storage, single process. M1: Postgres behind the same
handlers; the contract does not change. Export the spec:
`python -c "import json; from gateway.main import app; print(json.dumps(app.openapi()))"`.
