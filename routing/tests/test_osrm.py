from unittest import mock

import requests
from django.test import SimpleTestCase

from routing.services.exceptions import RoutingProviderError
from routing.services.osrm import OSRMClient, decode_polyline, encode_polyline


class FakeResp:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status}")

    def json(self):
        return self.payload


class OSRMTests(SimpleTestCase):
    def test_polyline_round_trip(self):
        lat, lon = [38.5, 40.7, 40.73], [-120.2, -120.95, -126.453]
        dlat, dlon = decode_polyline(encode_polyline(lat, lon))
        self.assertTrue(all(abs(a - b) < 1e-6 for a, b in zip(lat, dlat)))
        self.assertTrue(all(abs(a - b) < 1e-6 for a, b in zip(lon, dlon)))

    def test_exactly_one_http_call(self):
        session = mock.Mock()
        session.get.return_value = FakeResp({"code": "Ok", "routes": [
            {"geometry": encode_polyline([32.0, 33.0], [-97.0, -96.0]), "distance": 160934.4, "duration": 5000}]})
        route = OSRMClient("http://osrm.test", session=session).get_route(32.0, -97.0, 33.0, -96.0)
        self.assertEqual(session.get.call_count, 1)
        url = session.get.call_args.args[0]
        self.assertEqual(url, "http://osrm.test/route/v1/driving/-97.000000,32.000000;-96.000000,33.000000")
        self.assertEqual(session.get.call_args.kwargs["params"]["overview"], "full")
        self.assertEqual(len(route.lat), 2)

    def test_failure_is_not_retried(self):
        session = mock.Mock()
        session.get.side_effect = requests.ConnectTimeout("slow")
        with self.assertRaises(RoutingProviderError):
            OSRMClient("http://osrm.test", session=session).get_route(0, 0, 1, 1)
        self.assertEqual(session.get.call_count, 1)

    def test_no_route_code(self):
        session = mock.Mock()
        session.get.return_value = FakeResp({"code": "NoRoute", "message": "Impossible route"})
        with self.assertRaises(RoutingProviderError):
            OSRMClient("http://osrm.test", session=session).get_route(0, 0, 1, 1)
