import requests

SPOT_ID = "605112930a374f33cf5f8f05"
BASE = "https://services.surfline.com/kbyg/spots/forecasts"

tests = {
    "wave": f"{BASE}/wave",
    "swells": f"{BASE}/swells",
    "swell": f"{BASE}/swell",
}

params = {
    "spotId": SPOT_ID,
    "days": 2,
    "intervalHours": 1,
    "maxHeights": "false",
}

for name, url in tests.items():
    try:
        response = requests.get(
            url,
            params=params,
            timeout=15,
        )

        print(f"{name}: HTTP {response.status_code}")

        if response.ok:
            print("SUCCESS:", response.text[:500])
        else:
            print("ERROR:", response.text[:150])

    except requests.RequestException as e:
        print(f"{name}: {e}")
