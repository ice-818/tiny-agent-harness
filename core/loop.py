
import json
import time

from core.memory import MemoryManager
from router import ModelRouter
from tools_pkg.executor import execute_tool
from core.trace import create_run_id, log_event


router = ModelRouter()


def run(task: str, max_steps: int = 5, run_id: str = None):

    # 1. 初始化 Agent 运行
    is_resume = run_id is not None

    if run_id is None:
        run_id = create_run_id()

    start_time = time.perf_counter()
    memory = MemoryManager()

    start_step = 1

    messages = [
        {
            "role": "user",
            "content": task
        }
    ]

    # 2. 从已有 Checkpoint 恢复
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
            raise ValueError(
                f"Checkpoint not found: {run_id}"
            )

        if checkpoint["context"].get("status") != "running":
            raise ValueError(
                f"Checkpoint is not resumable: {run_id}"
            )

        start_step = checkpoint["step"]
        messages = checkpoint["context"]["messages"]

    log_event(
        run_id=run_id,
        step=0,
        event="agent_start",
        max_steps=max_steps
    )

    # 3. 统一处理 Checkpoint 保存异常
    def save_checkpoint_safely(step, next_step, status):
        checkpoint_start = time.perf_counter()

        try:
            memory.save_checkpoint(
                session_id=run_id,
                step=next_step,
                context={
                    "messages": messages,
                    "status": status
                }
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

    # 4. Agent 主循环
    for step in range(start_step, max_steps + 1):

        print(f"Agent step:{step}")

        # 5. 调用 LLM
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

        # 6. 处理工具调用
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

            # 7. 执行工具
            tool_start = time.perf_counter()

            try:
                observation = execute_tool(
                    tool_name,
                    arguments
                )

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

            # 8. 保存工具执行结果
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

        # 9. 处理最终回答
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

        # 10. 未知响应类型
        else:
            log_event(
                run_id=run_id,
                step=step,
                event="agent_failed",
                stage="response_parsing",
                error_type="unknown_response_type"
            )

            return "Agent failed: unknown response type"

    # 11. 超出最大执行轮数
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
