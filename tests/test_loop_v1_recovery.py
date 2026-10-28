import redis
import copy

from core import loop
from core.idempotency import IdempotencyManager, PersistentIdempotencyManager


class OfflineRedis:
    @staticmethod
    def _offline(*args, **kwargs):
        raise redis.exceptions.ConnectionError("Redis unavailable")

    set = _offline
    get = _offline
    scan_iter = _offline


def test_loop_recovers_completed_tool_observation_without_checkpoint(
        monkeypatch,
        tmp_path,
):
    run_id = "recovery-run-001"
    messages_before_tool_result = [
        {"role": "user", "content": "Calculate 25 times 8"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-001",
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "arguments": '{"a": 25, "b": 8, "op": "mul"}',
                    },
                }
            ],
        },
    ]
    initial_manager = PersistentIdempotencyManager(
        client=OfflineRedis(),
        fallback_dir=tmp_path,
    )
    initial_manager.execute(
        run_id=run_id,
        tool_call_id="call-001",
        tool_name="calculator",
        arguments={"a": 25, "b": 8, "op": "mul"},
        operation=lambda: {
            "success": True,
            "result": 200,
            "error": None,
            "error_type": None,
        },
        recovery={"step": 1, "messages": messages_before_tool_result},
    )

    saved_checkpoints = []

    class MissingCheckpointMemory:
        def get_checkpoint(self, session_id):
            assert session_id == run_id
            return None

        def save_checkpoint(self, session_id, step, context):
            saved_checkpoints.append({
                "session_id": session_id,
                "step": step,
                "context": context,
            })

    captured = {}

    def final_response(messages, **kwargs):
        captured["messages"] = copy.deepcopy(messages)
        captured["step"] = kwargs["step"]
        return {"type": "final", "content": "25 times 8 is 200"}

    monkeypatch.setattr(loop, "MemoryManager", MissingCheckpointMemory)
    monkeypatch.setattr(loop.router, "chat", final_response)
    monkeypatch.setattr(
        loop,
        "idempotency_manager",
        PersistentIdempotencyManager(
            client=OfflineRedis(),
            fallback_dir=tmp_path,
        ),
    )

    result = loop.run(
        task="ignored after recovery",
        max_steps=3,
        run_id=run_id,
        resume=True,
    )

    assert result == "25 times 8 is 200"
    assert captured["step"] == 2
    assert captured["messages"][-1]["role"] == "tool"
    assert "200" in captured["messages"][-1]["content"]
    assert saved_checkpoints[0]["context"]["status"] == "running"
    assert saved_checkpoints[-1]["context"]["status"] == "completed"


def test_loop_reports_an_idempotency_conflict(monkeypatch):
    manager = IdempotencyManager()
    manager.execute(
        run_id="loop-conflict-001",
        tool_call_id="call-001",
        tool_name="calculator",
        arguments={"a": 1, "b": 2, "op": "add"},
        operation=lambda: {"success": True},
    )

    events = []

    class FakeMemoryManager:
        def save_checkpoint(self, session_id, step, context):
            pass

    def repeated_call(messages, **kwargs):
        return {
            "type": "tool_call",
            "tool_call_id": "call-001",
            "tool_name": "calculator",
            "arguments": {"a": 9, "b": 9, "op": "mul"},
        }

    monkeypatch.setattr(loop, "MemoryManager", FakeMemoryManager)
    monkeypatch.setattr(loop.router, "chat", repeated_call)
    monkeypatch.setattr(loop, "idempotency_manager", manager)
    monkeypatch.setattr(loop, "log_event", lambda **kwargs: events.append(kwargs))

    result = loop.run(
        task="conflicting call",
        max_steps=1,
        run_id="loop-conflict-001",
        resume=False,
    )

    assert result == "Agent failed: idempotency conflict"
    assert any(
        event["stage"] == "idempotency_conflict"
        for event in events
        if event["event"] == "agent_failed"
    )


def test_tool_exception_is_journaled_as_unknown_for_safe_resume(
        monkeypatch,
        tmp_path,
):
    run_id = "unknown-loop-run-001"
    manager = PersistentIdempotencyManager(
        client=OfflineRedis(),
        fallback_dir=tmp_path,
    )

    class FakeMemoryManager:
        def __init__(self):
            self.saved = []

        def get_checkpoint(self, session_id):
            return None

        def save_checkpoint(self, session_id, step, context):
            self.saved.append((step, context))

    memory = FakeMemoryManager()

    monkeypatch.setattr(loop, "MemoryManager", lambda: memory)
    monkeypatch.setattr(loop, "idempotency_manager", manager)
    monkeypatch.setattr(
        loop.router,
        "chat",
        lambda messages, **kwargs: {
            "type": "tool_call",
            "tool_call_id": "call-001",
            "tool_name": "calculator",
            "arguments": {"a": 25, "b": 8, "op": "mul"},
        },
    )
    monkeypatch.setattr(
        loop,
        "execute_tool",
        lambda tool_name, arguments: (_ for _ in ()).throw(
            RuntimeError("tool process disappeared")
        ),
    )

    first_result = loop.run(
        task="calculate",
        max_steps=2,
        run_id=run_id,
        resume=False,
    )

    assert first_result == "Agent failed: tool execution error (RuntimeError)"
    assert manager.get_recovery(run_id)["status"] == "UNKNOWN"

    def no_llm_call(*args, **kwargs):
        pytest.fail("UNKNOWN recovery must stop before another model call")

    monkeypatch.setattr(loop.router, "chat", no_llm_call)
    resumed_result = loop.run(
        task="calculate",
        max_steps=2,
        run_id=run_id,
        resume=True,
    )

    assert resumed_result == (
        "Agent stopped: tool execution state unknown; "
        "manual reconciliation required"
    )
    assert memory.saved[-1][1]["status"] == "needs_manual_reconciliation"
