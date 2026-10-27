from core import loop


def test_agent_loop_success(monkeypatch):

    responses = [
        {
            "type": "tool_call",
            "tool_call_id": "call_001",
            "tool_name": "calculator",
            "arguments": {
                "a": 25,
                "b": 8,
                "op": "mul"
            }
        },
        {
            "type": "final",
            "content": "25乘以8等于200"
        }
    ]

    def mock_chat(messages, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(loop.router, "chat", mock_chat)

    result = loop.run("帮我计算25乘以8")

    assert result == "25乘以8等于200"
    assert len(responses) == 0

def test_agent_loop_max_steps(monkeypatch):

    call_count = 0

    def mock_chat(messages, **kwargs):
        nonlocal call_count
        call_count += 1

        return {
            "type": "tool_call",
            "tool_call_id": f"call_{call_count}",
            "tool_name": "calculator",
            "arguments": {
                "a": 10,
                "b": 20,
                "op": "add"
            }
        }

    monkeypatch.setattr(loop.router, "chat", mock_chat)

    result = loop.run("测试最大步数", max_steps=3)

    assert call_count == 3
    assert result == "Agent stopped: exceeded max steps (3)"

import json

def test_tool_observation_json(monkeypatch):
    captured_messages = []

    def mock_chat(messages,**kwargs):
        captured_messages.append(
            [message.copy() for message in messages]
        )

        if len(captured_messages) == 1:
            return {
                "type": "tool_call",
                "tool_call_id": "call_001",
                "tool_name": "calculator",
                "arguments": {
                    "a": 25,
                    "b": 8,
                    "op": "mul"
                }
            }

        return {
            "type": "final",
            "content": "计算完成"
        }

    monkeypatch.setattr(loop.router, "chat", mock_chat)

    result = loop.run("计算25乘以8")

    assert result == "计算完成"
    assert len(captured_messages) == 2

    second_messages = captured_messages[1]

    tool_messages = [
        message
        for message in second_messages
        if message["role"] == "tool"
    ]

    assert len(tool_messages) == 1

    observation = tool_messages[0]

    assert observation["tool_call_id"] == "call_001"

    tool_result = json.loads(observation["content"])

    assert tool_result["success"] is True
    assert tool_result["result"] == 200
    assert tool_result["error"] is None
    assert tool_result["error_type"] is None

def test_agent_loop_llm_failure(monkeypatch, caplog):

    def mock_chat(messages, **kwargs):
        raise ConnectionError("Ollama connection failed")

    monkeypatch.setattr(loop.router, "chat", mock_chat)

    with caplog.at_level(
            "INFO",
            logger="tiny_agent_harness"
    ):
        result = loop.run("测试模型连接失败")

    assert result == "Agent failed: LLM call error (ConnectionError)"

    assert any(
        '"event": "agent_failed"' in record.message
        and '"error_type": "ConnectionError"' in record.message
        for record in caplog.records
    )

import logging

import httpx
from openai import APITimeoutError


def test_retry_run_id_consistency(monkeypatch, caplog):
    attempts = 0

    # 跳过重试等待
    monkeypatch.setattr(
        "core.retry.time.sleep",
        lambda seconds: None
    )

    # 模拟底层 Ollama 请求
    def mock_create(**kwargs):
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            raise APITimeoutError(
                request=httpx.Request(
                    "POST",
                    "http://127.0.0.1:11434/v1/chat/completions"
                )
            )

        # 第二次请求成功，返回最终答案
        from types import SimpleNamespace

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="测试成功",
                        tool_calls=None
                    )
                )
            ]
        )

    monkeypatch.setattr(
        loop.router.local_client.chat.completions,
        "create",
        mock_create
    )

    with caplog.at_level(
            logging.INFO,
            logger="tiny_agent_harness"
    ):
        result = loop.run("测试 Retry run_id")

    assert result == "测试成功"
    assert attempts == 2

    # 获取 Agent 创建的 run_id
    import json

    start_log = next(
        json.loads(record.message)
        for record in caplog.records
        if '"event": "agent_start"' in record.message
    )

    run_id = start_log["run_id"]

# 解析 Retry 的 JSON 日志
    retry_events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "tiny_agent_harness"
          and json.loads(record.message).get("event", "").startswith("retry_")
    ]

# 验证失败和恢复事件都存在
    failed_event = next(
        event for event in retry_events
        if event["event"] == "retry_failed"
    )

    success_event = next(
        event for event in retry_events
        if event["event"] == "retry_success"
    )

# 验证与 Agent 使用同一个 run_id
    assert failed_event["run_id"] == run_id
    assert success_event["run_id"] == run_id

# 验证重试次数
    assert failed_event["attempt"] == 1
    assert success_event["attempt"] == 2

    # 验证 Retry 事件记录的是 Agent 第 1 轮执行
    assert failed_event["step"] == 1
    assert success_event["step"] == 1

def test_agent_loop_saves_checkpoint(monkeypatch):

    saved_checkpoints = []
    responses = [
        {
            "type": "tool_call",
            "tool_call_id": "call_001",
            "tool_name": "calculator",
            "arguments": {
                "a": 25,
                "b": 8,
                "op": "mul"
            }
        },
        {
            "type": "final",
            "content": "25乘以8等于200"
        }
    ]

    def mock_chat(messages, **kwargs):
        return responses.pop(0)

    class FakeMemoryManager:
        def save_checkpoint(self, session_id, step, context):
            saved_checkpoints.append({
                "session_id": session_id,
                "step": step,
                "context": json.loads(json.dumps(context))
            })

    monkeypatch.setattr(loop.router, "chat", mock_chat)

    # 先约定 Loop 将通过 MemoryManager 保存状态
    monkeypatch.setattr(
        loop,
        "MemoryManager",
        FakeMemoryManager,
        raising=False
    )

    result = loop.run("帮我计算25乘以8")

    assert result == "25乘以8等于200"

    # 工具执行后保存 running，任务完成后保存 completed
    assert len(saved_checkpoints) == 2

    # 第一次保存：工具执行完成
    checkpoint = saved_checkpoints[0]

    assert checkpoint["context"]["status"] == "running"

    # 第二次保存：整个 Agent 任务完成
    completed_checkpoint = saved_checkpoints[1]

    assert completed_checkpoint["context"]["status"] == "completed"
    assert completed_checkpoint["step"] == 2
    assert (
            completed_checkpoint["session_id"]
            == checkpoint["session_id"]
    )

    # 第 1 轮工具执行完成，下一轮应从 step=2 开始
    assert checkpoint["step"] == 2

    # Checkpoint 必须包含完整消息历史
    messages = checkpoint["context"]["messages"]

    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["role"] == "tool"

    # 工具执行结果必须保存
    observation = json.loads(messages[2]["content"])

    assert observation["success"] is True
    assert observation["result"] == 200

    assert checkpoint["context"]["status"] == "running"

def test_agent_loop_resume_from_checkpoint(monkeypatch):

    resumed_run_id = "resume-test-001"

    checkpoint = {
        "step": 2,
        "context": {
            "messages": [
                {"role": "user", "content": "帮我计算25乘以8"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_001",
                            "type": "function",
                            "function": {
                                "name": "calculator",
                                "arguments": '{"a":25,"b":8,"op":"mul"}'
                            }
                        }
                    ]
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_001",
                    "content": '{"success":true,"result":200}'
                }
            ],
            "status": "running"
        }
    }

    class FakeMemoryManager:
        def get_checkpoint(self, session_id):
            assert session_id == resumed_run_id
            return checkpoint

        def save_checkpoint(self, session_id, step, context):
            pass

    captured = {}

    def mock_chat(messages, **kwargs):
        captured["messages"] = messages
        captured["step"] = kwargs["step"]
        captured["run_id"] = kwargs["run_id"]

        return {
            "type": "final",
            "content": "恢复执行成功，答案是200"
        }

    monkeypatch.setattr(loop, "MemoryManager", FakeMemoryManager)
    monkeypatch.setattr(loop.router, "chat", mock_chat)

    result = loop.run(
        "帮我计算25乘以8",
        run_id=resumed_run_id
    )

    assert result == "恢复执行成功，答案是200"
    assert captured["run_id"] == resumed_run_id
    assert captured["step"] == 2
    assert captured["messages"] == checkpoint["context"]["messages"]

def test_agent_loop_marks_checkpoint_completed(monkeypatch):

    saved_checkpoints = []

    class FakeMemoryManager:
        def save_checkpoint(self, session_id, step, context):
            saved_checkpoints.append({
                "session_id": session_id,
                "step": step,
                "context": json.loads(json.dumps(context))
            })

    def mock_chat(messages, **kwargs):
        return {
            "type": "final",
            "content": "任务完成"
        }

    monkeypatch.setattr(loop, "MemoryManager", FakeMemoryManager)
    monkeypatch.setattr(loop.router, "chat", mock_chat)

    result = loop.run("测试任务完成状态")

    assert result == "任务完成"
    assert len(saved_checkpoints) == 1

    checkpoint = saved_checkpoints[0]

    assert checkpoint["context"]["status"] == "completed"
    assert checkpoint["step"] == 1