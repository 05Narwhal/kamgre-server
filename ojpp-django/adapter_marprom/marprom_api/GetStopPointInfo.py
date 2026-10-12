from typing import List
from typing import Any
from dataclasses import dataclass
import json
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
    StaticData: 'StaticData'
    ListOfLineId: List[int]
    Schedules: List['Schedule']

    @staticmethod
    def from_dict(obj: Any) -> 'Root':
        _Response = Response.from_dict(obj.get("Response"))
        _StaticData = StaticData.from_dict(obj.get("StaticData"))
        _ListOfLineId = obj.get("ListOfLineId")
        _Schedules = [Schedule.from_dict(y) for y in obj.get("Schedules")]
        return Root(_Response, _StaticData, _ListOfLineId, _Schedules)

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
    LineShortName: str
    RouteAndSchedules: List[RouteAndSchedule]

    @staticmethod
    def from_dict(obj: Any) -> 'Schedule':
        _LineId = int(obj.get("LineId"))
        _LineShortName = str(obj.get("LineShortName"))
        _RouteAndSchedules = [RouteAndSchedule.from_dict(y) for y in obj.get("RouteAndSchedules")]
        return Schedule(_LineId, _LineShortName, _RouteAndSchedules)

@dataclass
class StaticData:
    StopPointName: str
    Description: str
    StopPointImgPath: str
    Code: str

    @staticmethod
    def from_dict(obj: Any) -> 'StaticData':
        _StopPointName = str(obj.get("StopPointName"))
        _Description = str(obj.get("Description"))
        _StopPointImgPath = str(obj.get("StopPointImgPath"))
        _Code = str(obj.get("Code"))
        return StaticData(_StopPointName, _Description, _StopPointImgPath, _Code)

# Example Usage
# jsonstring = json.loads(myjsonstring)
# root = Root.from_dict(jsonstring)
