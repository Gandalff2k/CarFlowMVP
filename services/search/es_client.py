from elasticsearch import AsyncElasticsearch

INDEX_MAPPING = {
    "properties": {
        "vehicle_id": {"type": "keyword"},
        "host_id": {"type": "keyword"},
        "make": {"type": "keyword"},
        "model": {"type": "keyword"},
        "year": {"type": "integer"},
        "daily_price_cents": {"type": "integer"},
        "daily_mileage_limit": {"type": "integer"},
        "booking_mode": {"type": "keyword"},
        "location": {"type": "geo_point"},
    }
}


def create_es_client(url: str) -> AsyncElasticsearch:
    return AsyncElasticsearch(url)


async def ensure_index(es: AsyncElasticsearch, index_name: str) -> None:
    if not await es.indices.exists(index=index_name):
        await es.indices.create(index=index_name, mappings=INDEX_MAPPING)
