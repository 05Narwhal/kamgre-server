from typing import List
from typing import Any
from dataclasses import dataclass
import json
@dataclass
class ArrivalsForStopPoint:
    Description: str
    LineId: int
    LineCode: str
    LineDescription: str
    ArrivalTime: str
    ETAMin: int
    DelayMin: int
    BusCode: str

    @staticmethod
    def from_dict(obj: Any) -> 'ArrivalsForStopPoint':
        _Description = str(obj.get("Description"))
        _LineId = int(obj.get("LineId"))
        _LineCode = str(obj.get("LineCode"))
        _LineDescription = str(obj.get("LineDescription"))
        _ArrivalTime = str(obj.get("ArrivalTime"))
        _ETAMin = int(obj["ETAMin"]) if 'ETAMin' in obj else None
        _DelayMin = int(obj.get("DelayMin", "0"))
        _BusCode = str(obj.get("BusCode"))
        return ArrivalsForStopPoint(_Description, _LineId, _LineCode, _LineDescription, _ArrivalTime, _ETAMin, _DelayMin, _BusCode)

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
    ArrivalsForStopPoints: List[ArrivalsForStopPoint]

    @staticmethod
    def from_dict(obj: Any) -> 'Root':
        _Response = Response.from_dict(obj.get("Response"))
        _ArrivalsForStopPoints = [ArrivalsForStopPoint.from_dict(y) for y in obj.get("ArrivalsForStopPoints")]
        return Root(_Response, _ArrivalsForStopPoints)

# Example Usage
# jsonstring = json.loads(myjsonstring)
# root = Root.from_dict(jsonstring)
