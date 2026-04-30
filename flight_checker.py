import os
import requests
from datetime import datetime, UTC

SERPAPI_KEY = os.environ["SERPAPI_KEY"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
PRICE_THRESHOLD_INR = int(os.environ.get("PRICE_THRESHOLD_INR", "35000"))
ADULTS = int(os.environ.get("ADULTS", "1"))

ORIGIN = "SYD"
DESTINATION = "MAA"
SERPAPI_URL = "https://serpapi.com/search"

# All candidate departure dates — one is selected per run via rotation
DATES = [
    "2026-06-27", "2026-06-28", "2026-06-29", "2026-06-30",
    "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04",
]


def pick_date() -> str:
    """Rotate through DATES so each run checks a different date.
    With 3 runs/day (every 8 h) this cycles each date roughly every 2-3 days,
    keeping total API usage at ~90 calls/month within the SerpAPI free tier."""
    now = datetime.now(UTC)
    run_slot = now.timetuple().tm_yday * 3 + now.hour // 8
    return DATES[run_slot % len(DATES)]


def search_flights(departure_date: str) -> list[dict]:
    params = {
        "engine": "google_flights",
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "outbound_date": departure_date,
        "currency": "INR",
        "hl": "en",
        "type": "2",        # one-way
        "adults": ADULTS,
        "api_key": SERPAPI_KEY,
    }
    response = requests.get(SERPAPI_URL, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    # Print top-level keys to help debug response structure
    print(f"Response keys: {list(data.keys())}")

    # other_flights don't include a price field, so only use best_flights
    flights = data.get("best_flights", [])

    # Print first flight object so we can see the exact structure
    if flights:
        print(f"Sample flight keys: {list(flights[0].keys())}")

    return flights


def extract_price(flight: dict) -> float:
    # SerpAPI sometimes nests price differently — try known locations
    if "price" in flight:
        return float(flight["price"])
    # Fallback: price inside a nested dict
    for key in ("fare", "total", "amount"):
        if key in flight:
            return float(flight[key])
    raise KeyError(f"Could not find price in flight object. Keys: {list(flight.keys())}")


def cheapest(flights: list[dict]) -> dict | None:
    return min(flights, key=extract_price) if flights else None


def format_flight(flight: dict) -> str:
    legs = flight.get("flights", [])
    if not legs:
        return ""
    dep = legs[0]["departure_airport"]
    arr = legs[-1]["arrival_airport"]
    stops = len(legs) - 1
    stop_label = "non-stop" if stops == 0 else f"{stops} stop(s)"
    return (
        f"{dep['id']} {dep['time']} → {arr['id']} {arr['time']} ({stop_label})"
    )


def send_alert(flight: dict, price: float, departure_date: str) -> None:
    itinerary = format_flight(flight)
    body = (
        f"Price: ₹{price:,.0f}  (threshold ₹{PRICE_THRESHOLD_INR:,})\n"
        f"Date: {departure_date}\n"
        f"Route: {itinerary}\n\n"
        f"Book now before the price changes!"
    )
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body,
        headers={
            "Title": f"Flight Alert: SYD→MAA ₹{price:,.0f}",
            "Priority": "high",
            "Tags": "airplane,money",
        },
        timeout=10,
    )
    print(f"Alert sent! ₹{price:,.0f} on {departure_date}")


def main() -> None:
    departure_date = pick_date()
    print(
        f"[{datetime.now(UTC).isoformat()}] Checking {ORIGIN}→{DESTINATION} "
        f"on {departure_date}"
    )

    flights = search_flights(departure_date)

    if not flights:
        print("No flights found.")
        return

    best = cheapest(flights)
    price = extract_price(best)
    print(f"Cheapest: ₹{price:,.0f}  (threshold: ₹{PRICE_THRESHOLD_INR:,})")

    if price <= PRICE_THRESHOLD_INR:
        send_alert(best, price, departure_date)
    else:
        print("Price above threshold — no alert sent.")


if __name__ == "__main__":
    main()
