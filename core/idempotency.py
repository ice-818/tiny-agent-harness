
import json
import threading
from typing import Callable, Any


class IdempotencyConflictError(ValueError):
    """Same call identity used with different tool or arguments."""


class IdempotencyManager:
    """
    In-process tool call deduplication.

    This implementation is thread-safe for one manager instance.
    It is not durable across process restarts.
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
    ) -> Any:

        if not run_id or not tool_call_id:
            raise ValueError(
                "run_id and tool_call_id must not be empty"
            )

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

            self._records[key] = (
                fingerprint,
                result,
            )

            return result

