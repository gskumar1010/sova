# app/mock-travel-api/tests/test_api.py
from fastapi.testclient import TestClient
from app.mock_travel_api.main import app  # noqa: E402

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_flights_returns_matches_filtered_by_price():
    r = client.get("/flights", params={"origin": "SFO", "destination": "BOS", "max_price": 300})
    assert r.status_code == 200
    flights = r.json()["flights"]
    assert len(flights) >= 1
    for f in flights:
        assert f["origin"] == "SFO"
        assert f["destination"] == "BOS"
        assert f["price_usd"] <= 300


def test_flights_no_params_returns_all():
    r = client.get("/flights")
    assert r.status_code == 200
    assert len(r.json()["flights"]) >= 1


def test_hotels_filtered_by_city_and_price():
    r = client.get("/hotels", params={"city": "Boston", "max_price": 250})
    assert r.status_code == 200
    hotels = r.json()["hotels"]
    assert len(hotels) >= 1
    for h in hotels:
        assert h["city"] == "Boston"
        assert h["nightly_usd"] <= 250
