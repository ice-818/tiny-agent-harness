from core.retry import retry_call


def test_retry_success_after_failure(monkeypatch):
    attempts = 0

    monkeypatch.setattr(
        "core.retry.time.sleep",
        lambda seconds: None
    )

    def unstable_call():
        nonlocal attempts
        attempts += 1

        if attempts < 3:
            raise ConnectionError("Temporary failure")

        return "success"

    result = retry_call(
        unstable_call,
        max_attempts=3
    )

    assert result == "success"
    assert attempts == 3

import pytest


def test_retry_exhausted(monkeypatch):
    """连续失败，达到最大尝试次数后抛出异常"""

    attempts = 0

    monkeypatch.setattr(
        "core.retry.time.sleep",
        lambda seconds: None
    )

    def always_fail():
        nonlocal attempts
        attempts += 1
        raise ConnectionError("Service unavailable")

    with pytest.raises(ConnectionError):
        retry_call(
            always_fail,
            max_attempts=3
        )

    assert attempts == 3


def test_retry_non_retryable_error(monkeypatch):
    """不可重试的异常，应立即失败"""

    attempts = 0

    def invalid_request():
        nonlocal attempts
        attempts += 1
        raise ValueError("Invalid request parameters")

    with pytest.raises(ValueError):
        retry_call(
            invalid_request,
            max_attempts=3
        )

    assert attempts == 1



import json
import logging


def test_retry_logging(monkeypatch, caplog):
    attempts = 0

    monkeypatch.setattr(
        "core.retry.time.sleep",
        lambda seconds: None
    )

    def unstable_call():
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            raise ConnectionError("Temporary failure")

        return "success"

    with caplog.at_level(
            logging.INFO,
            logger="tiny_agent_harness"
    ):
        result = retry_call(
            unstable_call,
            max_attempts=3,
            run_id="test-run-123",
            step=2
        )

    assert result == "success"
    assert attempts == 2

    # 解析结构化 JSON 日志
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "tiny_agent_harness"
    ]

    failed_event = next(
        event for event in events
        if event["event"] == "retry_failed"
    )

    wait_event = next(
        event for event in events
        if event["event"] == "retry_wait"
    )

    success_event = next(
        event for event in events
        if event["event"] == "retry_success"
    )

    assert failed_event["run_id"] == "test-run-123"
    assert failed_event["step"] == 2
    assert failed_event["attempt"] == 1
    assert failed_event["error_type"] == "ConnectionError"

    assert wait_event["delay_ms"] == 500.0

    assert success_event["run_id"] == "test-run-123"
    assert success_event["step"] == 2
    assert success_event["attempt"] == 2