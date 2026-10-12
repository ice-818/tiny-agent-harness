from router import ModelRouter


def main():
    router = ModelRouter()

    print("正在调用本地 Ollama 模型...")

    response = router.chat("你好，请用一句话介绍什么是 AI Agent。")

    print("模型回复：", response)


if __name__ == "__main__":
    main()