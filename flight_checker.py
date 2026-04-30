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

DATES = [
    "2026-06-27", "2026-06-28", "2026-06-29", "2026-06-30",
    "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04",
]


def pick_date() -> str:
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
        "type": "2",
        "adults": ADULTS,
        "api_key": SERPAPI_KEY,
    }
    response = requests.get(SERPAPI_URL, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()
    return data.get("best_flights", [])


def extract_price(flight: dict) -> float:
    if "price" in flight:
        return float(flight["price"])
    for key in ("fare", "total", "amount"):
        if key in flight:
            return float(flight[key])
    raise KeyError(f"Could not find price in flight object. Keys: {list(flight.keys())}")


def cheapest(flights: list[dict]) -> dict | None:
    return min(flights, key=extract_price) if flights else None


def format_duration(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60}m"


def format_flight(flight: dict) -> str:
    legs = flight.get("flights", [])
    if not legs:
        return ""

    lines = []
    total = format_duration(flight.get("total_duration", 0))
    stops = len(legs) - 1
    stop_label = "non-stop" if stops == 0 else f"{stops} stop(s)"
    lines.append(f"  {stop_label}, total {total}")

    for i, leg in enumerate(legs, 1):
        dep = leg["departure_airport"]
        arr = leg["arrival_airport"]
        airline = leg.get("airline", "")
        flight_no = leg.get("flight_number", "")
        duration = format_duration(leg.get("duration", 0))
        lines.append(
            f"  Leg {i}: {dep['id']} {dep['time']} -> {arr['id']} {arr['time']} "
            f"({airline} {flight_no}, {duration})"
        )

        layovers = flight.get("layovers", [])
        if i <= len(layovers):
            lv = layovers[i - 1]
            lines.append(
                f"  Layover: {lv.get('name', lv.get('id', ''))} "
                f"({format_duration(lv.get('duration', 0))})"
            )

    return "\n".join(lines)


def send_alert(flight: dict, price: float, departure_date: str) -> None:
    itinerary = format_flight(flight)
    body = (
        f"Price: Rs{price:,.0f} (threshold Rs{PRICE_THRESHOLD_INR:,})\n"
        f"Date: {departure_date}\n"
        f"Flight details:\n{itinerary}\n\n"
        f"Book now before the price changes!"
    )
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body,
        headers={
            "Title": f"Flight Alert: SYD->MAA Rs{price:,.0f}",
            "Priority": "high",
            "Tags": "airplane,money",
        },
        timeout=10,
    )
    print(f"Alert sent! Rs{price:,.0f} on {departure_date}")


def main() -> None:
    departure_date = pick_date()
    print(
        f"[{datetime.now(UTC).isoformat()}] Checking {ORIGIN}->>{DESTINATION} "
        f"on {departure_date}"
    )

    flights = search_flights(departure_date)

    if not flights:
        print("No flights found.")
        return

    best = cheapest(flights)
    price = extract_price(best)
    print(f"Cheapest: Rs{price:,.0f}  (threshold: Rs{PRICE_THRESHOLD_INR:,})")

    if price <= PRICE_THRESHOLD_INR:
        send_alert(best, price, departure_date)
    else:
        print("Price above threshold -- no alert sent.")


if __name__ == "__main__":
    main()
