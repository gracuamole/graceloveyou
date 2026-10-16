import requests

SPOT_ID = "605112930a374f33cf5f8f05"

BASE = "https://services.surfline.com/kbyg/spots/forecasts"

endpoints = [
    "conditions",
    "rating",
    "wave",
    "wind",
    "tides",
]

for endpoint in endpoints:
    url = f"{BASE}/{endpoint}"

    try:
        response = requests.get(
            url,
            params={"spotId": SPOT_ID, "days": 2},
            timeout=15,
        )

        print(f"{endpoint}: HTTP {response.status_code}")

        if response.ok:
            print("SUCCESS:", response.text[:300])
        else:
            print("ERROR:", response.text[:150])

    except requests.RequestException as e:
        print(f"{endpoint}: {e}")
