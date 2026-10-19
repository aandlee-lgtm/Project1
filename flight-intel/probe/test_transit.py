"""Unit tests for the transit restriction. Offers here are synthetic test fixtures, not fares."""

import unittest

from transit import transit_violations


def airport(code, country):
    return {"iata_code": code, "iata_country_code": country}


def offer(*slices):
    return {"slices": [{"segments": list(segments)} for segments in slices]}


def seg(origin, dest, stops=()):
    return {"origin": origin, "destination": dest, "stops": [{"airport": a} for a in stops]}


SYD, CAN, CDG, DOH, IST, SIN = (airport("SYD", "AU"), airport("CAN", "CN"), airport("CDG", "FR"),
                                airport("DOH", "QA"), airport("IST", "TR"), airport("SIN", "SG"))


class TransitTest(unittest.TestCase):
    def test_china_connection_complies(self):
        o = offer([seg(SYD, CAN), seg(CAN, CDG)], [seg(CDG, CAN), seg(CAN, SYD)])
        self.assertEqual(transit_violations(o), [])

    def test_doha_on_return_only_is_rejected(self):
        o = offer([seg(SYD, SIN), seg(SIN, CDG)], [seg(CDG, DOH), seg(DOH, SYD)])
        self.assertEqual(transit_violations(o), ["DOH (Qatar)"])

    def test_technical_stop_in_turkey_is_rejected(self):
        o = offer([seg(SYD, CDG, stops=[IST])], [seg(CDG, SYD)])
        self.assertEqual(transit_violations(o), ["IST (Türkiye)"])

    def test_unknown_country_is_not_assumed_safe(self):
        o = offer([seg(SYD, {"iata_code": "XXX"})], [seg({"iata_code": "XXX"}, SYD)])
        self.assertEqual(transit_violations(o), ["XXX (country unknown)"])


if __name__ == "__main__":
    unittest.main()
