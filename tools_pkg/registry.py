from tools_pkg.calculator import calculator, calculator_tool
from tools_pkg.weather import get_weather, get_weather_tool

TOOL_REGISTRY = {
    "calculator": calculator,
    "get_weather": get_weather
}

TOOL_DEFINITIONS = [
    calculator_tool,
    get_weather_tool
]