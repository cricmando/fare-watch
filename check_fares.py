#!/usr/bin/env python3
"""
Checks one route on Google Flights via SerpApi, appends the fare to fares.csv,
and emails you when it crosses a threshold you set.

Everything configurable lives in TRIP below or in repository secrets.
Standard library only - no pip install needed.
"""

import csv
import json
import os
import smtplib
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

# ---------------------------------------------------------------- trip config

TRIP = {
    "departure_id": "JFK",
    "arrival_id": "DEL",
    "outbound_date": "2026-12-12",
    "return_date": "2026-12-22",
    "travel_class": "3",   # 1 economy, 2 premium economy, 3 business, 4 first
    "type": "1",           # 1 = round trip
    "stops": "2",          # 0 any, 1 nonstop only, 2 one stop max, 3 two stops max
    "currency": "USD",
    "hl": "en",
}

TARGET = float(os.environ.get("TARGET_PRICE", 4000))    # book at or below
CEILING = float(os.environ.get("CEILING_PRICE", 8000))  # walk away above
HISTORY = Path(os.environ.get("HISTORY_FILE", "fares.csv"))
TIMEOUT = 45

FIELDS = [
    "checked_on", "price", "airline", "flight_numbers", "duration_min",
    "price_level", "typical_low", "typical_high", "google_lowest",
]


# ------------------------------------------------------------------ serpapi

def fetch():
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        die("SERPAPI_KEY is not set. Add it as a repository secret.")

    params = dict(TRIP, engine="google_flights", api_key=key)
    url = "https://serpapi.com/search?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers={"User-Agent": "fare-watch/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        die(f"SerpApi returned HTTP {e.code}. Check your key and your search quota.")
    except Exception as e:  # noqa: BLE001
        die(f"Could not reach SerpApi: {e}")

    if data.get("error"):
        die(f"SerpApi error: {data['error']}")
    return data


def cheapest(data):
    """Pick the lowest-priced itinerary across both result buckets."""
    options = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    priced = [o for o in options if isinstance(o.get("price"), (int, float))]
    if not priced:
        return None
    best = min(priced, key=lambda o: o["price"])

    legs = best.get("flights") or []
    return {
        "price": float(best["price"]),
        "airline": " / ".join(dict.fromkeys(l.get("airline", "?") for l in legs)),
        "flight_numbers": " ".join(l.get("flight_number", "?") for l in legs),
        "duration_min": best.get("total_duration", ""),
    }


def insights(data):
    pi = data.get("price_insights") or {}
    rng = pi.get("typical_price_range") or [None, None]
    return {
        "price_level": pi.get("price_level", ""),
        "typical_low": rng[0] if len(rng) > 0 else "",
        "typical_high": rng[1] if len(rng) > 1 else "",
        "google_lowest": pi.get("lowest_price", ""),
    }


# ------------------------------------------------------------------ history

def read_history():
    if not HISTORY.exists():
        return []
    with HISTORY.open(newline="", encoding="utf-8") as f:
        rows = []
        for row in csv.DictReader(f):
            try:
                row["price"] = float(row["price"])
                rows.append(row)
            except (TypeError, ValueError, KeyError):
                continue  # skip any malformed line rather than crashing
        return rows


def append_history(row):
    new = not HISTORY.exists()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


# -------------------------------------------------------------------- email

def send(subject, body):
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", 465))
    user = os.environ.get("SMTP_USER")
    pw = os.environ.get("SMTP_PASSWORD")
    to = os.environ.get("EMAIL_TO") or user

    if not (user and pw and to):
        print("Email not configured; printing instead.\n")
        print(subject, "\n", body, sep="")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, pw)
            s.send_message(msg)
        print(f"Alert sent to {to}")
    except Exception as e:  # noqa: BLE001
        print(f"Could not send mail: {e}", file=sys.stderr)
        print(subject, "\n", body, sep="")


def die(msg):
    print(msg, file=sys.stderr)
    send("Fare watch failed", msg)
    sys.exit(1)


# --------------------------------------------------------------------- main

def main():
    data = fetch()
    fare = cheapest(data)
    route = f"{TRIP['departure_id']}-{TRIP['arrival_id']}"

    if not fare:
        die(f"No {route} itineraries came back. The dates may be outside "
            "Google's booking window, or the nonstop filter may be too tight.")

    history = read_history()
    prev_low = min((r["price"] for r in history), default=None)
    last = history[-1]["price"] if history else None

    row = {"checked_on": date.today().isoformat(), **fare, **insights(data)}
    append_history(row)

    price = fare["price"]
    print(f"{route} {TRIP['outbound_date']} -> {TRIP['return_date']}: ${price:,.0f} "
          f"on {fare['airline']} ({fare['flight_numbers']})")

    # Decide whether this is worth an email. Daily mail about an unchanged
    # fare trains you to ignore the alerts, so only three things qualify.
    reasons = []
    if price <= TARGET:
        reasons.append(f"at or below your ${TARGET:,.0f} buy target")
    if prev_low is not None and price < prev_low:
        reasons.append(f"a new low, under the previous ${prev_low:,.0f}")
    if last is not None and last - price >= 250:
        reasons.append(f"down ${last - price:,.0f} since the last check")

    if not reasons:
        print("No alert: nothing crossed a threshold.")
        return

    if price <= TARGET:
        verdict = "BOOK"
    elif price <= CEILING:
        verdict = "HOLD"
    else:
        verdict = "WALK AWAY"

    search = ("https://www.google.com/travel/flights?q=" + urllib.parse.quote(
        f"Flights to {TRIP['arrival_id']} from {TRIP['departure_id']} "
        f"on {TRIP['outbound_date']} through {TRIP['return_date']} business class"))

    body = "\n".join([
        f"{route}  {TRIP['outbound_date']} to {TRIP['return_date']}  business",
        "",
        f"Cheapest nonstop: ${price:,.0f}",
        f"Carrier: {fare['airline']}  ({fare['flight_numbers']})",
        f"Verdict: {verdict}",
        f"Why you're getting this: {'; '.join(reasons)}.",
        "",
        f"Google calls this price level: {row['price_level'] or 'not reported'}",
        f"Typical range for this route: "
        f"${row['typical_low'] or '?'} to ${row['typical_high'] or '?'}",
        f"Lowest seen since tracking began: "
        f"${min(prev_low, price):,.0f}" if prev_low else "First recorded check.",
        "",
        f"Open the search: {search}",
        "",
        f"Checked {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC. "
        f"Full history is in {HISTORY.name} in the repo.",
    ])

    send(f"{route} business {verdict}: ${price:,.0f}", body)


if __name__ == "__main__":
    main()
