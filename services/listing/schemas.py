import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CreateVehicleRequest(BaseModel):
    make: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=80)
    year: int = Field(ge=1980, le=2100)
    daily_price_cents: int = Field(gt=0)
    daily_mileage_limit: int = Field(gt=0)
    booking_mode: Literal["instant", "request"] = "instant"


class UpdateVehicleRequest(BaseModel):
    make: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=80)
    year: int | None = Field(default=None, ge=1980, le=2100)
    daily_price_cents: int | None = Field(default=None, gt=0)
    daily_mileage_limit: int | None = Field(default=None, gt=0)
    booking_mode: Literal["instant", "request"] | None = None


class VehicleResponse(BaseModel):
    id: str
    host_id: str
    make: str
    model: str
    year: int
    daily_price_cents: int
    daily_mileage_limit: int
    booking_mode: str
    approval_status: str


class CreateAvailabilityBlockRequest(BaseModel):
    start_date: dt.date
    end_date: dt.date

    @model_validator(mode="after")
    def check_date_order(self) -> "CreateAvailabilityBlockRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class AvailabilityBlockResponse(BaseModel):
    id: str
    vehicle_id: str
    start_date: dt.date
    end_date: dt.date
