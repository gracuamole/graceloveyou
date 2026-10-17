"""Surfline surf-mcp Python library + curl_cffi Telegram forecast.

Uses surf_mcp's endpoint construction, parsing, hourly merging and grouping.
Only replaces its HTTP transport to use the minimal curl_cffi request that
matched the successful direct endpoint tests more closely.
"""
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from curl_cffi import requests as curl_requests
from surf_mcp import fetch_full_forecast
import surf_mcp.surfline_client as surfline_client

SPOT_ID = "605112930a374f33cf5f8f05"
SPOT_NAME = "Old Man's / Batu Bolong"
BALI = ZoneInfo("Asia/Makassar")
HOURS = (6, 10, 15)
TIMEOUT = 25

# Some optional Surfline feeds may be restricted; their absence must not
# prevent the working core forecast feeds from being used.
OPTIONAL = {"consistency", "energy", "weather"}
cache = {}


def curl_get_json(url):
    endpoint = urlparse(url).path.rsplit("/", 1)[-1]
    # Do not send the package's custom browser headers or impersonation.
    # Earlier plain requests calls succeeded with minimal headers.
    response = curl_requests.get(url, timeout=TIMEOUT)
    print(f"Surfline {endpoint}: HTTP {response.status_code}")
    if response.status_code in (403, 404):
        if endpoint in OPTIONAL:
            print(f"Skipping optional feed: {endpoint}")
            return {"data": {endpoint: []}}
        if endpoint == "surf":
            # If breaking-surf heights are unavailable, use rating timestamps
            # as empty surf rows so surf-mcp can still join swell/wind/rating.
            ratings = cache.get("rating", {}).get("data", {}).get("rating", [])
            if ratings:
                print("Surfline surf unavailable; surf height will show N/A")
                return {"data": {"surf": [
                    {"timestamp": r["timestamp"],
                     "utcOffset": r.get("utcOffset", 8), "surf": {}}
                    for r in ratings if "timestamp" in r
                ]}}
    response.raise_for_status()
    data = response.json()
    if endpoint in {"rating", "surf", "swells", "wind", "tides", "conditions"}:
        cache[endpoint] = data
    return data


# Use the package's public forecast function and its normalizers, but provide
# the requested curl_cffi transport with simpler request fingerprint.
surfline_client._get_json = curl_get_json


def feet_m(value):
    return f"{value * 0.3048:.1f} m" if isinstance(value, (int, float)) else "N/A"


def primary_swell(swells):
    if not swells:
        return "N/A"
    # surf-mcp sorts swell partitions by height descending.
    swell = swells[0]
    period = swell.get("period_s")
    p = f"{period:g}s" if isinstance(period, (int, float)) else "?s"
    return f"{feet_m(swell.get('height_ft'))} @ {p} {swell.get('cardinal') or '?'}"


def nearest_tide(day, hour):
    target = datetime.combine(datetime.fromisoformat(day["date"]).date(),
                              datetime.min.time(), tzinfo=BALI).replace(hour=hour)
    tides = day.get("tide_hourly") or []
    valid = [t for t in tides if isinstance(t.get("timestamp"), (int, float))]
    if not valid:
        return "N/A"
    tide = min(valid, key=lambda t: abs(datetime.fromtimestamp(t["timestamp"], BALI) - target))
    if abs((datetime.fromtimestamp(tide["timestamp"], BALI) - target).total_seconds()) > 5400:
        return "N/A"
    return feet_m(tide.get("height_ft"))


def build_message():
    tomorrow = (datetime.now(BALI) + timedelta(days=1)).date()
    forecast = fetch_full_forecast(SPOT_ID, days=3)
    day = next((d for d in forecast.get("daily", []) if d.get("date") == tomorrow.isoformat()), None)
    if day is None:
        raise RuntimeError(f"Tomorrow {tomorrow} absent from Surfline response")

    lines = [f"🏄 {SPOT_NAME}", f"Tomorrow: {tomorrow:%a, %d %b %Y} (Bali)", ""]
    for hour in HOURS:
