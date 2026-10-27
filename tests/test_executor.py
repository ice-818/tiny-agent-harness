from tools_pkg.executor import execute_tool


def test_calculator_success():
    result = execute_tool(
        "calculator",
        {
            "a": 25,
            "b": 8,
            "op": "mul"
        }
    )

    assert result["success"] is True
    assert result["result"] == 200
    assert result["error"] is None
    assert result["error_type"] is None

def test_calculator_validation_error():
    result = execute_tool(
        "calculator",
        {
            "a": 25,
            "b": 8
        }
    )

    assert result["success"] is False
    assert result["result"] is None
    assert result["error_type"] == "validation_error"


def test_calculator_execution_error():
    result = execute_tool(
        "calculator",
        {
            "a": 10,
            "b": 0,
            "op": "div"
        }
    )

    assert result["success"] is False
    assert result["result"] is None
    assert result["error_type"] == "execution_error"


def test_tool_not_found():
    result = execute_tool(
        "unknown_tool",
        {}
    )

    assert result["success"] is False
    assert result["result"] is None
    assert result["error_type"] == "tool_not_found"