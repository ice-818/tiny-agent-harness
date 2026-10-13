import os

from dotenv import load_dotenv
from openai import OpenAI


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
    def chat(self, message: str, task_type: str = "chat") -> str:
        if task_type == "reasoning":
            client = self.cloud_client
            model = self.cloud_model
        else:
            client = self.local_client
            model = self.local_model

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": message
                }
            ],
            temperature=0.7
        )

        return response.choices[0].message.content