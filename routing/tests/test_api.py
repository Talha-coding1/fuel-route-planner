from decimal import Decimal
from unittest import mock

import numpy as np
from django.test import SimpleTestCase

from routing.services.exceptions import RoutingProviderError
from routing.services.osrm import OSRMRoute
from stations.services.station_index import StationIndex, StationRecord

URL = "/api/route/"


def fake_route():
    lat = np.linspace(34.05, 40.71, 400)
    lon = np.linspace(-118.24, -74.0, 400)
    return OSRMRoute(lat, lon, 4_000_000.0, 130_000.0)


def fake_index():
    # stations every ~150 miles along the same straight path
    recs = []
    for i, f in enumerate(np.linspace(0.05, 0.95, 18)):
        recs.append(StationRecord(i, f"STOP {i}", "I-40, EXIT 1", "Town", "TX",
                                  Decimal(f"{3 + (i % 5) / 10:.3f}"), 34.05 + f * 6.66, -118.24 + f * 44.24))
    return StationIndex(recs)


class RouteApiTests(SimpleTestCase):
    def setUp(self):
        osrm_cls = mock.patch("routing.services.trip_planner.OSRMClient")
        idx = mock.patch("routing.services.trip_planner.get_station_index", return_value=fake_index())
        self.osrm = osrm_cls.start().return_value
        self.osrm.get_route.return_value = fake_route()
        idx.start()
        self.addCleanup(mock.patch.stopall)

    def test_success_payload_and_single_routing_call(self):
        r = self.client.post(URL, {"start": "Los Angeles, CA", "finish": "New York, NY"}, content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(self.osrm.get_route.call_count, 1)
        self.assertEqual(d["route"]["geojson"]["geometry"]["type"], "LineString")
        self.assertGreater(len(d["fuel_stops"]), 0)
        stop = d["fuel_stops"][0]
        for key in ("name", "address", "city", "state", "price_per_gallon", "gallons", "cost", "location"):
            self.assertIn(key, stop)
        self.assertAlmostEqual(d["summary"]["total_fuel_cost_usd"], sum(s["cost"] for s in d["fuel_stops"]), places=2)
        self.assertEqual(d["summary"]["stop_count"], len(d["fuel_stops"]))

    def test_get_with_query_params(self):
        r = self.client.get(URL, {"start": "34.05,-118.24", "finish": "Brooklyn, NY"})
        self.assertEqual(r.status_code, 200, r.content)

    def test_geometry_is_downsampled(self):
        d = self.client.post(URL, {"start": "Los Angeles, CA", "finish": "New York, NY"}, content_type="application/json").json()
        self.assertLessEqual(len(d["route"]["geojson"]["geometry"]["coordinates"]), 2500)

    def test_validation_errors(self):
        for body in [{}, {"start": "Los Angeles, CA"}, {"start": "Paris, FR", "finish": "New York, NY"},
                     {"start": "Dallas, TX", "finish": "Dallas, TX"}, {"start": 5, "finish": "Dallas, TX"},
                     {"start": {"lat": 51.5, "lon": -0.1}, "finish": "Dallas, TX"}]:
            r = self.client.post(URL, body, content_type="application/json")
            self.assertEqual(r.status_code, 400, body)
        self.assertEqual(self.osrm.get_route.call_count, 0)  # bad input never reaches the routing API

    def test_object_coordinates_accepted(self):
        r = self.client.post(URL, {"start": {"lat": 34.05, "lon": -118.24}, "finish": "New York, NY"}, content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_provider_failure_is_502(self):
        self.osrm.get_route.side_effect = RoutingProviderError("boom")
        r = self.client.post(URL, {"start": "Los Angeles, CA", "finish": "New York, NY"}, content_type="application/json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["error"], "routing_provider_error")

    def test_infeasible_is_422(self):
        with mock.patch("routing.services.trip_planner.get_station_index", return_value=StationIndex([])):
            r = self.client.post(URL, {"start": "Los Angeles, CA", "finish": "New York, NY"}, content_type="application/json")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"], "no_fuel_in_range")

    def test_map_page(self):
        r = self.client.get("/route-map/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "leaflet")
        self.assertEqual(self.client.get("/").status_code, 302)
