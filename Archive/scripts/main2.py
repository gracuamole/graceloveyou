"""Tomorrow's Old Man's / Batu Bolong surf forecast to Telegram.

Sources: Surfline's unofficial public forecast endpoints (ratings, swells,
wind, tides, commentary), and Open-Meteo Marine for modelled wave height.

Required environment variables: TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID.
Run: python main2.py
"""

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

SPOT_ID = "605112930a374f33cf5f8f05"
SPOT_NAME = "Old Man's / Batu Bolong"
LAT, LON = -8.658239153703311, 115.1275
BALI_TZ = ZoneInfo("Asia/Makassar")
HOURS = (6, 10, 15)
SURFLINE_BASE = "https://services.surfline.com/kbyg/spots/forecasts"
TIMEOUT = 20


def get_json(url, params):
    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def surfline(endpoint):
    return get_json(
        f"{SURFLINE_BASE}/{endpoint}",
        {"spotId": SPOT_ID, "days": 3, "intervalHours": 1},
    )


def local_time(record):
    """Surfline timestamps are Unix timestamps (UTC), not local wall times."""
    return datetime.fromtimestamp(record["timestamp"], tz=timezone.utc).astimezone(BALI_TZ)


def closest_record(records, target, max_minutes=65):
    if not records:
        return None
    valid = [r for r in records if isinstance(r, dict) and isinstance(r.get("timestamp"), (int, float))]
    if not valid:
        return None
    match = min(valid, key=lambda r: abs((local_time(r) - target).total_seconds()))
    if abs((local_time(match) - target).total_seconds()) > max_minutes * 60:
        return None
    return match


def cardinal(degrees):
    if not isinstance(degrees, (int, float)):
        return "?"
    labels = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    return labels[round(degrees / 45) % 8]


def feet_to_m(value):
    return value * 0.3048 if isinstance(value, (int, float)) else None


def fmt_m(value):
    return f"{value:.1f} m" if isinstance(value, (int, float)) else "N/A"


def fetch_open_meteo_wave(target_date):
    """Open-Meteo wave_height is modelled sea-wave height, not a guarantee of breaker size."""
    data = get_json(
        "https://marine-api.open-meteo.com/v1/marine",
        {
            "latitude": LAT,
            "longitude": LON,
            "hourly": "wave_height",
            "timezone": "Asia/Makassar",
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
        },
    )
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    heights = hourly.get("wave_height", [])
    output = {}
    for stamp, height in zip(times, heights):
        # Open-Meteo returns local wall-clock times when timezone is specified.
        dt = datetime.fromisoformat(stamp)
        if dt.date() == target_date:
            output[dt.hour] = height
    return output

def get_swell_summary(record):
    if not record:
        return "N/A"
