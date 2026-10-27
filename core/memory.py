import json
import os
import re
import tempfile
from pathlib import Path

import redis


class MemoryManager:
    def __init__(self):
        # 连接本地 Docker 运行的 Redis
        self.client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True
        )

        # Redis 故障时的本地备用存储目录
        self.fallback_dir = Path("data/checkpoints")

    def save_history(self, session_id: str, role: str, content: str):
        key = f"history:{session_id}"

        self.client.rpush(
            key,
            json.dumps(
                {"role": role, "content": content},
                ensure_ascii=False
            )
        )

        self.client.expire(key, 3600)

    def get_history(self, session_id: str):
        key = f"history:{session_id}"

        history = self.client.lrange(key, 0, -1)

        return [json.loads(item) for item in history]

    def save_checkpoint(self, session_id: str, step: int, context: dict):
        # 验证 session_id，避免路径穿越
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
            raise ValueError("Invalid checkpoint session_id")

        key = f"checkpoint:{session_id}"

        try:
            # 优先保存到 Redis
            self.client.hset(
                key,
                mapping={
                    "step": step,
                    "context": json.dumps(
                        context,
                        ensure_ascii=False
                    )
                }
            )

            self.client.expire(key, 3600)
            return

        except redis.exceptions.ConnectionError:
            # Redis 连接失败，切换到本地 JSON 存储
            fallback_dir = Path(self.fallback_dir)

            fallback_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            target = fallback_dir / f"{session_id}.json"

            checkpoint_data = {
                "step": step,
                "context": context
            }

            # 使用临时文件 + 原子替换，避免写入半截 JSON
            temp_path = None

            try:
                with tempfile.NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        dir=fallback_dir,
                        prefix=".checkpoint-",
                        suffix=".tmp",
                        delete=False
                ) as temp_file:

                    temp_path = Path(temp_file.name)

                    json.dump(
                        checkpoint_data,
                        temp_file,
                        ensure_ascii=False
                    )

                    temp_file.flush()
                    os.fsync(temp_file.fileno())

                os.replace(temp_path, target)

            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)

    def get_checkpoint(self, session_id: str):
        # 验证 session_id，避免路径穿越
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
            raise ValueError("Invalid checkpoint session_id")

        key = f"checkpoint:{session_id}"

        fallback_dir = Path(self.fallback_dir)
        fallback_file = fallback_dir / f"{session_id}.json"

        redis_checkpoint = None
        local_checkpoint = None

        # 1. 尝试从 Redis 读取 Checkpoint
        try:
            data = self.client.hgetall(key)

            if data:
                redis_checkpoint = {
                    "step": int(data["step"]),
                    "context": json.loads(data["context"])
                }

        except redis.exceptions.ConnectionError:
            # Redis 不可用时，继续尝试本地文件
            pass

        # 2. 尝试读取本地 Checkpoint
        if fallback_file.exists():
            with fallback_file.open(
                    "r",
                    encoding="utf-8"
            ) as f:
                local_checkpoint = json.load(f)

        # 3. Redis 和本地都有 Checkpoint
        if redis_checkpoint is not None and local_checkpoint is not None:

            # 当前阶段暂时用 step 判断哪个状态更新
            if local_checkpoint["step"] > redis_checkpoint["step"]:
                return local_checkpoint

            return redis_checkpoint

        # 4. 只有一个存储位置有数据
        return redis_checkpoint or local_checkpoint