import requests

# ---------------------------------
# SURFLINE SETTINGS
# ---------------------------------

SPOT_NAME = "Old Man's / Batu Bolong, Canggu"
SPOT_ID = "605112930a374f33cf5f8f05"

# ---------------------------------
# TEST SURFLINE API CONNECTION
# ---------------------------------

def test_surfline():

    url = "https://services.surfline.com/kbyg/spots/forecasts/wave"

    params = {
        "spotId": SPOT_ID,
        "days": 2,
        "intervalHours": 1
    }

    print(f"Testing Surfline API for {SPOT_NAME}...")
    print(f"Spot ID: {SPOT_ID}")

    try:
        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        print(f"HTTP status: {response.status_code}")

        if response.status_code == 200:

            data = response.json()

            print("Connection successful!")
            print("Response keys:", list(data.keys()))

            wave_data = data.get("data", {}).get("wave", [])

            print(f"Wave forecast entries: {len(wave_data)}")

            if wave_data:
                print("\nFirst forecast entry:")
                print(wave_data[0])
            else:
                print("No wave forecast entries returned.")
                raise RuntimeError("Surfline returned no wave forecast data.")

        else:
            print("Surfline API request failed.")
            print("Response preview:", response.text[:500])
            response.raise_for_status()

    except requests.exceptions.RequestException as error:
        print(f"Request error: {error}")
        raise


# ---------------------------------
# RUN TEST
# ---------------------------------

if __name__ == "__main__":
    test_surfline()
