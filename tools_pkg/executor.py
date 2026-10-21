from core.guardrail import check_tool
from tools_pkg.registry import TOOL_REGISTRY, TOOL_SCHEMA_REGISTRY
from tools_pkg.validator import validate_arguments


def execute_tool(tool_name: str, arguments: dict):
    action = check_tool(tool_name)

    if action == "allow":
        if tool_name not in TOOL_REGISTRY:
            return f"Tool {tool_name} is not registered"

        schema = TOOL_SCHEMA_REGISTRY[tool_name]

        is_valid, error = validate_arguments(arguments, schema)

        if not is_valid:
            return f"Invalid tool arguments: {error}"

        tool = TOOL_REGISTRY[tool_name]

        try:
            return tool(**arguments)
        except Exception as e:
            return f"Tool execution failed: {e}"

    elif action == "require_approval":
        return f"Tool {tool_name} requires approval"

    elif action == "deny":
        return f"Tool {tool_name} is denied"

    else:
        return f"Invalid guardrail action: {action}"