
import json
import os
import re
import tempfile
from pathlib import Path

import redis


class CheckpointConflictError(RuntimeError):
    """Checkpoint version conflict."""


class MemoryManager:
    CHECKPOINT_TTL = 3600

    CAS_SCRIPT = """
    local current = redis.call('HGET', KEYS[1], 'version')
    local expected = tonumber(ARGV[1])
    local new_version = tonumber(ARGV[2])

    local current_version = tonumber(current or '0')

    if current_version ~= expected then
        return 0
    end

    redis.call(
        'HSET',
        KEYS[1],
        'version', ARGV[2],
        'step', ARGV[3],
        'context', ARGV[4]
    )

    redis.call('EXPIRE', KEYS[1], 3600)
    return 1
    """

    SYNC_SCRIPT = """
    local current = redis.call('HGET', KEYS[1], 'version')
    local new_version = tonumber(ARGV[1])

    if current and tonumber(current) >= new_version then
        return 0
    end

    redis.call(
        'HSET',
        KEYS[1],
        'version', ARGV[1],
        'step', ARGV[2],
        'context', ARGV[3]
    )

    redis.call('EXPIRE', KEYS[1], 3600)
    return 1
    """

    def __init__(self):
        self.client = redis.Redis(
            host=os.getenv("TINY_AGENT_REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("TINY_AGENT_REDIS_PORT", "6379")),
            db=int(os.getenv("TINY_AGENT_REDIS_DB", "0")),
            decode_responses=True
        )
        data_dir = Path(os.getenv("TINY_AGENT_DATA_DIR", "data"))
        self.fallback_dir = data_dir / "checkpoints"

    def _validate_session_id(self, session_id: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
            raise ValueError("Invalid checkpoint session_id")

    def save_history(self, session_id: str, role: str, content: str):
        key = f"history:{session_id}"

        self.client.rpush(
            key,
            json.dumps(
                {"role": role, "content": content},
                ensure_ascii=False
            )
        )
        self.client.expire(key, self.CHECKPOINT_TTL)

    def get_history(self, session_id: str):
        key = f"history:{session_id}"
        history = self.client.lrange(key, 0, -1)
        return [json.loads(item) for item in history]

    def _save_local_checkpoint(self, session_id: str, checkpoint: dict):
        fallback_dir = Path(self.fallback_dir)
        fallback_dir.mkdir(parents=True, exist_ok=True)

        target = fallback_dir / f"{session_id}.json"
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
                json.dump(checkpoint, temp_file, ensure_ascii=False)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            os.replace(temp_path, target)

        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _read_local_checkpoint(self, session_id: str):
        fallback_file = Path(self.fallback_dir) / f"{session_id}.json"

        if not fallback_file.exists():
            return None

        with fallback_file.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _read_redis_checkpoint(self, session_id: str):
        data = self.client.hgetall(f"checkpoint:{session_id}")

        if not data:
            return None

        checkpoint = {
            "step": int(data["step"]),
            "context": json.loads(data["context"])
        }

        if "version" in data:
            checkpoint["version"] = int(data["version"])

        return checkpoint

    def _select_checkpoint(self, redis_checkpoint, local_checkpoint):
        if redis_checkpoint is None:
            return local_checkpoint

        if local_checkpoint is None:
            return redis_checkpoint

        redis_version = redis_checkpoint.get("version")
        local_version = local_checkpoint.get("version")

        if redis_version is not None and local_version is not None:
            if local_version > redis_version:
                return local_checkpoint

            if redis_version > local_version:
                return redis_checkpoint

            if local_checkpoint != redis_checkpoint:
                raise ValueError(
                    "Checkpoint conflict: same version, different content"
                )

            return redis_checkpoint

        # Backward compatibility for unversioned checkpoints.
        if local_checkpoint["step"] > redis_checkpoint["step"]:
            return local_checkpoint

        return redis_checkpoint

    def _sync_checkpoint_to_redis(self, session_id: str, checkpoint: dict):
        key = f"checkpoint:{session_id}"

        return self.client.eval(
            self.SYNC_SCRIPT,
            1,
            key,
            checkpoint["version"],
            checkpoint["step"],
            json.dumps(checkpoint["context"], ensure_ascii=False)
        )

    def _cas_save_checkpoint(
            self,
            session_id: str,
            expected_version: int,
            checkpoint: dict
    ):
        key = f"checkpoint:{session_id}"

        result = self.client.eval(
            self.CAS_SCRIPT,
            1,
            key,
            expected_version,
            checkpoint["version"],
            checkpoint["step"],
            json.dumps(checkpoint["context"], ensure_ascii=False)
        )

        if result != 1:
            raise CheckpointConflictError(
                f"Checkpoint conflict for {session_id}: "
                f"expected version {expected_version}"
            )

    def save_checkpoint(self, session_id: str, step: int, context: dict):
        self._validate_session_id(session_id)

        previous = self.get_checkpoint(session_id)
        expected_version = (
            previous.get("version", 0)
            if previous is not None
            else 0
        )

        checkpoint = {
            "version": expected_version + 1,
            "step": step,
            "context": context
        }

        try:
            self._cas_save_checkpoint(
                session_id,
                expected_version,
                checkpoint
            )

        except redis.exceptions.ConnectionError:
            # Single-writer fallback only. Multi-writer offline
            # concurrency requires additional coordination.
            self._save_local_checkpoint(session_id, checkpoint)

    def get_checkpoint(self, session_id: str):
        self._validate_session_id(session_id)

        redis_checkpoint = None
        redis_available = True

        try:
            redis_checkpoint = self._read_redis_checkpoint(session_id)
        except redis.exceptions.ConnectionError:
            redis_available = False

        local_checkpoint = self._read_local_checkpoint(session_id)

        selected = self._select_checkpoint(
            redis_checkpoint,
            local_checkpoint
        )

        if (
                redis_available
                and local_checkpoint is not None
                and selected == local_checkpoint
                and local_checkpoint.get("version") is not None
                and (
                redis_checkpoint is None
                or local_checkpoint["version"]
                > redis_checkpoint.get("version", 0)
        )
        ):
            try:
                synced = self._sync_checkpoint_to_redis(
                    session_id,
                    local_checkpoint
                )

                if synced == 0:
                    # Redis may have changed after the initial read.
                    latest = self._read_redis_checkpoint(session_id)
                    selected = self._select_checkpoint(
                        latest,
                        local_checkpoint
                    )

            except redis.exceptions.ConnectionError:
                pass

        return selected
