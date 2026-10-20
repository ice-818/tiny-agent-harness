import os
import json

from dotenv import load_dotenv
from openai import OpenAI
from tools import calculator_tool

class ModelRouter:
    def __init__(self):
        load_dotenv()

        # 本地 Ollama 客户端
        self.local_client = OpenAI(
            base_url="http://127.0.0.1:11434/v1",
            api_key="ollama"
        )

        # 云端 Qwen-Max 客户端
        self.cloud_client = OpenAI(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=os.getenv("DASHSCOPE_API_KEY")
        )

        self.cloud_model = "qwen-max"

        # 本地对话模型
        self.local_model = "qwen2.5:7b-instruct-q4_K_M"
    def chat(self, messages: list, task_type: str = "chat") -> dict:
        if task_type == "reasoning":
            client = self.cloud_client
            model = self.cloud_model
        else:
            client = self.local_client
            model = self.local_model

        response = client.chat.completions.create(
            model=model,
            messages = messages,
            temperature=0.7,
            tools = [calculator_tool]
        )

        message =response.choices[0].message

        if message.tool_calls is None:
            return{
                "type": "final",
                "content":message.content
            }
        else:
            tool_name = message.tool_calls[0].function.name
            arguments = message.tool_calls[0].function.arguments
            arguments = json.loads(arguments)
            tool_call_id = message.tool_calls[0].id
            return{
                "type":"tool_call",
                "tool_call_id":tool_call_id,
                "tool_name":tool_name,
                "arguments": arguments
            }