def get_weather(city: str) -> str:
    return f"{city} 当前天气：晴，26℃。"


get_weather_tool = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get weather information for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string"
                }
            },
            "required": ["city"]
        }
    }
}