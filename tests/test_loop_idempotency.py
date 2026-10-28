
from core import loop
from core.idempotency import IdempotencyManager


def test_agent_loop_deduplicates_tool_calls(monkeypatch):
    """The same tool call must execute only once."""

    executions = []
    events = []
    llm_calls = 0

    class FakeMemoryManager:
        def save_checkpoint(self, session_id, step, context):
            pass

    def fake_chat(messages, **kwargs):
        nonlocal llm_calls
        llm_calls += 1

        if llm_calls <= 2:
            return {
                "type": "tool_call",
                "tool_name": "calculator",
                "arguments": {"a": 25, "b": 8},
                "tool_call_id": "same-call-id",
            }

        return {
            "type": "final",
            "content": "200",
        }

    def fake_execute_tool(tool_name, arguments):
        executions.append((tool_name, arguments))
        return {
            "success": True,
            "result": 200,
            "error": None,
            "error_type": None,
        }

    monkeypatch.setattr(loop, "MemoryManager", FakeMemoryManager)
    monkeypatch.setattr(loop.router, "chat", fake_chat)
    monkeypatch.setattr(loop, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(loop, "log_event", lambda **kwargs: events.append(kwargs))

    # Isolate the test from the global manager's existing cache.
    monkeypatch.setattr(
        loop,
        "idempotency_manager",
        IdempotencyManager(),
    )

    result = loop.run(
        task="Calculate 25 times 8",
        max_steps=5,
    )

    assert result == "200"
    assert llm_calls == 3

    # The key assertion: the tool ran only once.
    assert len(executions) == 1

    assert any(
        event["event"] == "agent_finish"
        for event in events
    )

