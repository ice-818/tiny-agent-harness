def calculator(a: float, b: float, op: str) -> float:
    if op == "add":
        return a + b
    if op == "sub":
        return a - b
    if op == "mul":
        return a * b
    if op == "div":
        if b == 0:
            raise ValueError("除数不能为 0")
        return a / b

    raise ValueError(f"不支持的运算类型: {op}")


calculator_tool = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Perform basic arithmetic operations",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {
                    "type": "number"
                },
                "b": {
                    "type": "number"
                },
                "op": {
                    "type": "string",
                    "enum": ["add", "sub", "mul", "div"]
                }
            },
            "required": ["a", "b", "op"]
        }
    }
}