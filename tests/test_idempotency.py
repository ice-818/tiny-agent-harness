
import pytest

from core.idempotency import (
    IdempotencyManager,
    IdempotencyConflictError,
)


def test_duplicate_call_executes_only_once():
    manager = IdempotencyManager()
    executions = []

    def create_order():
        executions.append("created")
        return {"order_id": 1001}

    first = manager.execute(
        run_id="run-001",
        tool_call_id="call-001",
        tool_name="create_order",
        arguments={"item": "book"},
        operation=create_order,
    )

    second = manager.execute(
        run_id="run-001",
        tool_call_id="call-001",
        tool_name="create_order",
        arguments={"item": "book"},
        operation=create_order,
    )

    assert first == {"order_id": 1001}
    assert second == first
    assert len(executions) == 1


def test_different_call_ids_execute_separately():
    manager = IdempotencyManager()
    executions = []

    def operation():
        executions.append(1)
        return len(executions)

    first = manager.execute(
        "run-001", "call-001", "counter", {}, operation
    )
    second = manager.execute(
        "run-001", "call-002", "counter", {}, operation
    )

    assert first == 1
    assert second == 2
    assert len(executions) == 2


def test_same_call_id_different_arguments_rejected():
    manager = IdempotencyManager()
    executions = []

    def operation():
        executions.append(1)
        return "done"

    manager.execute(
        "run-001", "call-001",
        "create_order", {"item": "book"}, operation
    )

    with pytest.raises(IdempotencyConflictError):
        manager.execute(
            "run-001", "call-001",
            "create_order", {"item": "phone"}, operation
        )

    assert len(executions) == 1


def test_same_call_id_different_tool_rejected():
    manager = IdempotencyManager()

    manager.execute(
        "run-001", "call-001", "tool_a", {},
        lambda: "A"
    )

    with pytest.raises(IdempotencyConflictError):
        manager.execute(
            "run-001", "call-001", "tool_b", {},
            lambda: "B"
        )


def test_different_run_ids_are_independent():
    manager = IdempotencyManager()
    executions = []

    def operation():
        executions.append(1)
        return len(executions)

    manager.execute(
        "run-001", "call-001", "counter", {}, operation
    )
    manager.execute(
        "run-002", "call-001", "counter", {}, operation
    )

    assert len(executions) == 2
