def vehicle_to_document(data: dict) -> dict:
    return {
        "vehicle_id": data["vehicle_id"],
        "host_id": data["host_id"],
        "make": data["make"],
        "model": data["model"],
        "year": data["year"],
        "daily_price_cents": data["daily_price_cents"],
        "daily_mileage_limit": data["daily_mileage_limit"],
        "booking_mode": data["booking_mode"],
        "location": {"lat": data["latitude"], "lon": data["longitude"]},
    }
