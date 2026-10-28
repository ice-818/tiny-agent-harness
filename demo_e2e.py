"""Offline end-to-end demonstration of the FastAPI runtime.

This demo replaces only the LLM and checkpoint storage in memory. It does not
need an API key, Ollama, or Redis, but it exercises the real HTTP endpoints,
agent loop, guardrail, calculator tool, and checkpoint shape.
"""

import copy

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError as error:
    raise SystemExit(
        "FastAPI is not installed. Run: python -m pip install -r requirements.txt"
    ) from error

import api
from core import loop
from core.idempotency import IdempotencyManager


class DemoMemoryManager:
    checkpoints = {}

    def get_checkpoint(self, session_id):
        checkpoint = self.checkpoints.get(session_id)
        return copy.deepcopy(checkpoint)

    def save_checkpoint(self, session_id, step, context):
        self.checkpoints[session_id] = {
            "step": step,
            "context": copy.deepcopy(context),
        }


def main():
    responses = [
        {
            "type": "tool_call",
            "tool_call_id": "demo_call_001",
            "tool_name": "calculator",
            "arguments": {"a": 25, "b": 8, "op": "mul"},
        },
        {"type": "final", "content": "25 × 8 = 200"},
    ]

    def scripted_chat(messages, **kwargs):
        return responses.pop(0)

    original_chat = loop.router.chat
    original_memory = loop.MemoryManager
    original_api_memory = api.MemoryManager
    original_idempotency = loop.idempotency_manager
    DemoMemoryManager.checkpoints = {}

    try:
        loop.router.chat = scripted_chat
        loop.MemoryManager = DemoMemoryManager
        api.MemoryManager = DemoMemoryManager
        loop.idempotency_manager = IdempotencyManager()

        with TestClient(api.app) as client:
            started = client.post(
                "/runs",
                json={
                    "run_id": "demo-run-001",
                    "task": "请计算 25 乘以 8",
                    "max_steps": 3,
                },
            )
            started.raise_for_status()
            print("POST /runs")
            print(started.json())

            state = client.get("/runs/demo-run-001")
            state.raise_for_status()
            print("GET /runs/demo-run-001")
            print(state.json())
    finally:
        loop.router.chat = original_chat
        loop.MemoryManager = original_memory
        api.MemoryManager = original_api_memory
        loop.idempotency_manager = original_idempotency


if __name__ == "__main__":
    main()
