from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).resolve().parent.parent / "guardrail.yaml"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def check_tool(tool_name: str) -> str:
    config = load_config()
    tools = config["tools"]
    if tool_name in tools:
        return tools[tool_name]["action"]
    else:
        return "deny"