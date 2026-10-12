from typing import List
from typing import Any
from dataclasses import dataclass
import json
@dataclass
class ShapeNode:
    SequenceNo: int
    Lat: float
    Lon: float
    StopPointID: int
    Name: str
    Description: str
    StopId: int
    Shedules: List['Schedule']

    @staticmethod
    def from_dict(obj: Any) -> 'ShapeNode':
        _SequenceNo = int(obj.get("SequenceNo"))
        _Lat = float(obj.get("Lat"))
        _Lon = float(obj.get("Lon"))
        _StopPointID = int(obj.get("StopPointID")) if "StopPointID" in obj else None
        _Name = str(obj["Name"]) if "Name" in obj else None
        _Description = str(obj["Description"]) if "Description" in obj else None
        _StopId = int(obj["StopId"]) if "StopId" in obj else None
        _Shedules = [Schedule.from_dict(y) for y in obj["Shedules"]] if "Shedules" in obj else None
        return ShapeNode(_SequenceNo, _Lat, _Lon, _StopPointID, _Name, _Description, _StopId, _Shedules)

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

@dataclass
class RouteAndSchedule:
    Direction: str
    Departures: List[str]

    @staticmethod
    def from_dict(obj: Any) -> 'RouteAndSchedule':
        _Direction = str(obj.get("Direction"))
        _Departures = obj.get("Departures")
        return RouteAndSchedule(_Direction, _Departures)

@dataclass
class Schedule:
    LineId: int
    RouteAndSchedules: List[RouteAndSchedule]

    @staticmethod
    def from_dict(obj: Any) -> 'Schedule':
        _LineId = int(obj.get("LineId"))
        _RouteAndSchedules = [RouteAndSchedule.from_dict(y) for y in obj.get("RouteAndSchedules")]
        return Schedule(_LineId, _RouteAndSchedules)

# Example Usage
# jsonstring = json.loads(myjsonstring)
# root = Root.from_dict(jsonstring)
