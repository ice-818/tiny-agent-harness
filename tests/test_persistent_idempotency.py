import pytest
import redis
from fnmatch import fnmatch

from core.idempotency import (
    IdempotencyConflictError,
    IdempotencyUnknownError,
    PersistentIdempotencyManager,
)


class OfflineRedis:
    """Force the manager to exercise its durable local fallback."""

    @staticmethod
    def _offline(*args, **kwargs):
        raise redis.exceptions.ConnectionError("Redis unavailable")

    set = _offline
    get = _offline
    scan_iter = _offline


class InMemoryRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, nx=False, xx=False, ex=None):
        exists = key in self.values
        if nx and exists:
            return False
        if xx and not exists:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def scan_iter(self, match=None):
        for key in self.values:
            if match is None or fnmatch(key, match):
                yield key


def test_completed_call_is_replayed_after_manager_restart(tmp_path):
    executions = []
    recovery = {
        "step": 1,
        "messages": [{"role": "user", "content": "create an order"}],
    }

    first_manager = PersistentIdempotencyManager(
        client=OfflineRedis(),
        fallback_dir=tmp_path,
    )
    first = first_manager.execute(
        run_id="persist-run-001",
        tool_call_id="call-001",
        tool_name="create_order",
        arguments={"item": "book"},
        operation=lambda: executions.append("created") or {"order_id": 1001},
        recovery=recovery,
    )

    second_manager = PersistentIdempotencyManager(
        client=OfflineRedis(),
        fallback_dir=tmp_path,
    )
    second = second_manager.execute(
        run_id="persist-run-001",
        tool_call_id="call-001",
        tool_name="create_order",
        arguments={"item": "book"},
        operation=lambda: executions.append("duplicated") or {"order_id": 1002},
        recovery=recovery,
    )

    assert first == {"order_id": 1001}
    assert second == first
    assert executions == ["created"]

    journal = second_manager.get_recovery("persist-run-001")
    assert journal["status"] == "COMPLETED"
    assert journal["result"] == {"order_id": 1001}


def test_unknown_outcome_is_never_retried_after_restart(tmp_path):
    manager = PersistentIdempotencyManager(
        client=OfflineRedis(),
        fallback_dir=tmp_path,
    )
    recovery = {
        "step": 1,
        "messages": [{"role": "user", "content": "charge a card"}],
    }

    def uncertain_operation():
        raise RuntimeError("connection dropped after request was sent")

    with pytest.raises(RuntimeError):
        manager.execute(
            run_id="unknown-run-001",
            tool_call_id="call-001",
            tool_name="charge_card",
            arguments={"amount": 100},
            operation=uncertain_operation,
            recovery=recovery,
        )

    restarted_manager = PersistentIdempotencyManager(
        client=OfflineRedis(),
        fallback_dir=tmp_path,
    )
    with pytest.raises(IdempotencyUnknownError):
        restarted_manager.execute(
            run_id="unknown-run-001",
            tool_call_id="call-001",
            tool_name="charge_card",
            arguments={"amount": 100},
            operation=lambda: pytest.fail("an UNKNOWN operation must not rerun"),
            recovery=recovery,
        )

    journal = restarted_manager.get_recovery("unknown-run-001")
    assert journal["status"] == "UNKNOWN"


def test_persisted_call_id_rejects_different_operation(tmp_path):
    first_manager = PersistentIdempotencyManager(
        client=OfflineRedis(),
        fallback_dir=tmp_path,
    )
    first_manager.execute(
        run_id="conflict-run-001",
        tool_call_id="call-001",
        tool_name="create_order",
        arguments={"item": "book"},
        operation=lambda: {"order_id": 1001},
    )

    second_manager = PersistentIdempotencyManager(
        client=OfflineRedis(),
        fallback_dir=tmp_path,
    )
    with pytest.raises(IdempotencyConflictError):
        second_manager.execute(
            run_id="conflict-run-001",
            tool_call_id="call-001",
            tool_name="create_order",
            arguments={"item": "phone"},
            operation=lambda: {"order_id": 1002},
        )


def test_local_fallback_record_is_restored_when_redis_recovers(tmp_path):
    offline_manager = PersistentIdempotencyManager(
        client=OfflineRedis(),
        fallback_dir=tmp_path,
    )
    offline_manager.execute(
        run_id="restore-run-001",
        tool_call_id="call-001",
        tool_name="create_order",
        arguments={"item": "book"},
        operation=lambda: {"order_id": 1001},
    )

    recovered_redis = InMemoryRedis()
    recovered_manager = PersistentIdempotencyManager(
        client=recovered_redis,
        fallback_dir=tmp_path,
    )
    replay = recovered_manager.execute(
        run_id="restore-run-001",
        tool_call_id="call-001",
        tool_name="create_order",
        arguments={"item": "book"},
        operation=lambda: pytest.fail("completed fallback work must not rerun"),
    )

    assert replay == {"order_id": 1001}
    assert recovered_redis.values
