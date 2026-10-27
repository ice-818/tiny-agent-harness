
import sys

from core.loop import run


TASK = "请使用 calculator 工具计算25乘以8，并告诉我结果。"


def main():
    print("=" * 50)
    print("Tiny Agent Harness - Checkpoint Resume Demo")
    print("=" * 50)

    if len(sys.argv) == 1:
        print("\n[阶段一] 执行第一轮 Agent")
        print("请从 agent_start 日志中记录实际 run_id。\n")

        result = run(
            task=TASK,
            max_steps=1
        )

        print(f"\n第一阶段结果：{result}")
        print("\n下一步：使用实际 run_id 执行恢复。")

    elif len(sys.argv) == 2:
        run_id = sys.argv[1]

        print(f"\n[阶段二] 恢复 Agent")
        print(f"Run ID: {run_id}\n")

        result = run(
            task=TASK,
            max_steps=5,
            run_id=run_id
        )

        print(f"\n恢复结果：{result}")

    else:
        print("用法：python demo_resume.py [run_id]")
        sys.exit(1)


if __name__ == "__main__":
    main()
