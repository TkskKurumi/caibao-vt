from dataclasses import dataclass
from typing import List, Dict



@dataclass
class OAIParam:
    name: str
    param_type: str
    description: str
    required: bool
    def to_oai(self):
        return {
            "name": self.name,
            "type": self.param_type,
            "description": self.description
        }
@dataclass
class OAIFunction:
    name: str
    description: str
    params: List[OAIParam]
    def to_oai(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {i.name: i.to_oai() for i in self.params},
                    "required": [i.name for i in self.params if i.required]
                }
            }
        }

"""example
location_param = OAIParam("location", "str", "...", True)
get_weather_fn = OAIFunction(name="get_weather", description="...", params=[location_param])

equals following:
{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get weather of a location.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city name, e.g. San Francisco, CA",
                }
            },
            "required": ["location"]
        }
    }
}
"""