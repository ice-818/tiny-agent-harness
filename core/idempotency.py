"""Idempotency primitives for tool calls.

The lightweight :class:`IdempotencyManager` preserves the original in-process
behaviour. The agent loop uses :class:`PersistentIdempotencyManager`, which
stores a small execution journal in Redis and falls back to local JSON files
when Redis is unavailable.

The journal deliberately distinguishes a completed tool call from one whose
side effect may have happened but whose outcome was not confirmed. The latter
is ``UNKNOWN`` and must be reconciled by an operator; it is never retried
automatically.
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import redis


class IdempotencyConflictError(ValueError):
    """The same call identity was supplied with a different operation."""


class IdempotencyInProgressError(RuntimeError):
    """Another worker currently owns this tool call."""


class IdempotencyUnknownError(RuntimeError):
    """The outcome of a tool call is unknown and cannot be retried safely."""


class IdempotencyStorageError(RuntimeError):
    """The durable idempotency journal could not be read safely."""


class _DurableIdempotencyStore:
    """Redis-first journal with an atomic local-file fallback.

    Redis ``SET ... NX`` reserves a call before its operation starts. When
    Redis is down, ``O_EXCL`` gives the local fallback the same single-writer
    reservation property on one Windows host.
    """

    TTL_SECONDS = 3600
    KEY_PREFIX = "tiny-agent:idempotency:v1"

    def __init__(
            self,
            client=None,
            fallback_dir: Optional[Path] = None,
            ttl_seconds: int = TTL_SECONDS,
    ):
        self.client = client or redis.Redis(
            host=os.getenv("TINY_AGENT_REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("TINY_AGENT_REDIS_PORT", "6379")),
            db=int(os.getenv("TINY_AGENT_REDIS_DB", "0")),
            decode_responses=True,
        )
        data_dir = Path(os.getenv("TINY_AGENT_DATA_DIR", "data"))
        self.fallback_dir = Path(fallback_dir or data_dir / "idempotency")
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _validate_identifier(value: str, field_name: str) -> None:
        if not isinstance(value, str) or not value or len(value) > 128:
            raise ValueError(
                f"{field_name} must be a non-empty string up to 128 characters"
            )

        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        if any(character not in allowed for character in value):
            raise ValueError(
                f"{field_name} may contain only letters, numbers, underscores, and hyphens"
            )

    def _redis_key(self, run_id: str, tool_call_id: str) -> str:
        return f"{self.KEY_PREFIX}:{run_id}:{tool_call_id}"

    def _fallback_path(self, run_id: str, tool_call_id: str) -> Path:
        return self.fallback_dir / f"{run_id}--{tool_call_id}.json"

    @staticmethod
    def _decode(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")

        try:
            record = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise IdempotencyStorageError("Invalid idempotency record") from error

        if not isinstance(record, dict):
            raise IdempotencyStorageError("Invalid idempotency record")

        required = {"run_id", "tool_call_id", "fingerprint", "status"}
        if not required.issubset(record):
            raise IdempotencyStorageError("Incomplete idempotency record")

        return record

    @staticmethod
    def _encode(record: Dict[str, Any]) -> str:
        try:
            return json.dumps(record, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise IdempotencyStorageError(
                "Idempotency records must be JSON serializable"
            ) from error

    def _read_local(self, run_id: str, tool_call_id: str):
        path = self._fallback_path(run_id, tool_call_id)
        if not path.exists():
            return None

        try:
            return self._decode(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise IdempotencyStorageError(
                "Could not read local idempotency record"
            ) from error

    def _write_local(self, record: Dict[str, Any]) -> None:
        self.fallback_dir.mkdir(parents=True, exist_ok=True)
        target = self._fallback_path(record["run_id"], record["tool_call_id"])
        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.fallback_dir,
                    prefix=".idempotency-",
                    suffix=".tmp",
                    delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(self._encode(record))
                temp_file.flush()
                os.fsync(temp_file.fileno())

            os.replace(temp_path, target)
        except OSError as error:
            raise IdempotencyStorageError(
                "Could not persist local idempotency record"
            ) from error
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _create_local(self, record: Dict[str, Any]) -> bool:
        self.fallback_dir.mkdir(parents=True, exist_ok=True)
        target = self._fallback_path(record["run_id"], record["tool_call_id"])

        try:
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        except OSError as error:
            raise IdempotencyStorageError(
                "Could not reserve local idempotency record"
            ) from error

        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as record_file:
                record_file.write(self._encode(record))
                record_file.flush()
                os.fsync(record_file.fileno())
        except BaseException:
            target.unlink(missing_ok=True)
            raise

        return True

    def reserve(self, record: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        run_id = record["run_id"]
        tool_call_id = record["tool_call_id"]
        self._validate_identifier(run_id, "run_id")
        self._validate_identifier(tool_call_id, "tool_call_id")
        encoded = self._encode(record)
        local_record = self._read_local(run_id, tool_call_id)

        try:
            existing = self.client.get(self._redis_key(run_id, tool_call_id))
            if existing is not None:
                return self._decode(existing), False

            # Redis may have recovered after an earlier outage. Restore the
            # local journal before considering a new operation, otherwise a
            # completed fallback record could be executed a second time.
            if local_record is not None:
                restored = self.client.set(
                    self._redis_key(run_id, tool_call_id),
                    self._encode(local_record),
                    nx=True,
                    ex=self.ttl_seconds,
                )
                if restored:
                    return local_record, False

                concurrent = self.client.get(
                    self._redis_key(run_id, tool_call_id)
                )
                if concurrent is None:
                    raise IdempotencyStorageError(
                        "Idempotency record disappeared while being restored"
                    )
                return self._decode(concurrent), False

            created = self.client.set(
                self._redis_key(run_id, tool_call_id),
                encoded,
                nx=True,
                ex=self.ttl_seconds,
            )
            if created:
                # Keep a local recovery copy even when Redis is healthy.
                self._write_local(record)
                return record, True

            concurrent = self.client.get(self._redis_key(run_id, tool_call_id))
            if concurrent is None:
                raise IdempotencyStorageError(
                    "Idempotency reservation disappeared before it could be read"
                )
            return self._decode(concurrent), False
        except redis.exceptions.ConnectionError:
            if local_record is not None:
                return local_record, False

            created = self._create_local(record)
            if created:
                return record, True

            existing = self._read_local(run_id, tool_call_id)
            if existing is None:
                raise IdempotencyStorageError(
                    "Local idempotency reservation disappeared before it could be read"
                )
            return existing, False

    def update(self, record: Dict[str, Any]) -> None:
        run_id = record["run_id"]
        tool_call_id = record["tool_call_id"]
        encoded = self._encode(record)

        try:
            updated = self.client.set(
                self._redis_key(run_id, tool_call_id),
                encoded,
                xx=True,
                ex=self.ttl_seconds,
            )
            if not updated:
                raise IdempotencyStorageError(
                    "Idempotency record disappeared before it could be updated"
                )
            self._write_local(record)
        except redis.exceptions.ConnectionError:
            self._write_local(record)

    def _local_records_for_run(self, run_id: str):
        records = []
        if not self.fallback_dir.exists():
            return records

        for path in self.fallback_dir.glob(f"{run_id}--*.json"):
            try:
                record = self._decode(path.read_text(encoding="utf-8"))
            except OSError as error:
                raise IdempotencyStorageError(
                    "Could not read local idempotency record"
                ) from error
            if record.get("run_id") == run_id:
                records.append(record)
        return records

    def records_for_run(self, run_id: str):
        self._validate_identifier(run_id, "run_id")

        records_by_call = {
            record["tool_call_id"]: record
            for record in self._local_records_for_run(run_id)
        }

        try:
            pattern = f"{self.KEY_PREFIX}:{run_id}:*"
            for key in self.client.scan_iter(match=pattern):
                raw = self.client.get(key)
                if raw is not None:
                    record = self._decode(raw)
                    # Redis is the source of truth when it is available.
                    records_by_call[record["tool_call_id"]] = record
        except redis.exceptions.ConnectionError:
            pass

        return list(records_by_call.values())


class IdempotencyManager:
    """Thread-safe, in-process tool call deduplication.

    This is intentionally the original lightweight implementation. It is
    useful for unit tests and demos. Production loops should use
    :class:`PersistentIdempotencyManager`.
    """

    def __init__(self):
        self._records = {}
        self._lock = threading.RLock()

    @staticmethod
    def _fingerprint(tool_name: str, arguments: dict) -> str:
        return json.dumps(
            {
                "tool_name": tool_name,
                "arguments": arguments,
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    def execute(
            self,
            run_id: str,
            tool_call_id: str,
            tool_name: str,
            arguments: dict,
            operation: Callable[[], Any],
            recovery: Optional[Dict[str, Any]] = None,
    ) -> Any:
        del recovery  # The in-process manager has no cross-process recovery.

        if not run_id or not tool_call_id:
            raise ValueError("run_id and tool_call_id must not be empty")

        key = (run_id, tool_call_id)
        fingerprint = self._fingerprint(tool_name, arguments)

        with self._lock:
            if key in self._records:
                stored_fingerprint, stored_result = self._records[key]

                if stored_fingerprint != fingerprint:
                    raise IdempotencyConflictError(
                        "Same tool call ID used with different operation"
                    )

                return stored_result

            result = operation()
            self._records[key] = (fingerprint, result)
            return result

    def get_recovery(self, run_id: str):
        del run_id
        return None


class PersistentIdempotencyManager(IdempotencyManager):
    """Durable tool-call idempotency with explicit recovery states.

    ``COMPLETED`` calls replay their stored observation. ``IN_PROGRESS`` calls
    are not duplicated. If an operation raises after reservation, the call is
    recorded as ``UNKNOWN`` because an external side effect may have occurred;
    a later resume must stop for reconciliation instead of retrying.
    """

    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_UNKNOWN = "UNKNOWN"

    def __init__(
            self,
            client=None,
            fallback_dir: Optional[Path] = None,
            ttl_seconds: int = _DurableIdempotencyStore.TTL_SECONDS,
    ):
        super().__init__()
        self._store = _DurableIdempotencyStore(
            client=client,
            fallback_dir=fallback_dir,
            ttl_seconds=ttl_seconds,
        )

    def _new_record(
            self,
            run_id: str,
            tool_call_id: str,
            fingerprint: str,
            recovery: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        now = time.time()
        record = {
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "fingerprint": fingerprint,
            "status": self.STATUS_IN_PROGRESS,
            "result": None,
            "recovery": recovery,
            "created_at": now,
            "updated_at": now,
        }
        # Validate serializability before an operation can cause side effects.
        self._store._encode(record)
        return record

    @staticmethod
    def _assert_same_operation(record: Dict[str, Any], fingerprint: str) -> None:
        if record.get("fingerprint") != fingerprint:
            raise IdempotencyConflictError(
                "Same tool call ID used with different operation"
            )

    def _mark_unknown(self, record: Dict[str, Any]) -> None:
        record["status"] = self.STATUS_UNKNOWN
        record["updated_at"] = time.time()
        record["result"] = None
        self._store.update(record)

    def execute(
            self,
            run_id: str,
            tool_call_id: str,
            tool_name: str,
            arguments: dict,
            operation: Callable[[], Any],
            recovery: Optional[Dict[str, Any]] = None,
    ) -> Any:
        if not run_id or not tool_call_id:
            raise ValueError("run_id and tool_call_id must not be empty")

        fingerprint = self._fingerprint(tool_name, arguments)

        with self._lock:
            candidate = self._new_record(
                run_id,
                tool_call_id,
                fingerprint,
                recovery,
            )
            record, owned = self._store.reserve(candidate)
            self._assert_same_operation(record, fingerprint)

            if not owned:
                status = record.get("status")
                if status == self.STATUS_COMPLETED:
                    return record.get("result")
                if status == self.STATUS_UNKNOWN:
                    raise IdempotencyUnknownError(
                        "Tool execution outcome is UNKNOWN; reconciliation is required"
                    )
                if status == self.STATUS_IN_PROGRESS:
                    raise IdempotencyInProgressError(
                        "Tool execution is already in progress"
                    )
                raise IdempotencyStorageError(
                    f"Unsupported idempotency status: {status!r}"
                )

            try:
                result = operation()
            except BaseException:
                # The call was reserved but the caller cannot prove whether an
                # external side effect completed. Preserve that uncertainty.
                self._mark_unknown(record)
                raise

            record["status"] = self.STATUS_COMPLETED
            record["result"] = result
            record["updated_at"] = time.time()
            self._store.update(record)
            return result

    def get_recovery(self, run_id: str):
        records = [
            record
            for record in self._store.records_for_run(run_id)
            if record.get("recovery") is not None
        ]
        if not records:
            return None

        return max(records, key=lambda record: record.get("updated_at", 0))
