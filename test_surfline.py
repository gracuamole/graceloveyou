import requests

SPOT_ID = "605112930a374f33cf5f8f05"

url = "https://services.surfline.com/kbyg/spots/forecasts/wave"

params = {
    "spotId": SPOT_ID,
    "days": 2,
    "intervalHours": 1,
    "maxHeights": "false"
}

try:
    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    print("HTTP status:", response.status_code)
    print("Requested URL:", response.url)

    if response.status_code == 200:
        data = response.json()

        print("Connection successful!")
        print("Response keys:", list(data.keys()))

        waves = data.get("data", {}).get("wave", [])

        print("Wave entries:", len(waves))

        if waves:
            print("First forecast:", waves[0])

    else:
        print("Request unsuccessful.")
        print("Response preview:", response.text[:300])
        response.raise_for_status()

except requests.exceptions.RequestException as error:
    print("Connection error:", error)
    raise
