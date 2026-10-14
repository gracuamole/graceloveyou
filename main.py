
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

# ---------------------------------
# SETTINGS
# ---------------------------------

SPOT_NAME = "Batu Bolong, Canggu"

# Approximate offshore forecast point.
# Adjust after checking the location.
LATITUDE = -8.66
LONGITUDE = 115.13

TIMEZONE = "Asia/Makassar"

# ---------------------------------
# COMPONENT 1: FETCH FORECAST
# ---------------------------------

def fetch_forecast():
    marine_url = "https://marine-api.open-meteo.com/v1/marine"
    weather_url = "https://api.open-meteo.com/v1/forecast"

    marine_params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join([
            "wave_height",
            "wave_direction",
            "wave_period",
            "swell_wave_height",
            "swell_wave_direction",
            "swell_wave_period"
        ]),
        "timezone": TIMEZONE,
        "forecast_days": 1
    }

    weather_params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join([
            "wind_speed_10m",
            "wind_direction_10m"
        ]),
        "wind_speed_unit": "kmh",
        "timezone": TIMEZONE,
        "forecast_days": 1
    }

    marine_response = requests.get(
        marine_url, params=marine_params, timeout=30
    )
    marine_response.raise_for_status()

    weather_response = requests.get(
        weather_url, params=weather_params, timeout=30
    )
    weather_response.raise_for_status()

    return marine_response.json(), weather_response.json()

# ---------------------------------
# COMPONENT 2: SUMMARISE FORECAST
# ---------------------------------

def compass_direction(degrees):
    if degrees is None:
        return "Unknown"

    directions = [
        "N", "NE", "E", "SE",
        "S", "SW", "W", "NW"
    ]

    index = round(degrees / 45) % 8
    return directions[index]

def format_number(value, digits=1):
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"

def get_hourly_value(data, field, timestamp):
    hourly = data["hourly"]
    times = hourly["time"]

    if timestamp not in times:
        return None

    index = times.index(timestamp)
    return hourly[field][index]

def summarise_forecast(marine, weather):
    now = datetime.now(ZoneInfo(TIMEZONE))
    date_str = now.strftime("%A, %d %B %Y")

    # Use the 9 AM forecast.
    target_time = now.strftime("%Y-%m-%d") + "T09:00"

    def marine_value(field):
        return get_hourly_value(marine, field, target_time)

    def weather_value(field):
        return get_hourly_value(weather, field, target_time)

    wave_height = marine_value("wave_height")
    wave_direction = marine_value("wave_direction")
    wave_period = marine_value("wave_period")
    swell_height = marine_value("swell_wave_height")
    swell_direction = marine_value("swell_wave_direction")
    swell_period = marine_value("swell_wave_period")
    wind_speed = weather_value("wind_speed_10m")
    wind_direction = weather_value("wind_direction_10m")

    if wind_speed is None:
        wind_summary = "Wind forecast unavailable."
    elif wind_speed < 10:
        wind_summary = "Light winds forecast."
    elif wind_speed < 20:
        wind_summary = "Moderate winds forecast."
    else:
        wind_summary = "Stronger winds forecast. Check local conditions."

    if wave_height is None:
        wave_summary = "Wave forecast unavailable."
    elif wave_height < 0.5:
        wave_summary = "Relatively small offshore waves forecast."
    elif wave_height < 1.5:
        wave_summary = "Moderate offshore wave height forecast."
    else:
        wave_summary = "Larger offshore waves forecast. Exercise caution."

    message = f"""🏄 BALI DAILY SURF FORECAST
📅 {date_str}

📍 {SPOT_NAME}
🕘 Forecast for 9:00 AM Bali time

🌊 MARINE CONDITIONS
• Wave height: {format_number(wave_height)} m
• Wave direction: {compass_direction(wave_direction)}
• Wave period: {format_number(wave_period)} s
• Swell height: {format_number(swell_height)} m
• Swell direction: {compass_direction(swell_direction)}
• Swell period: {format_number(swell_period)} s

💨 WIND
• Speed: {format_number(wind_speed)} km/h
• Direction (from): {compass_direction(wind_direction)}

📝 FORECAST SUMMARY
{wave_summary}
{wind_summary}

⚠️ These are offshore model forecasts, not measured breaking-wave heights at Batu Bolong. They do not establish surf safety or suitability for beginners.

📡 Data: Open-Meteo Marine & Weather
"""

    return message

# ---------------------------------
# COMPONENT 3: SEND TO TELEGRAM
# ---------------------------------

def send_to_telegram(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    channel_id = os.environ["TELEGRAM_CHANNEL_ID"]

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": channel_id,
            "text": message
        },
        timeout=30
    )

    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram error"))

    print("Telegram message sent successfully!")

# ---------------------------------
# RUN ALL COMPONENTS
# ---------------------------------

def main():
    print("Fetching surf forecast...")
    marine, weather = fetch_forecast()

    print("Generating summary...")
    summary = summarise_forecast(marine, weather)

    print("Sending forecast to Telegram...")
    send_to_telegram(summary)

    print("Finished!")

if __name__ == "__main__":
    main()
