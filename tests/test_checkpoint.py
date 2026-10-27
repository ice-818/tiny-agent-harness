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
    import json
    import redis

    from core.memory import MemoryManager

    memory = MemoryManager()
    memory.fallback_dir = tmp_path

    session_id = "fallback-test-001"

    # 模拟 Redis 读取失败
    def mock_hgetall(*args, **kwargs):
        raise redis.exceptions.ConnectionError(
            "Redis connection lost"
        )

    # 模拟 Redis Lua CAS 写入失败
    def mock_eval(*args, **kwargs):
        raise redis.exceptions.ConnectionError(
            "Redis connection lost"
        )

    monkeypatch.setattr(
        memory.client,
        "hgetall",
        mock_hgetall
    )

    monkeypatch.setattr(
        memory.client,
        "eval",
        mock_eval
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
        session_id=session_id,
        step=2,
        context=context
    )

    fallback_file = tmp_path / f"{session_id}.json"

    assert fallback_file.exists()

    saved = json.loads(
        fallback_file.read_text(encoding="utf-8")
    )

    assert saved["version"] == 1
    assert saved["step"] == 2
    assert saved["context"] == context

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

def test_checkpoint_prefers_higher_version(
        monkeypatch,
        tmp_path
):
    import json
    from core.memory import MemoryManager

    memory = MemoryManager()
    memory.fallback_dir = tmp_path

    session_id = "version-conflict-001"

    redis_checkpoint = {
        "version": 5,
        "step": 3,
        "context": {
            "messages": [],
            "status": "running"
        }
    }

    local_checkpoint = {
        "version": 6,
        "step": 3,
        "context": {
            "messages": [],
            "status": "completed"
        }
    }

    monkeypatch.setattr(
        memory.client,
        "hgetall",
        lambda key: {
            "version": "5",
            "step": "3",
            "context": json.dumps(
                redis_checkpoint["context"]
            )
        }
    )

    fallback_file = tmp_path / f"{session_id}.json"

    fallback_file.write_text(
        json.dumps(local_checkpoint),
        encoding="utf-8"
    )

    result = memory.get_checkpoint(session_id)

    assert result == local_checkpoint


def test_checkpoint_version_increments_on_save(monkeypatch):
    import json
    from core.memory import MemoryManager

    memory = MemoryManager()
    storage = {}

    def mock_hgetall(key):
        return storage.get(key, {}).copy()

    def mock_eval(
            script,
            numkeys,
            key,
            expected_version,
            new_version,
            step,
            context
    ):
        current = storage.get(key, {})
        current_version = int(current.get("version", 0))

        # 模拟 Redis Lua CAS 的版本比较
        if current_version != int(expected_version):
            return 0

        # 只有版本匹配才允许写入
        storage[key] = {
            "version": str(new_version),
            "step": str(step),
            "context": context
        }

        return 1

    monkeypatch.setattr(
        memory.client,
        "hgetall",
        mock_hgetall
    )
    monkeypatch.setattr(
        memory.client,
        "eval",
        mock_eval
    )

    session_id = "version-increment-test-001"

    memory.save_checkpoint(
        session_id,
        step=1,
        context={"messages": [], "status": "running"}
    )

    first = memory.get_checkpoint(session_id)

    memory.save_checkpoint(
        session_id,
        step=2,
        context={"messages": [], "status": "running"}
    )

    second = memory.get_checkpoint(session_id)

    assert first["version"] == 1
    assert second["version"] == 2

    assert first["step"] == 1
    assert second["step"] == 2

    assert json.loads(
        storage[f"checkpoint:{session_id}"]["context"]
    ) == second["context"]


def test_checkpoint_version_increments_during_redis_outage(
        monkeypatch,
        tmp_path
):
    import redis
    from core.memory import MemoryManager

    memory = MemoryManager()
    memory.fallback_dir = tmp_path

    def redis_unavailable(*args, **kwargs):
        raise redis.exceptions.ConnectionError(
            "Redis unavailable"
        )

    # 模拟 Redis 读取失败
    monkeypatch.setattr(
        memory.client,
        "hgetall",
        redis_unavailable
    )

    # 模拟 Redis Lua CAS 写入失败
    monkeypatch.setattr(
        memory.client,
        "eval",
        redis_unavailable
    )

    session_id = "outage-version-test-001"

    # 第一次保存：应生成本地 v1
    memory.save_checkpoint(
        session_id,
        step=1,
        context={
            "messages": [],
            "status": "running"
        }
    )

    first = memory.get_checkpoint(session_id)

    # 第二次保存：Redis 仍然不可用，应生成本地 v2
    memory.save_checkpoint(
        session_id,
        step=2,
        context={
            "messages": [],
            "status": "running"
        }
    )

    second = memory.get_checkpoint(session_id)

    assert first["version"] == 1
    assert second["version"] == 2

    assert first["step"] == 1
    assert second["step"] == 2

    # 确认最终版本确实保存在本地 JSON
    import json

    fallback_file = tmp_path / f"{session_id}.json"

    assert fallback_file.exists()

    saved = json.loads(
        fallback_file.read_text(encoding="utf-8")
    )

    assert saved["version"] == 2
    assert saved["step"] == 2

def test_checkpoint_syncs_local_state_to_redis(monkeypatch, tmp_path):
    import json
    from core.memory import MemoryManager

    memory = MemoryManager()
    memory.fallback_dir = tmp_path

    session_id = "sync-test-001"
    key = f"checkpoint:{session_id}"

    redis_storage = {
        key: {
            "version": "1",
            "step": "1",
            "context": json.dumps({
                "messages": [],
                "status": "running"
            })
        }
    }

    local_checkpoint = {
        "version": 3,
        "step": 3,
        "context": {
            "messages": [
                {"role": "tool", "content": "200"}
            ],
            "status": "running"
        }
    }

    fallback_file = tmp_path / f"{session_id}.json"
    fallback_file.write_text(
        json.dumps(local_checkpoint),
        encoding="utf-8"
    )

    def mock_hgetall(redis_key):
        return redis_storage.get(redis_key, {})

    def mock_eval(script, numkeys, redis_key, version, step, context):
        # 模拟 Lua 脚本的版本比较与条件写入
        current = redis_storage.get(redis_key, {})
        current_version = int(current.get("version", 0))

        if current_version >= int(version):
            return 0

        redis_storage[redis_key] = {
            "version": str(version),
            "step": str(step),
            "context": context
        }

        return 1

    monkeypatch.setattr(memory.client, "hgetall", mock_hgetall)
    monkeypatch.setattr(memory.client, "eval", mock_eval)

    result = memory.get_checkpoint(session_id)

    assert result == local_checkpoint
    assert redis_storage[key]["version"] == "3"
    assert redis_storage[key]["step"] == "3"
    assert json.loads(redis_storage[key]["context"]) == local_checkpoint["context"]

def test_checkpoint_rejects_stale_concurrent_write(monkeypatch):
    import pytest
    from core.memory import MemoryManager, CheckpointConflictError

    memory = MemoryManager()
    session_id = "concurrent-conflict-001"

    old_checkpoint = {
        "version": 3,
        "step": 3,
        "context": {
            "messages": [],
            "status": "running"
        }
    }

    # 模拟 Agent A 读取到 v3
    monkeypatch.setattr(
        memory,
        "get_checkpoint",
        lambda sid: old_checkpoint
    )

    # 模拟 CAS 检测到 Redis 版本已经改变
    monkeypatch.setattr(
        memory.client,
        "eval",
        lambda *args: 0
    )

    # 发生版本冲突时，必须明确拒绝写入
    with pytest.raises(CheckpointConflictError):
        memory.save_checkpoint(
            session_id,
            step=4,
            context={
                "messages": [],
                "status": "running"
            }
        )