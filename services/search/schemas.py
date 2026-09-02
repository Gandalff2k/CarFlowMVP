from pydantic import BaseModel


class VehicleSearchResult(BaseModel):
    vehicle_id: str
    host_id: str
    make: str
    model: str
    year: int
    daily_price_cents: int
    daily_mileage_limit: int
    booking_mode: str
    latitude: float
    longitude: float


class SearchResponse(BaseModel):
    items: list[VehicleSearchResult]


def document_to_result(document: dict) -> VehicleSearchResult:
    return VehicleSearchResult(
        vehicle_id=document["vehicle_id"],
        host_id=document["host_id"],
        make=document["make"],
        model=document["model"],
        year=document["year"],
        daily_price_cents=document["daily_price_cents"],
        daily_mileage_limit=document["daily_mileage_limit"],
        booking_mode=document["booking_mode"],
        latitude=document["location"]["lat"],
        longitude=document["location"]["lon"],
    )
