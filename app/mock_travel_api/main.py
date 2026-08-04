"""Mock Travel API: canned flights + hotels for the secure-agent demo."""
from fastapi import FastAPI

from app.mock_travel_api.data import FLIGHTS, HOTELS

app = FastAPI(title="Mock Travel API", version="1.0.0")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/flights")
def flights(origin: str | None = None, destination: str | None = None,
            max_price: int | None = None):
    results = FLIGHTS
    if origin:
        results = [f for f in results if f["origin"] == origin]
    if destination:
        results = [f for f in results if f["destination"] == destination]
    if max_price is not None:
        results = [f for f in results if f["price_usd"] <= max_price]
    return {"flights": results}


@app.get("/hotels")
def hotels(city: str | None = None, max_price: int | None = None):
    results = HOTELS
    if city:
        results = [h for h in results if h["city"] == city]
    if max_price is not None:
        results = [h for h in results if h["nightly_usd"] <= max_price]
    return {"hotels": results}
