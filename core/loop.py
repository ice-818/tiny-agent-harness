from core.guardrail import check_tool
from tools import TOOL_REGISTRY

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

def mock_llm(messages):
    response = {
        "type" : "tool_call",
        "tool_name": "calculator",
        "arguments": {
            "a": 20,
            "b": 30,
            "op": "add"
        }
    }
    if len(messages) == 1:
        return response
    else:
        return {
            "type" : "final",
            "content":"50"
        }

def run(task: str, max_steps: int = 5):
    messages = [
        {
            "role":"user",
            "content":task
        }
    ]
    for step in range (1,max_steps + 1):
        print(f"Agent step:{step}")
        response = mock_llm(messages)
        if response["type"] =="tool_call":
            tool_name = response["tool_name"]
            arguments = response["arguments"]
            observation = execute_tool(tool_name,arguments)
            messages.append(
                {
                "role":"tool",
                "content":str(observation)
                }
            )
        if response["type"] =="final":
            return response["content"]
print(run("帮我算20+30"))