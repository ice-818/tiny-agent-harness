# V1.0 deployment notes

## Prerequisites

- Windows 10/11 or another supported Python 3.10+ host.
- Python virtual environment with `pip install -r requirements.txt`.
- Redis 7+ is recommended for multi-process checkpoint and idempotency
  coordination. The runtime remains available during a Redis outage by writing
  atomic local files under `TINY_AGENT_DATA_DIR`.
- An Ollama-compatible local model for the default `chat` route, or a valid
  `DASHSCOPE_API_KEY` when the cloud reasoning route is selected.

Copy `.env.example` to `.env` and set the storage and model values for the
environment. Never commit `.env` or the `data/` recovery directory.

## Run the service

From the repository root in PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the generated OpenAPI interface. Put a
reverse proxy with TLS and authentication in front of the service before
exposing it outside the machine. The V1.0 API intentionally does not provide
authentication, tenant isolation, rate limiting, or a background job queue.

## Data and recovery behaviour

- Redis keys expire after one hour. The local fallback directory retains a
  recovery copy; define backup and retention policies appropriate for the
  data handled by tools.
- `COMPLETED` tool calls return their stored observation after a process
  restart and are not executed again.
- `IN_PROGRESS` calls return a retry-later response so concurrent workers do
  not duplicate the call.
- `UNKNOWN` means the process cannot prove whether an external side effect
  happened. The run is stored as `needs_manual_reconciliation` and must be
  reviewed before any retry or compensating action.

For side-effecting production tools, store an external business idempotency
key too. The harness protects its own call boundary, but it cannot prove what
an external system did after a network or process failure.

## Release checks

```powershell
python -m pytest -q
python demo_e2e.py
Invoke-RestMethod http://127.0.0.1:8000/health
```

Run the first two checks before deployment; the demo does not call a real
model, Redis server, or cloud API.
