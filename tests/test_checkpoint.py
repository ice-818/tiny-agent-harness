import unittest
import uuid

from core.memory import MemoryManager


class TestCheckpoint(unittest.TestCase):

    def test_save_and_load_agent_messages(self):
        memory = MemoryManager()
        session_id = f"test-{uuid.uuid4().hex}"

        messages = [
            {
                "role": "user",
                "content": "帮我算25乘以8"
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_001",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"a": 25, "b": 8, "op": "multiply"}'
                        }
                    }
                ]
            },
            {
                "role": "tool",
                "tool_call_id": "call_001",
                "content": '{"success": true, "result": 200}'
            }
        ]

        context = {
            "messages": messages,
            "status": "running"
        }

        try:
            memory.save_checkpoint(
                session_id=session_id,
                step=2,
                context=context
            )

            checkpoint = memory.get_checkpoint(session_id)

            self.assertIsNotNone(checkpoint)
            self.assertEqual(checkpoint["step"], 2)
            self.assertEqual(checkpoint["context"], context)

        finally:
            memory.client.delete(f"checkpoint:{session_id}")


if __name__ == "__main__":
    unittest.main()

def test_checkpoint_fallback_when_redis_unavailable(
        monkeypatch,
        tmp_path
):
    import redis

    from core.memory import MemoryManager

    memory = MemoryManager()

    # 使用 pytest 提供的临时目录
    memory.fallback_dir = tmp_path

    # 模拟 Redis 写入失败
    def mock_hset(*args, **kwargs):
        raise redis.exceptions.ConnectionError(
            "Redis connection lost"
        )

    monkeypatch.setattr(
        memory.client,
        "hset",
        mock_hset
    )

    context = {
        "messages": [
            {
                "role": "user",
                "content": "帮我计算25乘以8"
            },
            {
                "role": "tool",
                "tool_call_id": "call_001",
                "content": '{"result": 200}'
            }
        ],
        "status": "running"
    }

    memory.save_checkpoint(
        session_id="fallback-test-001",
        step=2,
        context=context
    )

    # Redis 故障时，应该生成本地备用文件
    fallback_file = (
            tmp_path / "fallback-test-001.json"
    )

    assert fallback_file.exists()

    # 验证保存的数据没有丢失
    import json

    saved_data = json.loads(
        fallback_file.read_text(encoding="utf-8")
    )

    assert saved_data["step"] == 2
    assert saved_data["context"] == context

def test_checkpoint_read_fallback_when_redis_unavailable(
        monkeypatch,
        tmp_path
):
    import json
    import redis
    from core.memory import MemoryManager

    memory = MemoryManager()
    memory.fallback_dir = tmp_path

    session_id = "fallback-read-test-001"

    expected = {
        "step": 2,
        "context": {
            "messages": [
                {"role": "user", "content": "计算25乘以8"},
                {
                    "role": "tool",
                    "tool_call_id": "call_001",
                    "content": '{"result":200}'
                }
            ],
            "status": "running"
        }
    }

    # 模拟已经存在的本地 Checkpoint
    fallback_file = tmp_path / f"{session_id}.json"
    fallback_file.write_text(
        json.dumps(expected, ensure_ascii=False),
        encoding="utf-8"
    )

    # 模拟 Redis 读取失败
    def mock_hgetall(*args, **kwargs):
        raise redis.exceptions.ConnectionError(
            "Redis connection lost"
        )

    monkeypatch.setattr(
        memory.client,
        "hgetall",
        mock_hgetall
    )

    result = memory.get_checkpoint(session_id)

    assert result == expected

def test_checkpoint_should_not_ignore_newer_local_state(
        monkeypatch,
        tmp_path
):
    import json
    from core.memory import MemoryManager

    memory = MemoryManager()
    memory.fallback_dir = tmp_path

    session_id = "checkpoint-conflict-001"

    # Redis 中保存的是旧状态
    redis_context = {
        "messages": [{"role": "user", "content": "计算25乘以8"}],
        "status": "running"
    }

    monkeypatch.setattr(
        memory.client,
        "hgetall",
        lambda key: {
            "step": "1",
            "context": json.dumps(redis_context)
        }
    )

    # 本地 JSON 保存的是更新的状态
    local_checkpoint = {
        "step": 2,
        "context": {
            "messages": [
                {"role": "user", "content": "计算25乘以8"},
                {"role": "tool", "content": "200"}
            ],
            "status": "running"
        }
    }

    (tmp_path / f"{session_id}.json").write_text(
        json.dumps(local_checkpoint),
        encoding="utf-8"
    )

    result = memory.get_checkpoint(session_id)

    assert result == local_checkpoint