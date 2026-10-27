import json
import uuid

from core.memory import MemoryManager


def test_real_redis_checkpoint_sync():
    memory = MemoryManager()

    # 每次测试生成独立 ID，避免影响已有数据
    session_id = f"integration-{uuid.uuid4().hex}"
    key = f"checkpoint:{session_id}"

    try:
        # 初始状态：Redis v1
        memory.client.hset(
            key,
            mapping={
                "version": 1,
                "step": 1,
                "context": json.dumps({
                    "messages": [],
                    "status": "running"
                })
            }
        )
        memory.client.expire(key, 3600)

        # 场景一：本地 v3 比 Redis v1 更新
        newer_checkpoint = {
            "version": 3,
            "step": 3,
            "context": {
                "messages": [{"role": "tool", "content": "200"}],
                "status": "running"
            }
        }

        result = memory._sync_checkpoint_to_redis(
            session_id,
            newer_checkpoint
        )

        assert result == 1

        saved = memory.client.hgetall(key)

        assert int(saved["version"]) == 3
        assert int(saved["step"]) == 3
        assert json.loads(saved["context"]) == newer_checkpoint["context"]

        # 场景二：Redis 已经是 v5
        memory.client.hset(
            key,
            mapping={
                "version": 5,
                "step": 5,
                "context": json.dumps({
                    "messages": [],
                    "status": "completed"
                })
            }
        )

        # 尝试用旧的 v3 覆盖 v5
        result = memory._sync_checkpoint_to_redis(
            session_id,
            newer_checkpoint
        )

        assert result == 0

        saved = memory.client.hgetall(key)

        assert int(saved["version"]) == 5
        assert int(saved["step"]) == 5
        assert json.loads(saved["context"])["status"] == "completed"

    finally:
        # 清理测试数据
        memory.client.delete(key)


def test_real_redis_cas_rejects_stale_write():
    import json
    import uuid
    import pytest

    from core.memory import (
        MemoryManager,
        CheckpointConflictError
    )

    memory = MemoryManager()

    session_id = f"cas-{uuid.uuid4().hex}"
    key = f"checkpoint:{session_id}"

    try:
        # 初始化 Redis v1
        memory.client.hset(
            key,
            mapping={
                "version": 1,
                "step": 1,
                "context": json.dumps({
                    "status": "running"
                })
            }
        )
        memory.client.expire(key, 3600)

        # Agent A 和 Agent B 都基于 v1 准备写入
        checkpoint_a = {
            "version": 2,
            "step": 2,
            "context": {"writer": "A"}
        }

        checkpoint_b = {
            "version": 2,
            "step": 2,
            "context": {"writer": "B"}
        }

        # Agent A 先成功写入 v2
        memory._cas_save_checkpoint(
            session_id,
            expected_version=1,
            checkpoint=checkpoint_a
        )

        # Agent B 仍使用旧的 expected_version=1
        # 必须被 CAS 拒绝
        with pytest.raises(CheckpointConflictError):
            memory._cas_save_checkpoint(
                session_id,
                expected_version=1,
                checkpoint=checkpoint_b
            )

        # Redis 必须保留 Agent A 的数据
        saved = memory.client.hgetall(key)

        assert int(saved["version"]) == 2
        assert json.loads(saved["context"]) == {"writer": "A"}

    finally:
        memory.client.delete(key)
