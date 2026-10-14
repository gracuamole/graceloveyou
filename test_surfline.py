import requests

url = "https://services.surfline.com/kbyg/spots/forecasts/wave"

params = {
    "spotId": "605112930a374f33cf5f8f05",
    "days": 2,
    "intervalHours": 1
}

response = requests.get(
    url,
    params=params,
    timeout=30
)

print("HTTP status:", response.status_code)

if response.ok:
    data = response.json()
    print("Response keys:", list(data.keys()))
    print("Wave entries:", len(data.get("data", {}).get("wave", [])))
else:
    print("Request failed.")
