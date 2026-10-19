"""Transit restriction: no itinerary may touch an airport in the Middle East or Turkey.

Checked by airport country (not by airline), on every segment endpoint and every technical stop,
outbound and inbound, so codeshares and overnight connections are covered.
"""

# ISO 3166-1 alpha-2 codes. Egypt is included by default (owner to confirm).
EXCLUDED_COUNTRIES = {
    "AE": "United Arab Emirates",
    "QA": "Qatar",
    "BH": "Bahrain",
    "SA": "Saudi Arabia",
    "OM": "Oman",
    "KW": "Kuwait",
    "JO": "Jordan",
    "LB": "Lebanon",
    "IL": "Israel",
    "IR": "Iran",
    "IQ": "Iraq",
    "SY": "Syria",
    "YE": "Yemen",
    "TR": "Türkiye",
    "EG": "Egypt",
}


def _airports(segment):
    yield segment["origin"]
    yield segment["destination"]
    for stop in segment.get("stops") or []:
        yield stop["airport"]


def transit_violations(offer):
    """Return the excluded airports an offer touches, e.g. ["DOH (Qatar)"]; empty if it complies.

    `offer` is a Duffel offer (slices -> segments -> origin/destination/stops, each airport carrying
    iata_code and iata_country_code). An airport without a country code is reported as a violation,
    because compliance cannot be proven.
    """
    found = []
    for slice_ in offer["slices"]:
        for segment in slice_["segments"]:
            for airport in _airports(segment):
                country = airport.get("iata_country_code")
                code = airport.get("iata_code", "?")
                if country is None:
                    label = f"{code} (country unknown)"
                elif country in EXCLUDED_COUNTRIES:
                    label = f"{code} ({EXCLUDED_COUNTRIES[country]})"
                else:
                    continue
                if label not in found:
                    found.append(label)
    return found
