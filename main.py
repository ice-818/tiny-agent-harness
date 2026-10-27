
from core.loop import run


def main():
    print("=" * 50)
    print("Tiny Agent Harness")
    print("AI Agent Runtime Demo")
    print("=" * 50)

    task = "请使用工具计算25乘以8，并告诉我结果。"

    print(f"\n用户任务：{task}")
    print("\nAgent 开始执行...\n")

    result = run(
        task=task,
        max_steps=5
    )

    print("\n" + "=" * 50)
    print("Agent 最终结果")
    print("=" * 50)
    print(result)


if __name__ == "__main__":
    main()
