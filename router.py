import os
import json

from dotenv import load_dotenv
from openai import (
    OpenAI,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
    RateLimitError,
)

from core.retry import retry_call
from tools_pkg.registry import TOOL_DEFINITIONS


class ModelRouter:

    def __init__(self):
        load_dotenv()

        self.local_client = OpenAI(
            base_url="http://127.0.0.1:11434/v1",
            api_key="ollama",
            timeout=30.0,
            max_retries=0
        )

        self.cloud_client = OpenAI(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            timeout=60.0,
            max_retries=0
        )

        self.local_model = "qwen2.5:7b-instruct-q4_K_M"
        self.cloud_model = "qwen-max"

    def chat(
        self,
        messages: list,
        task_type: str = "chat",
        run_id = None,
        step = 0
    ) -> dict:

        # 1. 显式选择模型
        if task_type == "chat":
            client = self.local_client
            model = self.local_model

        elif task_type == "reasoning":
            client = self.cloud_client
            model = self.cloud_model

        else:
            raise ValueError(f"Unsupported task_type: {task_type}")

        # 2. 封装单次模型请求
        def call_model():
            return client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                tools=TOOL_DEFINITIONS
            )

        # 3. Retry：只处理允许重试的异常
        response = retry_call(
            func=call_model,
            max_attempts=3,
            base_delay=0.5,
            retryable_exceptions=(
                APITimeoutError,
                APIConnectionError,
                InternalServerError,
                RateLimitError
            ),
            run_id = run_id,
            step = step
        )

        # 4. 解析模型响应
        message = response.choices[0].message

        if not message.tool_calls:
            return {
                "type": "final",
                "content": message.content
            }

        tool_call = message.tool_calls[0]

        return {
            "type": "tool_call",
            "tool_call_id": tool_call.id,
            "tool_name": tool_call.function.name,
            "arguments": json.loads(
                tool_call.function.arguments
            )
        }