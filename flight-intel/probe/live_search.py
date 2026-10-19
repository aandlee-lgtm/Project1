"""Milestone 1: one real, currently priced Sydney return itinerary from the Duffel API.

Standard library only. Needs a Duffel *live* access token in DUFFEL_ACCESS_TOKEN; test tokens are
refused so Duffel's fictional test airline can never be shown as a result.

    python3 flight-intel/probe/live_search.py --dest NRT --depart 2027-04-12 --nights 14

Nothing is invented: every field printed comes from the Duffel response. If the search fails or
nothing qualifies, the script says so and exits non-zero.
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from transit import transit_violations

API = "https://api.duffel.com"
CABINS = ("economy", "premium_economy", "business")


def call(method, path, token, body=None):
    request = urllib.request.Request(
        API + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Duffel-Version": "v2",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)["data"]
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:2000]
        sys.exit(f"Duffel {method} {path} failed: HTTP {error.code}\n{detail}")
    except urllib.error.URLError as error:
        sys.exit(f"Could not reach {API}: {error.reason}")


def money(amount, currency):
    # Only AUD is shown as A$; any other currency keeps its own code (no unlabeled "$").
    return f"A${amount}" if currency == "AUD" else f"{currency} {amount} (not AUD)"


def search_link(origin, dest, depart, back, cabin):
    query = f"Flights from {origin} to {dest} on {depart} through {back} {cabin.replace('_', ' ')}"
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(query)


def describe(offer):
    lines = [f"Offer {offer['id']}  (owner: {offer['owner']['name']})"]
    for label, slice_ in zip(("Outbound", "Return"), offer["slices"]):
        lines.append(f"  {label}: {slice_['origin']['iata_code']} -> {slice_['destination']['iata_code']}"
                     f"  duration {slice_.get('duration')}  fare brand: {slice_.get('fare_brand_name') or 'n/a'}")
        for seg in slice_["segments"]:
            mkt, opr = seg["marketing_carrier"], seg.get("operating_carrier") or {}
            pax = (seg.get("passengers") or [{}])[0]
            bags = ", ".join(f"{b['quantity']}x {b['type']}" for b in pax.get("baggages") or []) or "n/a"
            stops = [s["airport"]["iata_code"] for s in seg.get("stops") or []]
            lines.append(
                f"    {mkt['iata_code']}{seg['marketing_carrier_flight_number']} "
                f"operated by {opr.get('name', 'UNKNOWN')} ({opr.get('iata_code', '?')})  "
                f"{seg['origin']['iata_code']} {seg['departing_at']} -> "
                f"{seg['destination']['iata_code']} {seg['arriving_at']}"
                + (f"  tech stop {','.join(stops)}" if stops else "")
                + f"  cabin {pax.get('cabin_class_marketing_name') or pax.get('cabin_class', 'n/a')}"
                + f"  bags {bags}"
            )
    lines.append(f"  Total (1 adult, taxes incl.): {money(offer['total_amount'], offer['total_currency'])}"
                 f"  [base {offer.get('base_amount')}, tax {offer.get('tax_amount')}]")
    lines.append(f"  Offer expires: {offer.get('expires_at')}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--origin", default="SYD")
    parser.add_argument("--dest", required=True, help="IATA airport or city code, e.g. NRT, CDG, CAN")
    parser.add_argument("--depart", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--nights", type=int, default=14)
    parser.add_argument("--cabin", choices=CABINS, default="economy")
    parser.add_argument("--carrier", help="only keep offers with a segment marketed by this IATA code, e.g. CZ or VA")
    parser.add_argument("--max-connections", type=int, default=1)
    args = parser.parse_args()

    token = os.environ.get("DUFFEL_ACCESS_TOKEN", "")
    if not token.startswith("duffel_live_"):
        sys.exit("DUFFEL_ACCESS_TOKEN must be a Duffel live token (duffel_live_...). "
                 "Test tokens return fictional airlines and cannot demonstrate a real fare.")

    back = args.depart + dt.timedelta(days=args.nights)
    searched_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    request = call("POST", "/air/offer_requests?return_offers=true&supplier_timeout=20000", token, {
        "slices": [
            {"origin": args.origin, "destination": args.dest, "departure_date": args.depart.isoformat()},
            {"origin": args.dest, "destination": args.origin, "departure_date": back.isoformat()},
        ],
        "passengers": [{"type": "adult"}],
        "cabin_class": args.cabin,
        "max_connections": args.max_connections,
    })
    offers = request.get("offers") or []
    print(f"Searched {searched_at}: {args.origin} {args.depart} <-> {args.dest} {back} "
          f"({args.nights} nights, {args.cabin}); {len(offers)} offers returned.")

    kept, rejected = [], 0
    for offer in offers:
        if transit_violations(offer):
            rejected += 1
            continue
        if args.carrier and not any(seg["marketing_carrier"]["iata_code"] == args.carrier.upper()
                                    for s in offer["slices"] for seg in s["segments"]):
            continue
        kept.append(offer)
    print(f"Rejected for Middle East / Turkey transit: {rejected}. Qualifying: {len(kept)}.")
    if not kept:
        sys.exit("No practical fare found today for this search.")

    cheapest = min(kept, key=lambda o: float(o["total_amount"]))
    # Stage C: re-fetch the offer to confirm it is still available at this price.
    fresh = call("GET", f"/air/offers/{cheapest['id']}", token)
    if transit_violations(fresh):
        sys.exit("Repriced offer now routes through an excluded country; rejected.")
    changed = (fresh["total_amount"], fresh["total_currency"]) != (cheapest["total_amount"], cheapest["total_currency"])
    print()
    print(describe(fresh))
    print(f"  Repriced: {'price CHANGED from ' + money(cheapest['total_amount'], cheapest['total_currency']) if changed else 'same price confirmed'}")
    print(f"  Booking path (search link, not the exact fare): "
          f"{search_link(args.origin, args.dest, args.depart, back, args.cabin)}")


if __name__ == "__main__":
    main()
