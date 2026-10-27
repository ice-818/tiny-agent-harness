
from core import loop


def test_agent_loop_handles_tool_executor_exception(monkeypatch):
    """Agent should fail safely when the tool executor raises."""

    events = []

    class FakeMemoryManager:
        def save_checkpoint(self, session_id, step, context):
            pass

    def mock_chat(messages, **kwargs):
        return {
            "type": "tool_call",
            "tool_call_id": "call_failure_001",
            "tool_name": "calculator",
            "arguments": {
                "a": 25,
                "b": 8,
                "op": "mul"
            }
        }

    def mock_execute_tool(tool_name, arguments):
        raise RuntimeError("Simulated tool executor failure")

    def mock_log_event(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(loop, "MemoryManager", FakeMemoryManager)
    monkeypatch.setattr(loop.router, "chat", mock_chat)
    monkeypatch.setattr(loop, "execute_tool", mock_execute_tool)
    monkeypatch.setattr(loop, "log_event", mock_log_event)

    result = loop.run(
        task="Calculate 25 times 8",
        max_steps=2
    )

    assert result == "Agent failed: tool execution error (RuntimeError)"

    failure_events = [
        event for event in events
        if event["event"] == "agent_failed"
    ]

    assert len(failure_events) == 1
    assert failure_events[0]["stage"] == "tool_execution"
    assert failure_events[0]["error_type"] == "RuntimeError"
    assert failure_events[0]["step"] == 1
    assert failure_events[0]["duration_ms"] >= 0
