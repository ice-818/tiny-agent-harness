import json
import time

from core.memory import MemoryManager
from router import ModelRouter
from tools_pkg.executor import execute_tool
from core.trace import create_run_id, log_event


router = ModelRouter()


def run(task: str, max_steps: int = 5, run_id: str = None):

    # 1. 初始化本次 Agent 运行
    is_resume = run_id is not None

    if run_id is None:
        run_id = create_run_id()

    start_time = time.perf_counter()
    memory = MemoryManager()

    # 默认从第 1 轮开始
    start_step = 1

    messages = [
        {
            "role": "user",
            "content": task
        }
    ]

    # 如果指定了 run_id，则尝试从 Redis 恢复
    if is_resume:
        checkpoint = memory.get_checkpoint(run_id)

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

    # 2. Agent 主循环
    for step in range(start_step, max_steps + 1):

        print(f"Agent step:{step}")

        # 3. 调用 LLM，并记录耗时
        llm_start = time.perf_counter()

        try:
            response = router.chat(
                messages,
                run_id = run_id,
                step = step
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

            return f"Agent failed: LLM call error ({type(e).__name__})"

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

        # 4. LLM 请求调用工具
        if response["type"] == "tool_call":

            tool_name = response["tool_name"]
            arguments = response["arguments"]
            tool_call_id = response["tool_call_id"]

            # 将 Assistant 的工具调用加入消息历史
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

            # 5. 执行工具并记录耗时
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

            # 6. 将工具结果转换成 JSON，返回给 LLM
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

            memory.save_checkpoint(
                session_id=run_id,
                step=step + 1,
                context={
                    "messages": messages,
                    "status": "running"
                }
            )

            # 继续下一轮 Agent Loop
            continue

        # 7. LLM 返回最终答案
        elif response["type"] == "final":

            # 将最终回答加入消息历史
            messages.append(
                {
                    "role": "assistant",
                    "content": response["content"]
                }
            )

            # 更新 Checkpoint，标记任务已完成
            memory.save_checkpoint(
                session_id=run_id,
                step=step,
                context={
                    "messages": messages,
                    "status": "completed"
                }
            )

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

        # 8. 不认识的响应类型，安全终止
        else:
            log_event(
                run_id=run_id,
                step=step,
                event="agent_failed",
                stage="response_parsing",
                error_type="unknown_response_type"
                )

            return "Agent failed: unknown response type"

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