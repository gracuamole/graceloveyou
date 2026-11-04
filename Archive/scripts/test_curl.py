import requests
from curl_cffi import requests as curl_requests

URL = "https://services.surfline.com/kbyg/spots/forecasts/conditions"

PARAMS = {
    "spotId": "605112930a374f33cf5f8f05",
    "days": 2,
}

def test(name, client, **kwargs):
    try:
        response = client.get(
            URL,
            params=PARAMS,
            timeout=20,
            **kwargs,
        )
        print(f"{name}: HTTP {response.status_code}")
        print("URL:", response.url)
        print("Response:", response.text[:120])
    except Exception as e:
        print(f"{name}: {type(e).__name__}: {e}")

test("Standard requests", requests)
test("curl_cffi default", curl_requests)
test("curl_cffi Chrome", curl_requests, impersonate="chrome")
test("curl_cffi Firefox", curl_requests, impersonate="firefox")
