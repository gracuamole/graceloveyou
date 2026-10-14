from surf_mcp import (
    fetch_full_forecast,
    lookup_spot_metadata
)

SPOT_ID = "605112930a374f33cf5f8f05"

def main():
    print("Testing Surfline Python library...")

    print("\n1. Testing spot metadata")

    try:
        metadata = lookup_spot_metadata(SPOT_ID)
        print("Metadata:", metadata)
    except Exception as error:
        print("Metadata failed:", error)

    print("\n2. Testing forecast data")

    try:
        forecast = fetch_full_forecast(
            SPOT_ID,
            days=2
        )

        print("Forecast keys:", list(forecast.keys()))

        for day in forecast.get("daily", []):
            print("\nDate:", day.get("date"))
            print("Hourly entries:", len(day.get("hourly", [])))

            for hour in day.get("hourly", []):
                if hour.get("local_hour") in [6, 10, 15]:
                    print({
                        "time": hour.get("local_iso"),
                        "surf_min_ft": hour.get("surf_min_ft"),
                        "surf_max_ft": hour.get("surf_max_ft"),
                        "swells": hour.get("swells"),
                        "wind": hour.get("wind"),
                        "rating": hour.get("rating")
                    })

        if not forecast.get("daily"):
            print("No daily forecasts returned.")

    except Exception as error:
        print("Forecast failed:", error)
        raise

if __name__ == "__main__":
    main()
