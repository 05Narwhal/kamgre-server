from typing import List
from typing import Any
from dataclasses import dataclass
import json


@dataclass
class Line:
    LineId: int
    Code: str
    Description: str
    Color: str
    routes: List['Route']

    @staticmethod
    def from_dict(obj: Any) -> 'Line':
        _LineId = int(obj.get("LineId"))
        _Code = str(obj.get("Code"))
        _Description = str(obj.get("Description"))
        _Color = str(obj.get("Color"))
        _routes = [Route.from_dict(y) for y in obj.get("routes")]
        return Line(_LineId, _Code, _Description, _Color, _routes)

@dataclass
class Response:
    Date: str
    Status: int
    Message: str

    @staticmethod
    def from_dict(obj: Any) -> 'Response':
        _Date = str(obj.get("Date"))
        _Status = int(obj.get("Status"))
        _Message = str(obj.get("Message"))
        return Response(_Date, _Status, _Message)

@dataclass
class Root:
    Response: Response
    Lines: List[Line]

    @staticmethod
    def from_dict(obj: Any) -> 'Root':
        _Response = Response.from_dict(obj.get("Response"))
        _Lines = [Line.from_dict(y) for y in obj.get("Lines")]
        return Root(_Response, _Lines)

@dataclass
class Route:
    RouteId: int
    LineId: int
    HeadsignName: str

    @staticmethod
    def from_dict(obj: Any) -> 'Route':
        _RouteId = int(obj.get("RouteId"))
        _LineId = int(obj.get("LineId"))
        _HeadsignName = str(obj.get("HeadsignName"))
        return Route(_RouteId, _LineId, _HeadsignName)

# Example Usage
# jsonstring = json.loads(myjsonstring)
# root = Root.from_dict(jsonstring)
