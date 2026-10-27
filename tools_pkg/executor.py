from core.guardrail import check_tool
from tools_pkg.registry import TOOL_REGISTRY, TOOL_SCHEMA_REGISTRY
from tools_pkg.validator import validate_arguments


def execute_tool(tool_name: str, arguments: dict):

    if tool_name not in TOOL_REGISTRY:
        return {
            "success": False,
            "result": None,
            "error": f"Tool {tool_name} is not registered",
            "error_type": "tool_not_found"
        }

    action = check_tool(tool_name)

    if action == "allow":
        schema = TOOL_SCHEMA_REGISTRY[tool_name]

        is_valid, error = validate_arguments(arguments, schema)

        if not is_valid:
            return {
                "success": False,
                "result": None,
                "error": error,
                "error_type": "validation_error"
            }

        tool = TOOL_REGISTRY[tool_name]

        try:
            result = tool(**arguments)

            return {
                "success": True,
                "result": result,
                "error": None,
                "error_type": None
            }

        except Exception as e:
            return {
                "success": False,
                "result": None,
                "error": str(e),
                "error_type": "execution_error"
            }

    elif action == "require_approval":
        return {
            "success": False,
            "result": None,
            "error": f"Tool {tool_name} requires approval",
            "error_type": "approval_required"
        }

    elif action == "deny":
        return {
            "success": False,
            "result": None,
            "error": f"Tool {tool_name} is denied",
            "error_type": "permission_denied"
        }

    else:
        return {
            "success": False,
            "result": None,
            "error": f"Invalid guardrail action: {action}",
            "error_type": "guardrail_error"
        }