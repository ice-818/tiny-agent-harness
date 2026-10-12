from openai import OpenAI


class ModelRouter:
    def __init__(self):
        # 本地 Ollama 客户端
        self.local_client = OpenAI(
            base_url="http://127.0.0.1:11434/v1",
            api_key="ollama"
        )

        # 本地对话模型
        self.local_model = "qwen2.5:7b-instruct-q4_K_M"
    def chat(self, message: str) -> str:
        response = self.local_client.chat.completions.create(
            model=self.local_model,
            messages=[
                {"role": "user","content": message
                }
            ],
            temperature=0.7
        )
        return response.choices[0].message.content