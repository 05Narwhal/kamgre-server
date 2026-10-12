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
    Stops: List['Stop']

    @staticmethod
    def from_dict(obj: Any) -> 'Root':
        _Response = Response.from_dict(obj.get("Response"))
        _Stops = [Stop.from_dict(y) for y in obj.get("Stops")]
        return Root(_Response, _Stops)

@dataclass
class Stop:
    StopId: int
    Name: str
    Lat: float
    Lon: float

    @staticmethod
    def from_dict(obj: Any) -> 'Stop':
        _StopId = int(obj.get("StopId"))
        _Name = str(obj.get("Name"))
        _Lat = float(obj.get("Lat", 0))  # TODO: null
        _Lon = float(obj.get("Lon", 0))  # TODO: null
        return Stop(_StopId, _Name, _Lat, _Lon)

# Example Usage
# jsonstring = json.loads(myjsonstring)
# root = Root.from_dict(jsonstring)
