import os
import requests
from datetime import datetime

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
    now = datetime.utcnow()
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
    return data.get("best_flights", []) + data.get("other_flights", [])


def cheapest(flights: list[dict]) -> dict | None:
    return min(flights, key=lambda f: f["price"]) if flights else None


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
        f"[{datetime.utcnow().isoformat()}] Checking {ORIGIN}→{DESTINATION} "
        f"on {departure_date}"
    )

    flights = search_flights(departure_date)

    if not flights:
        print("No flights found.")
        return

    best = cheapest(flights)
    price = float(best["price"])
    print(f"Cheapest: ₹{price:,.0f}  (threshold: ₹{PRICE_THRESHOLD_INR:,})")

    if price <= PRICE_THRESHOLD_INR:
        send_alert(best, price, departure_date)
    else:
        print("Price above threshold — no alert sent.")


if __name__ == "__main__":
    main()
