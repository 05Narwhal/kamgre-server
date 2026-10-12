from typing import List
from typing import Any
from dataclasses import dataclass
import json
@dataclass
class ShapeNode:
    SequenceNo: int
    Lat: float
    Lon: float
    StopId: int
    StopPointId: int

    @staticmethod
    def from_dict(obj: Any) -> 'ShapeNode':
        _SequenceNo = int(obj.get("SequenceNo"))
        _Lat = float(obj.get("Lat"))
        _Lon = float(obj.get("Lon"))
        _StopId = int(obj.get("StopId"))
        _StopPointId = int(obj.get("StopPointId"))
        return ShapeNode(_SequenceNo, _Lat, _Lon, _StopId, _StopPointId)

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
    Routes: List['Route']

    @staticmethod
    def from_dict(obj: Any) -> 'Root':
        _Response = Response.from_dict(obj.get("Response"))
        _Routes = [Route.from_dict(y) for y in obj.get("Routes")]
        return Root(_Response, _Routes)

@dataclass
class Route:
    RouteId: int
    LineId: int
    HeadsignName: str
    ListOfShapeNodes: List[ShapeNode]

    @staticmethod
    def from_dict(obj: Any) -> 'Route':
        _RouteId = int(obj.get("RouteId"))
        _LineId = int(obj.get("LineId"))
        _HeadsignName = str(obj.get("HeadsignName"))
        _ListOfShapeNodes = [ShapeNode.from_dict(y) for y in obj.get("ListOfShapeNodes")]
        return Route(_RouteId, _LineId, _HeadsignName, _ListOfShapeNodes)

# Example Usage
# jsonstring = json.loads(myjsonstring)
# root = Root.from_dict(jsonstring)
