from types import SimpleNamespace

import httpx
from openai import APITimeoutError

from router import ModelRouter


def test_router_retry_success(monkeypatch):
    router = ModelRouter()

    attempts = 0

    # 跳过真实等待，加快测试速度
    monkeypatch.setattr(
        "core.retry.time.sleep",
        lambda seconds: None
    )

    def mock_create(**kwargs):
        nonlocal attempts
        attempts += 1

        # 第一次调用模拟超时
        if attempts == 1:
            raise APITimeoutError(
                request=httpx.Request(
                    "POST",
                    "http://127.0.0.1:11434/v1/chat/completions"
                )
            )

        # 第二次调用模拟成功
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="你好",
                        tool_calls=None
                    )
                )
            ]
        )

    # 替换真实模型请求
    monkeypatch.setattr(
        router.local_client.chat.completions,
        "create",
        mock_create
    )

    result = router.chat(
        messages=[
            {"role": "user", "content": "你好"}
        ],
        task_type="chat"
    )

    assert result == {
        "type": "final",
        "content": "你好"
    }

    # 验证确实调用了两次
    assert attempts == 2

import pytest


def test_router_retry_exhausted(monkeypatch):
    router = ModelRouter()
    attempts = 0

    # 跳过重试等待
    monkeypatch.setattr(
        "core.retry.time.sleep",
        lambda seconds: None
    )

    def mock_create(**kwargs):
        nonlocal attempts
        attempts += 1

        raise APITimeoutError(
            request=httpx.Request(
                "POST",
                "http://127.0.0.1:11434/v1/chat/completions"
            )
        )

    monkeypatch.setattr(
        router.local_client.chat.completions,
        "create",
        mock_create
    )

    with pytest.raises(APITimeoutError):
        router.chat(
            messages=[
                {"role": "user", "content": "你好"}
            ],
            task_type="chat"
        )

    assert attempts == 3


from openai import BadRequestError


def test_router_non_retryable_error(monkeypatch):
    router = ModelRouter()
    attempts = 0

    def mock_create(**kwargs):
        nonlocal attempts
        attempts += 1

        request = httpx.Request(
            "POST",
            "http://127.0.0.1:11434/v1/chat/completions"
        )

        response = httpx.Response(
            status_code=400,
            request=request,
            json={"error": "Invalid request parameters"}
        )

        raise BadRequestError(
            message="Invalid request parameters",
            response=response,
            body=None
        )

    monkeypatch.setattr(
        router.local_client.chat.completions,
        "create",
        mock_create
    )

    with pytest.raises(BadRequestError):
        router.chat(
            messages=[
                {"role": "user", "content": "你好"}
            ],
            task_type="chat"
        )

    assert attempts == 1