# app/agent_tools/travel_search.py
"""Travel search CLI used by the sandboxed OpenCode agent.

Calls the Mock Travel API. Network egress from this script is governed by the
OpenShell policy proxy: only the allowlisted mock-travel-api endpoint succeeds.
"""
import argparse
import json
import os
import sys

import requests

# Port 8080 is required: the OpenShell egress policy allowlists
# mock-travel-api:8080 exactly, and the Service exposes 8080. Any other port
# (e.g. the default 80) is denied by the policy proxy.
DEFAULT_BASE = "http://mock-travel-api:8080"


def base_url() -> str:
    return os.environ.get("TRAVEL_API_URL", DEFAULT_BASE).rstrip("/")


def build_request(kind: str, origin=None, destination=None, city=None, max_price=None):
    params = {}
    if kind == "flights":
        if origin:
            params["origin"] = origin
        if destination:
            params["destination"] = destination
    elif kind == "hotels":
        if city:
            params["city"] = city
    if max_price is not None:
        params["max_price"] = max_price
    return f"{base_url()}/{kind}", params


def search(kind: str, params: dict) -> dict:
    url = f"{base_url()}/{kind}"
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Search flights or hotels.")
    sub = parser.add_subparsers(dest="kind", required=True)

    pf = sub.add_parser("flights")
    pf.add_argument("--origin")
    pf.add_argument("--destination")
    pf.add_argument("--max-price", type=int, dest="max_price")

    ph = sub.add_parser("hotels")
    ph.add_argument("--city")
    ph.add_argument("--max-price", type=int, dest="max_price")

    args = parser.parse_args(argv)
    if args.kind == "flights":
        url, params = build_request("flights", origin=args.origin,
                                    destination=args.destination, max_price=args.max_price)
    else:
        url, params = build_request("hotels", city=args.city, max_price=args.max_price)

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        print(json.dumps(resp.json()))
        return 0
    except requests.RequestException as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
