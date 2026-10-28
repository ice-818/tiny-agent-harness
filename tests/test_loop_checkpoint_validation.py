
import pytest

from core import loop


@pytest.mark.parametrize(
    "checkpoint",
    [
        {"step": 2},
        {
            "step": 2,
            "context": {"status": "running"}
        },
        {
            "step": "abc",
            "context": {
                "status": "running",
                "messages": [{"role": "user", "content": "hello"}]
            }
        },
        {
            "step": 2,
            "context": {
                "status": "running",
                "messages": "hello"
            }
        }
    ]
)
def test_invalid_checkpoint_fails_safely(monkeypatch, checkpoint):
    events = []

    class FakeMemoryManager:
        def get_checkpoint(self, session_id):
            return checkpoint

    def mock_log_event(**kwargs):
        events.append(kwargs)

    def mock_chat(messages, **kwargs):
        raise AssertionError(
            "LLM must not be called for invalid checkpoints"
        )

    monkeypatch.setattr(loop, "MemoryManager", FakeMemoryManager)
    monkeypatch.setattr(loop, "log_event", mock_log_event)
    monkeypatch.setattr(loop.router, "chat", mock_chat)

    result = loop.run(
        task="resume task",
        run_id="invalid-checkpoint-test",
        max_steps=5
    )

    assert result == (
        "Agent failed: invalid checkpoint (InvalidCheckpointError)"
    )

    failure_events = [
        event for event in events
        if event["event"] == "agent_failed"
    ]

    assert len(failure_events) == 1
    assert failure_events[0]["stage"] == "checkpoint_validation"
    assert failure_events[0]["error_type"] == "InvalidCheckpointError"

    assert not any(
        event["event"] == "agent_finish"
        for event in events
    )
