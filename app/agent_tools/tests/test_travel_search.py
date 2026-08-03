# app/agent_tools/tests/test_travel_search.py
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import app.agent_tools.travel_search as ts

TOOL = Path(__file__).resolve().parents[1] / "travel_search.py"


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ts.requests.HTTPError(f"status {self.status_code}")


def test_build_flights_url_includes_params():
    url, params = ts.build_request("flights", origin="SFO", destination="BOS", max_price=300)
    assert url.endswith("/flights")
    assert params == {"origin": "SFO", "destination": "BOS", "max_price": 300}


def test_search_returns_payload(monkeypatch):
    monkeypatch.setenv("TRAVEL_API_URL", "http://mock-travel-api")
    with patch.object(ts.requests, "get", return_value=FakeResp({"flights": [{"flight_no": "OA101"}]})):
        out = ts.search("flights", {"destination": "BOS"})
    assert out == {"flights": [{"flight_no": "OA101"}]}


def test_cli_flights_prints_json(monkeypatch):
    # End-to-end CLI invocation with a stubbed HTTP layer via env pointing nowhere,
    # so assert the argument parsing + error path instead.
    result = subprocess.run(
        [sys.executable, str(TOOL), "flights", "--destination", "BOS", "--max-price", "300"],
        capture_output=True, text=True, env={"TRAVEL_API_URL": "http://127.0.0.1:59999"},
    )
    # No server listening -> exit code 2 and JSON error on stderr.
    assert result.returncode == 2
    assert json.loads(result.stderr)["error"]
