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
    Vehicles: List['Vehicle']

    @staticmethod
    def from_dict(obj: Any) -> 'Root':
        _Response = Response.from_dict(obj.get("Response"))
        _Vehicles = [Vehicle.from_dict(y) for y in obj.get("Vehicles")]
        return Root(_Response, _Vehicles)

@dataclass
class Vehicle:
    DeviceId: int
    BusCode: str
    RouteId: int
    LineId: int
    Lat: float
    Lon: float
    NextStopPointId: int
    ETA: int
    Predicted: int
    DirectionDescription: str
    Direction: int

    @staticmethod
    def from_dict(obj: Any) -> 'Vehicle':
        _DeviceId = int(obj.get("DeviceId"))
        _BusCode = str(obj.get("BusCode"))
        _RouteId = int(obj.get("RouteId"))
        _LineId = int(obj.get("LineId"))
        _Lat = float(obj.get("Lat"))
        _Lon = float(obj.get("Lon"))
        _NextStopPointId = int(obj.get("NextStopPointId"))
        _ETA = int(obj.get("ETA"))
        _Predicted = int(obj.get("Predicted"))
        _DirectionDescription = str(obj.get("DirectionDescription"))
        _Direction = int(obj.get("Direction"))
        return Vehicle(_DeviceId, _BusCode, _RouteId, _LineId, _Lat, _Lon, _NextStopPointId, _ETA, _Predicted, _DirectionDescription, _Direction)

# Example Usage
# jsonstring = json.loads(myjsonstring)
# root = Root.from_dict(jsonstring)
