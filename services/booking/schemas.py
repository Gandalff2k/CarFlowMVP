import datetime as dt
import uuid

from pydantic import BaseModel, Field, model_validator


class CreateBookingRequest(BaseModel):
    vehicle_id: uuid.UUID
    start_date: dt.date
    end_date: dt.date

    @model_validator(mode="after")
    def check_date_order(self) -> "CreateBookingRequest":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class HandoverRequest(BaseModel):
    odometer: int = Field(ge=0)
    fuel_percent: int = Field(ge=0, le=100)
    photo_url: str = Field(min_length=1, max_length=512)


class ReturnRequest(BaseModel):
    odometer: int = Field(ge=0)
    fuel_percent: int = Field(ge=0, le=100)
    photo_url: str = Field(min_length=1, max_length=512)


class BookingResponse(BaseModel):
    id: str
    vehicle_id: str
    host_id: str
    renter_id: str
    start_date: dt.date
    end_date: dt.date
    daily_price_cents: int
    daily_mileage_limit: int
    booking_mode: str
    status: str
    start_odometer: int | None
    end_odometer: int | None
    start_fuel_percent: int | None
    end_fuel_percent: int | None
    start_photo_url: str | None
    end_photo_url: str | None
    overage_cents: int


class ListBookingsResponse(BaseModel):
    items: list[BookingResponse]
    next_offset: int | None
