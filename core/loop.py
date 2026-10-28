import json
import time

from core.memory import MemoryManager
from router import ModelRouter
from tools_pkg.executor import execute_tool
from core.trace import create_run_id, log_event
from core.checkpoint_validator import validate_checkpoint, InvalidCheckpointError
from core.idempotency import (
    IdempotencyManager,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyUnknownError,
    PersistentIdempotencyManager,
)

router = ModelRouter()
idempotency_manager = PersistentIdempotencyManager()

def run(
        task: str,
        max_steps: int = 5,
        run_id: str = None,
        resume: bool = None,
):

    # 1. Initialize the Agent run
    is_resume = run_id is not None if resume is None else resume

    if is_resume and run_id is None:
        raise ValueError("run_id is required when resume=True")

    if run_id is None:
        run_id = create_run_id()

    start_time = time.perf_counter()
    memory = MemoryManager()

    log_event(
        run_id=run_id,
        step=0,
        event="agent_start"
    )

    start_step = 1

    messages = [
        {
            "role": "user",
            "content": task
        }
    ]

    # 2. Handle checkpoint-save errors consistently.
    def save_checkpoint_safely(step, next_step, status, **extra_context):
        checkpoint_start = time.perf_counter()

        try:
            context = {
                "messages": messages,
                "status": status,
                **extra_context,
            }
            memory.save_checkpoint(
                session_id=run_id,
                step=next_step,
                context=context,
            )

            return True

        except Exception as e:
            duration_ms = round(
                (time.perf_counter() - checkpoint_start) * 1000,
                2
            )

            log_event(
                run_id=run_id,
                step=step,
                event="agent_failed",
                stage="checkpoint_save",
                error_type=type(e).__name__,
                duration_ms=duration_ms
            )

            return (
                f"Agent failed: checkpoint save error "
                f"({type(e).__name__})"
            )

    # 3. Restore from a checkpoint. If the process died after a durable tool
    # reservation but before checkpointing its observation, rebuild the state
    # from the idempotency journal instead of executing the tool again.
    if is_resume:
        recovery_start = time.perf_counter()

        try:
            checkpoint = memory.get_checkpoint(run_id)

        except Exception as e:
            duration_ms = round(
                (time.perf_counter() - recovery_start) * 1000,
                2
            )

            log_event(
                run_id=run_id,
                step=0,
                event="agent_failed",
                stage="checkpoint_recovery",
                error_type=type(e).__name__,
                duration_ms=duration_ms
            )

            return (
                f"Agent failed: checkpoint recovery error "
                f"({type(e).__name__})"
            )

        if checkpoint is None:
            try:
                idempotency_recovery = idempotency_manager.get_recovery(run_id)
            except Exception as e:
                log_event(
                    run_id=run_id,
                    step=0,
                    event="agent_failed",
                    stage="idempotency_recovery",
                    error_type=type(e).__name__,
                )
                return (
                    f"Agent failed: idempotency recovery error "
                    f"({type(e).__name__})"
                )

            # Preserve the historical error when neither persistence layer
            # knows this run.
            if idempotency_recovery is None:
                raise ValueError(f"Checkpoint not found: {run_id}")

            recovery = idempotency_recovery.get("recovery")
            recovery_status = idempotency_recovery.get("status")

            if (
                    not isinstance(recovery, dict)
                    or type(recovery.get("step")) is not int
                    or recovery["step"] < 1
                    or not isinstance(recovery.get("messages"), list)
                    or not recovery["messages"]
            ):
                log_event(
                    run_id=run_id,
                    step=0,
                    event="agent_failed",
                    stage="idempotency_recovery",
                    error_type="invalid_recovery_record",
                )
                return "Agent failed: invalid idempotency recovery record"

            messages = recovery["messages"]
            recovery_step = recovery["step"]
            tool_call_id = idempotency_recovery["tool_call_id"]

            if recovery_status == PersistentIdempotencyManager.STATUS_COMPLETED:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": json.dumps(
                            idempotency_recovery.get("result"),
                            ensure_ascii=False,
                        ),
                    }
                )
                start_step = recovery_step + 1
                checkpoint_result = save_checkpoint_safely(
                    step=recovery_step,
                    next_step=start_step,
                    status="running",
                    idempotency_recovery={
                        "tool_call_id": tool_call_id,
                        "status": recovery_status,
                    },
                )
                if checkpoint_result is not True:
                    return checkpoint_result

                log_event(
                    run_id=run_id,
                    step=recovery_step,
                    event="idempotency_recovered",
                    tool_call_id=tool_call_id,
                )

            elif recovery_status == PersistentIdempotencyManager.STATUS_UNKNOWN:
                checkpoint_result = save_checkpoint_safely(
                    step=recovery_step,
                    next_step=recovery_step,
                    status="needs_manual_reconciliation",
                    idempotency_recovery={
                        "tool_call_id": tool_call_id,
                        "status": recovery_status,
                    },
                )
                if checkpoint_result is not True:
                    return checkpoint_result

                log_event(
                    run_id=run_id,
                    step=recovery_step,
                    event="agent_stopped",
                    reason="tool_execution_unknown",
                    tool_call_id=tool_call_id,
                )
                return (
                    "Agent stopped: tool execution state unknown; "
                    "manual reconciliation required"
                )

            elif recovery_status == PersistentIdempotencyManager.STATUS_IN_PROGRESS:
                log_event(
                    run_id=run_id,
                    step=recovery_step,
                    event="agent_stopped",
                    reason="tool_execution_in_progress",
                    tool_call_id=tool_call_id,
                )
                return "Agent stopped: tool execution in progress; retry later"

            else:
                log_event(
                    run_id=run_id,
                    step=recovery_step,
                    event="agent_failed",
                    stage="idempotency_recovery",
                    error_type="unsupported_idempotency_status",
                )
                return "Agent failed: unsupported idempotency recovery status"

        else:
            # A completed checkpoint is intentionally not resumable. A known
            # UNKNOWN outcome also cannot be retried automatically.
            if (
                    isinstance(checkpoint, dict)
                    and isinstance(checkpoint.get("context"), dict)
            ):
                status = checkpoint["context"].get("status")
                if status == "completed":
                    raise ValueError(f"Checkpoint is not resumable: {run_id}")
                if status == "needs_manual_reconciliation":
                    return (
                        "Agent stopped: tool execution state unknown; "
                        "manual reconciliation required"
                    )

            validation_start = time.perf_counter()

            try:
                start_step, messages = validate_checkpoint(
                    checkpoint,
                    max_steps=max_steps
                )

            except InvalidCheckpointError as e:
                duration_ms = round(
                    (time.perf_counter() - validation_start) * 1000,
                    2
                )

                log_event(
                    run_id=run_id,
                    step=0,
                    event="agent_failed",
                    stage="checkpoint_validation",
                    error_type=type(e).__name__,
                    duration_ms=duration_ms
                )

                return (
                    f"Agent failed: invalid checkpoint "
                    f"({type(e).__name__})"
                )

    # 4. Agent main loop
    for step in range(start_step, max_steps + 1):

        print(f"Agent step:{step}")

        # 5. Call the LLM
        llm_start = time.perf_counter()

        try:
            response = router.chat(
                messages,
                run_id=run_id,
                step=step
            )

        except Exception as e:
            duration_ms = round(
                (time.perf_counter() - llm_start) * 1000,
                2
            )

            log_event(
                run_id=run_id,
                step=step,
                event="agent_failed",
                stage="llm_call",
                error_type=type(e).__name__,
                duration_ms=duration_ms
            )

            return (
                f"Agent failed: LLM call error "
                f"({type(e).__name__})"
            )

        llm_duration_ms = round(
            (time.perf_counter() - llm_start) * 1000,
            2
        )

        log_event(
            run_id=run_id,
            step=step,
            event="llm_call",
            duration_ms=llm_duration_ms,
            response_type=response["type"]
        )

        # 6. Process a tool call
        if response["type"] == "tool_call":

            tool_name = response["tool_name"]
            arguments = response["arguments"]
            tool_call_id = response["tool_call_id"]

            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(
                                    arguments,
                                    ensure_ascii=False
                                )
                            }
                        }
                    ]
                }
            )

            # 7. Execute the tool
            tool_start = time.perf_counter()

            try:
                observation = idempotency_manager.execute(
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    operation=lambda: execute_tool(
                        tool_name,
                        arguments
                    ),
                    recovery={
                        "step": step,
                        "messages": messages,
                    },
                )

            except IdempotencyConflictError as e:
                duration_ms = round(
                    (time.perf_counter() - tool_start) * 1000,
                    2
                )

                log_event(
                    run_id=run_id,
                    step=step,
                    event="agent_failed",
                    stage="idempotency_conflict",
                    error_type=type(e).__name__,
                    duration_ms=duration_ms
                )

                return "Agent failed: idempotency conflict"

            except IdempotencyUnknownError as e:
                duration_ms = round(
                    (time.perf_counter() - tool_start) * 1000,
                    2
                )

                checkpoint_result = save_checkpoint_safely(
                    step=step,
                    next_step=step,
                    status="needs_manual_reconciliation",
                    idempotency_recovery={
                        "tool_call_id": tool_call_id,
                        "status": "UNKNOWN",
                    },
                )
                if checkpoint_result is not True:
                    return checkpoint_result

                log_event(
                    run_id=run_id,
                    step=step,
                    event="agent_stopped",
                    reason="tool_execution_unknown",
                    tool_call_id=tool_call_id,
                    error_type=type(e).__name__,
                    duration_ms=duration_ms
                )

                return (
                    "Agent stopped: tool execution state unknown; "
                    "manual reconciliation required"
                )

            except IdempotencyInProgressError as e:
                duration_ms = round(
                    (time.perf_counter() - tool_start) * 1000,
                    2
                )

                log_event(
                    run_id=run_id,
                    step=step,
                    event="agent_stopped",
                    reason="tool_execution_in_progress",
                    tool_call_id=tool_call_id,
                    error_type=type(e).__name__,
                    duration_ms=duration_ms
                )

                return "Agent stopped: tool execution in progress; retry later"

            except Exception as e:
                duration_ms = round(
                    (time.perf_counter() - tool_start) * 1000,
                    2
                )

                log_event(
                    run_id=run_id,
                    step=step,
                    event="agent_failed",
                    stage="tool_execution",
                    error_type=type(e).__name__,
                    duration_ms=duration_ms
                )

                return (
                    f"Agent failed: tool execution error "
                    f"({type(e).__name__})"
                )

            tool_duration_ms = round(
                (time.perf_counter() - tool_start) * 1000,
                2
            )

            log_event(
                run_id=run_id,
                step=step,
                event="tool_result",
                tool_name=tool_name,
                success=observation["success"],
                error_type=observation["error_type"],
                duration_ms=tool_duration_ms
            )

            # 8. Save the tool result
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(
                        observation,
                        ensure_ascii=False
                    )
                }
            )

            checkpoint_result = save_checkpoint_safely(
                step=step,
                next_step=step + 1,
                status="running"
            )

            if checkpoint_result is not True:
                return checkpoint_result

            continue

        # 9. Process a final answer
        elif response["type"] == "final":

            messages.append(
                {
                    "role": "assistant",
                    "content": response["content"]
                }
            )

            checkpoint_result = save_checkpoint_safely(
                step=step,
                next_step=step,
                status="completed"
            )

            if checkpoint_result is not True:
                return checkpoint_result

            total_duration_ms = round(
                (time.perf_counter() - start_time) * 1000,
                2
            )

            log_event(
                run_id=run_id,
                step=step,
                event="agent_finish",
                duration_ms=total_duration_ms
            )

            return response["content"]

        # 10. Unknown response type
        else:
            log_event(
                run_id=run_id,
                step=step,
                event="agent_failed",
                stage="response_parsing",
                error_type="unknown_response_type"
            )

            return "Agent failed: unknown response type"

    # 11. Maximum execution steps exceeded
    log_event(
        run_id=run_id,
        step=max_steps,
        event="agent_stopped",
        reason="max_steps_exceeded",
        duration_ms=round(
            (time.perf_counter() - start_time) * 1000,
            2
        )
    )

    return f"Agent stopped: exceeded max steps ({max_steps})"


if __name__ == "__main__":
    print(run("帮我算25乘以8"))
