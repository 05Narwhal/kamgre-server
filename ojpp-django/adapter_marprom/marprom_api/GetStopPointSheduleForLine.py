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
    Schedules: List['Schedule']

    @staticmethod
    def from_dict(obj: Any) -> 'Root':
        _Response = Response.from_dict(obj.get("Response"))
        _Schedules = [Schedule.from_dict(y) for y in obj.get("Schedules")]
        return Root(_Response, _Schedules)

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
    StopPoint: 'StopPoint'
    ScheduleForLine: List['ScheduleForLine']

    @staticmethod
    def from_dict(obj: Any) -> 'Schedule':
        _StopPoint = StopPoint.from_dict(obj.get("StopPoint"))
        _ScheduleForLine = [ScheduleForLine.from_dict(y) for y in obj.get("ScheduleForLine")]
        return Schedule(_StopPoint, _ScheduleForLine)

@dataclass
class ScheduleForLine:
    LineId: int
    RouteAndSchedules: List['RouteAndSchedule']

    @staticmethod
    def from_dict(obj: Any) -> 'ScheduleForLine':
        _LineId = int(obj.get("LineId"))
        _RouteAndSchedules = [RouteAndSchedule.from_dict(y) for y in obj.get("RouteAndSchedules")]
        return ScheduleForLine(_LineId, _RouteAndSchedules)

@dataclass
class StopPoint:
    StopPointId: int
    Name: str
    Description: str
    Code: str

    @staticmethod
    def from_dict(obj: Any) -> 'StopPoint':
        _StopPointId = int(obj.get("StopPointId"))
        _Name = str(obj.get("Name"))
        _Description = str(obj.get("Description"))
        _Code = str(obj.get("Code"))
        return StopPoint(_StopPointId, _Name, _Description, _Code)

# Example Usage
# jsonstring = json.loads(myjsonstring)
# root = Root.from_dict(jsonstring)
