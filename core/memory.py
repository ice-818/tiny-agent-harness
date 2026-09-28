import json
import redis

class MemoryManager:
    def __init__(self):
        # 连接本地 Docker 运行的 Redis
        self.client = redis.Redis(host='127.0.0.1', port=6379, db=0, decode_responses=True)

    def save_history(self, session_id: str, role: str, content: str):
        key = f"history:{session_id}"
        self.client.rpush(key, json.dumps({"role": role, "content": content}))
        self.client.expire(key, 3600)

    def get_history(self, session_id: str):
        key = f"history:{session_id}"
        history = self.client.lrange(key, 0, -1)
        return [json.loads(item) for item in history]

    def save_checkpoint(self, session_id: str, step: int, context: dict):
        key = f"checkpoint:{session_id}"
        self.client.hset(key, mapping={"step": step, "context": json.dumps(context)})
        self.client.expire(key, 3600)

    def get_checkpoint(self, session_id: str):
        key = f"checkpoint:{session_id}"
        data = self.client.hgetall(key)
        if not data:
            return None
        return {"step": int(data["step"]), "context": json.loads(data["context"])}