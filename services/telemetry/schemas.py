import datetime as dt

from pydantic import BaseModel, Field


class TelemetryPacket(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    speed_kph: float = Field(ge=0, le=400)
    recorded_at: dt.datetime


class VehicleLocationResponse(BaseModel):
    vehicle_id: str
    lat: float
    lng: float
    recorded_at: str
