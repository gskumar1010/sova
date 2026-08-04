"""Canned travel dataset. No external calls; deterministic for demos/tests."""

FLIGHTS = [
    {"flight_no": "OA101", "airline": "OpenAir", "origin": "SFO",
     "destination": "BOS", "depart": "2026-09-08T08:00", "arrive": "2026-09-08T16:30", "price_usd": 279},
    {"flight_no": "OA205", "airline": "OpenAir", "origin": "SFO",
     "destination": "BOS", "depart": "2026-09-08T13:15", "arrive": "2026-09-08T21:40", "price_usd": 312},
    {"flight_no": "KT300", "airline": "KataJet", "origin": "SFO",
     "destination": "JFK", "depart": "2026-09-08T09:30", "arrive": "2026-09-08T18:05", "price_usd": 258},
    {"flight_no": "SH410", "airline": "ShellWings", "origin": "ORD",
     "destination": "BOS", "depart": "2026-09-08T07:45", "arrive": "2026-09-08T11:10", "price_usd": 189},
]

HOTELS = [
    {"name": "Harborview Suites", "city": "Boston", "nightly_usd": 219, "rating": 4.5},
    {"name": "Downtown Kata Inn", "city": "Boston", "nightly_usd": 175, "rating": 4.2},
    {"name": "Beacon Hill Grand", "city": "Boston", "nightly_usd": 349, "rating": 4.8},
    {"name": "Midtown OpenStay", "city": "New York", "nightly_usd": 289, "rating": 4.3},
]
