import json

from core.trace import create_run_id, log_event


def test_create_run_id_unique():
    run_id_1 = create_run_id()
    run_id_2 = create_run_id()

    assert isinstance(run_id_1, str)
    assert isinstance(run_id_2, str)
    assert len(run_id_1) == 32
    assert run_id_1 != run_id_2


def test_log_event(caplog):
    with caplog.at_level(
            "INFO",
            logger="tiny_agent_harness"
    ):
        log_event(
            run_id="test_run_001",
            step=1,
            event="tool_result",
            tool_name="calculator",
            duration_ms=2.5
        )

    records = [
        record
        for record in caplog.records
        if record.name == "tiny_agent_harness"
    ]

    assert len(records) == 1

    data = json.loads(records[0].message)

    assert data["run_id"] == "test_run_001"
    assert data["step"] == 1
    assert data["event"] == "tool_result"
    assert data["tool_name"] == "calculator"
    assert data["duration_ms"] == 2.5
    assert isinstance(data["timestamp"], (int, float))