
from core import loop


def test_agent_loop_handles_checkpoint_read_failure(monkeypatch):
    """Agent should fail safely if checkpoint reading raises."""

    events = []

    class FakeMemoryManager:
        def get_checkpoint(self, session_id):
            raise OSError("Simulated checkpoint read failure")

    def mock_log_event(**kwargs):
        events.append(kwargs)

    def mock_chat(messages, **kwargs):
        raise AssertionError(
            "LLM must not be called when checkpoint recovery fails"
        )

    monkeypatch.setattr(loop, "MemoryManager", FakeMemoryManager)
    monkeypatch.setattr(loop, "log_event", mock_log_event)
    monkeypatch.setattr(loop.router, "chat", mock_chat)

    result = loop.run(
        task="Resume interrupted task",
        run_id="resume-read-failure-001",
        max_steps=5
    )

    assert result == (
        "Agent failed: checkpoint recovery error (OSError)"
    )

    failure_events = [
        event for event in events
        if event["event"] == "agent_failed"
    ]

    assert len(failure_events) == 1
    assert failure_events[0]["stage"] == "checkpoint_recovery"
    assert failure_events[0]["error_type"] == "OSError"
    assert failure_events[0]["duration_ms"] >= 0

    assert not any(
        event["event"] == "agent_finish"
        for event in events
    )
