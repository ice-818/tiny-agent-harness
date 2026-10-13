from router import ModelRouter


def main():
    router = ModelRouter()

    print("=== 测试本地 chat 路由 ===")
    local_response = router.chat(
        "请用一句话解释什么是 AI Agent。",
        task_type="chat"
    )
    print("本地模型回复：", local_response)

    print("\n=== 测试云端 reasoning 路由 ===")
    cloud_response = router.chat(
        "为什么企业级 Agent 需要状态持久化？请简要回答。",
        task_type="reasoning"
    )
    print("云端模型回复：", cloud_response)


if __name__ == "__main__":
    main()