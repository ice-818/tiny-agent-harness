import copy

import pytest


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

import api
from core import loop
from core.idempotency import IdempotencyManager


def test_api_starts_and_reads_a_completed_run(monkeypatch):
    checkpoints = {}
    responses = [
        {
            "type": "tool_call",
            "tool_call_id": "api-call-001",
            "tool_name": "calculator",
            "arguments": {"a": 25, "b": 8, "op": "mul"},
        },
        {"type": "final", "content": "200"},
    ]

    class FakeMemoryManager:
        def get_checkpoint(self, session_id):
            return copy.deepcopy(checkpoints.get(session_id))

        def save_checkpoint(self, session_id, step, context):
            checkpoints[session_id] = {
                "step": step,
                "context": copy.deepcopy(context),
            }

    monkeypatch.setattr(loop, "MemoryManager", FakeMemoryManager)
    monkeypatch.setattr(api, "MemoryManager", FakeMemoryManager)
    monkeypatch.setattr(loop, "idempotency_manager", IdempotencyManager())
    monkeypatch.setattr(loop.router, "chat", lambda messages, **kwargs: responses.pop(0))

    with TestClient(api.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["version"] == "1.0.0"

        started = client.post(
            "/runs",
            json={
                "run_id": "api-run-001",
                "task": "calculate 25 times 8",
                "max_steps": 3,
            },
        )
        assert started.status_code == 200
        assert started.json()["run_id"] == "api-run-001"
        assert started.json()["status"] == "completed"
        assert started.json()["result"] == "200"

        state = client.get("/runs/api-run-001")
        assert state.status_code == 200
        assert state.json()["status"] == "completed"

        duplicate = client.post(
            "/runs",
            json={
                "run_id": "api-run-001",
                "task": "calculate 25 times 8",
            },
        )
        assert duplicate.status_code == 409
