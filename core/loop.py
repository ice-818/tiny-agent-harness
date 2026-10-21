from core.guardrail import check_tool
from tools_pkg.registry import TOOL_REGISTRY
from router import ModelRouter
import  json

router = ModelRouter()

def execute_tool(tool_name : str, arguments: dict):
    action = check_tool(tool_name)
    if action == "allow":
        if tool_name not in TOOL_REGISTRY:
            return f"Tool {tool_name} is not registered"
        tool = TOOL_REGISTRY[tool_name]
        return tool(**arguments)
    elif action =="require_approval":
        return f"Tool {tool_name} requires approval"
    elif action =="deny":
        return f"Tool {tool_name} is denied"
    else:
        return f"Invalid guardrail action: {action}"


def run(task: str, max_steps: int = 5):
    messages = [
        {
            "role":"user",
            "content":task
        }
    ]
    for step in range (1,max_steps + 1):
        print(f"Agent step:{step}")
        response = router.chat(messages)
        if response["type"] =="tool_call":
            tool_name = response["tool_name"]
            arguments = response["arguments"]
            tool_call_id = response["tool_call_id"]

            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(arguments)
                        }
                    }
                ]
            })

            observation = execute_tool(tool_name,arguments)

            messages.append(
                {
                "role":"tool",
                "tool_call_id": tool_call_id,
                "content":str(observation)
                }
            )
        if response["type"] =="final":
            return response["content"]
print(run("东京天气怎么样"))