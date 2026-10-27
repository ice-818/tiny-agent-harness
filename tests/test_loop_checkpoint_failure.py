
from core import loop
from core.memory import CheckpointConflictError


def test_agent_loop_handles_checkpoint_conflict(monkeypatch):
    """Agent should fail safely on checkpoint version conflict."""

    events = []

    class FakeMemoryManager:
        def save_checkpoint(self, session_id, step, context):
            raise CheckpointConflictError(
                "Simulated checkpoint version conflict"
            )

    def mock_chat(messages, **kwargs):
        return {
            "type": "final",
            "content": "Task completed"
        }

    def mock_log_event(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(loop, "MemoryManager", FakeMemoryManager)
    monkeypatch.setattr(loop.router, "chat", mock_chat)
    monkeypatch.setattr(loop, "log_event", mock_log_event)

    result = loop.run(
        task="Test checkpoint conflict",
        max_steps=2
    )

    assert result == (
        "Agent failed: checkpoint save error "
        "(CheckpointConflictError)"
    )

    failure_events = [
        event for event in events
        if event["event"] == "agent_failed"
    ]

    assert len(failure_events) == 1
    assert failure_events[0]["stage"] == "checkpoint_save"
    assert failure_events[0]["error_type"] == "CheckpointConflictError"
    assert failure_events[0]["step"] == 1
    assert failure_events[0]["duration_ms"] >= 0

    assert not any(
        event["event"] == "agent_finish"
        for event in events
    )
