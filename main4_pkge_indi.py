"""Surfline surf-mcp Python library + curl_cffi Telegram forecast.

Uses surf_mcp's endpoint construction, parsing, hourly merging and grouping.
Only replaces its HTTP transport to use the minimal curl_cffi request that
matched the successful direct endpoint tests more closely.
"""
import os
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from zoneinfo import ZoneInfo

from curl_cffi import requests as curl_requests
from surf_mcp import fetch_full_forecast
import surf_mcp.surfline_client as surfline_client

SPOT_ID = "605112930a374f33cf5f8f05"
SPOT_NAME = "Old Man's / Batu Bolong"
BALI = ZoneInfo("Asia/Makassar")
HOURS = (6, 10, 15)
TIMEOUT = 25

# The package handles parsing and joining. This transport adds retries and
# independently retries a failed feed using the minimal successful parameters.
OPTIONAL = {"consistency", "energy", "weather", "swells", "wind", "tides", "conditions"}
cache = {}


def request_json(url, endpoint, label, attempts=3):
    """Use curl_cffi for every request, including fallback requests."""
    for attempt in range(1, attempts + 1):
        try:
            response = curl_requests.get(
                url, impersonate="firefox", timeout=TIMEOUT,
            )
            print(f"Surfline {endpoint} [{label} {attempt}/{attempts}]: "
                  f"HTTP {response.status_code}", flush=True)
            response.raise_for_status()
            return response.json()
        except (Exception) as exc:
            print(f"Surfline {endpoint}: {type(exc).__name__}: {exc}", flush=True)
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 4))
    return None


def minimal_endpoint_url(original_url):
    """Independently call the failed endpoint with known-working query params."""
    parsed = urlparse(original_url)
    params = dict(parse_qsl(parsed.query))
    params = {"spotId": params.get("spotId", SPOT_ID), "days": "2"}
    return urlunparse(parsed._replace(query=urlencode(params)))


def empty_feed(endpoint):
    """Provide the feed shape expected by the package if a feed is unavailable."""
    if endpoint == "surf":
        ratings = cache.get("rating", {}).get("data", {}).get("rating", [])
        return {"data": {"surf": [
            {"timestamp": row["timestamp"],
             "utcOffset": row.get("utcOffset", 8), "surf": {}}
            for row in ratings if "timestamp" in row
        ]}}
    if endpoint == "rating":
        # A missing rating is not silently treated as FAIR/POOR.
        raise RuntimeError("Surfline rating unavailable after primary and fallback requests")
    return {"data": {endpoint: []}}


def curl_get_json(url):
    endpoint = urlparse(url).path.rsplit("/", 1)[-1]
    data = request_json(url, endpoint, "package")
    if data is None:
        fallback_url = minimal_endpoint_url(url)
        print(f"Surfline {endpoint}: trying independent endpoint request "
              f"with spotId and days=2", flush=True)
        data = request_json(fallback_url, endpoint, "fallback", attempts=2)

    if data is None:
        if endpoint not in OPTIONAL and endpoint != "surf":
            raise RuntimeError(f"Required Surfline feed unavailable: {endpoint}")
        print(f"Surfline {endpoint}: unavailable; using N/A where possible", flush=True)
        return empty_feed(endpoint)

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
        row = next((r for r in day.get("hourly", []) if r.get("local_hour") == hour), None)
        lines.append(f"🕒 {hour:02d}:00")
        if row is None:
            lines.extend(["Forecast unavailable", ""])
            continue
        rating = (row.get("rating") or {}).get("key") or "N/A"
        wind = row.get("wind") or {}
        wind_text = (f"{wind['speed_kts']:.1f} kt {wind.get('cardinal') or '?'}"
                     if isinstance(wind.get("speed_kts"), (int, float)) else "N/A")
        lo, hi = row.get("surf_min_ft"), row.get("surf_max_ft")
        surf_text = f"{feet_m(lo)} – {feet_m(hi)}" if lo is not None and hi is not None else "N/A"
        lines.extend([
            f"Surfline rating: {rating}",
            f"Breaking surf (Surfline): {surf_text}",
            f"Primary swell (Surfline): {primary_swell(row.get('swells'))}",
            f"Wind (Surfline): {wind_text}",
            f"Tide (Surfline): {nearest_tide(day, hour)}", "",
        ])
    if day.get("headline"):
        lines.append("Surfline headline: " + str(day["headline"])[:350])
    if day.get("observation"):
        lines.append("Surfline commentary: " + str(day["observation"])[:500])
    return "\n".join(lines)


def main():
    message = build_message()
    print(message)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHANNEL_ID")
    if not token or not chat:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID")
    response = curl_requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": message}, timeout=TIMEOUT,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram API did not accept message")
    print("Telegram message sent")


if __name__ == "__main__":
    main()
