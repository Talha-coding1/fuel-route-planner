import random
from decimal import Decimal

from django.test import SimpleTestCase

from routing.services.exceptions import InfeasibleRouteError
from routing.services.fuel_optimizer import OptimizerConfig, build_fuel_plan, plan_purchases
from routing.services.geo import EARTH_RADIUS_MILES, build_route_path
from stations.services.station_index import StationIndex, StationRecord

MILE_DEG = 180 / (3.141592653589793 * EARTH_RADIUS_MILES)  # degrees of latitude per mile
LON = -100.0


def meridian_route(total_miles: float):
    """Straight north-bound route along a meridian, starting at 30N."""
    n = int(total_miles // 25) + 2
    lats = [30 + (total_miles * i / (n - 1)) * MILE_DEG for i in range(n)]
    return build_route_path(lats, [LON] * n, 0.5)


def station(mile: float, price: str, off_miles: float = 0.0, opis_id: int = 0) -> StationRecord:
    return StationRecord(opis_id, f"S{opis_id}", "addr", "City", "TX", Decimal(price),
                         30 + mile * MILE_DEG, LON + off_miles * MILE_DEG * 1.15)  # ~1 mile of lon at 30N


def idx(*stations):
    return StationIndex([station(m, p, o, i) for i, (m, p, o) in enumerate(stations)])


CFG = OptimizerConfig(max_range_miles=450, mpg=10, corridor_miles=10)


class PurchasePlannerTests(SimpleTestCase):
    def test_short_trip_needs_no_stops(self):
        self.assertEqual(plan_purchases([100, 200], [3.0, 3.0], 400, 450), [])

    def test_boundary_exactly_at_range_is_reachable(self):
        self.assertEqual(plan_purchases([], [], 450, 450), [])
        buys = plan_purchases([450], [3.0], 900, 450)
        self.assertEqual(len(buys), 1)

    def test_just_beyond_range_without_station_is_infeasible(self):
        with self.assertRaises(InfeasibleRouteError) as ctx:
            plan_purchases([], [], 450.5, 450)
        self.assertAlmostEqual(ctx.exception.gap_miles, 450.5)

    def test_gap_between_stations_larger_than_range_is_infeasible(self):
        with self.assertRaises(InfeasibleRouteError):
            plan_purchases([100, 600], [3, 3], 900, 450)

    def test_buys_only_enough_to_reach_cheaper_station(self):
        # A(100,$4), B(300,$3), full start tank: skip expensive A, arrive at B with 150, buy 250 to finish.
        buys = plan_purchases([100, 300], [4.0, 3.0], 700, 450)
        self.assertEqual([b.node for b in buys], [1])
        self.assertAlmostEqual(buys[0].miles_bought, 250)
        # Starting with only 100 miles of fuel A must be used, buying just enough to reach B.
        buys = plan_purchases([100, 300], [4.0, 3.0], 700, 450, start_fuel=120)
        self.assertEqual([b.node for b in buys], [0, 1])
        self.assertAlmostEqual(buys[0].miles_bought, 180)  # arrive A with 20, need 200 to reach B

    def test_fills_up_at_cheapest_when_nothing_cheaper_ahead(self):
        buys = plan_purchases([50, 300], [3.0, 3.5], 700, 450)
        self.assertEqual(buys[0].node, 0)
        self.assertAlmostEqual(buys[0].miles_bought, 50)  # arrives with 400, tops up to 450

    def test_matches_dynamic_programming_optimum(self):
        rng = random.Random(7)
        for _ in range(400):
            R = rng.randint(20, 60)
            total = rng.randint(R, 6 * R)
            pos = sorted(rng.sample(range(1, total), min(total - 1, rng.randint(0, 10))))
            prices = [rng.choice([2.5, 2.7, 3.0, 3.0, 3.3, 3.9]) for _ in pos]
            start = rng.choice([None, R, R // 2])
            try:
                got = sum(b.miles_bought * prices[b.node] for b in plan_purchases(pos, prices, total, R, start))
            except InfeasibleRouteError:
                self.assertIsNone(dp_min_cost(pos, prices, total, R, start))
                continue
            want = dp_min_cost(pos, prices, total, R, start)
            self.assertIsNotNone(want)
            self.assertAlmostEqual(got, want, places=6, msg=f"{pos=} {prices=} {total=} {R=} {start=}")


def dp_min_cost(pos, prices, total, R, start):
    """Brute-force reference: integer miles/fuel, min cost over all buy/skip decisions."""
    INF = float("inf")
    start = R if start is None else min(start, R)
    nodes = list(pos) + [total]
    pr = list(prices) + [0.0]
    best = [[INF] * (R + 1) for _ in nodes]  # best[i][fuel on arrival]
    prev = 0
    for j, p in enumerate(nodes):  # start -> station j (free fuel, no purchase)
        if p - 0 <= start:
            best[j][start - p] = min(best[j][start - p], 0.0)
    for i in range(len(nodes) - 1):
        for f in range(R + 1):
            c = best[i][f]
            if c == INF:
                continue
            for fill in range(f, R + 1):
                cost = c + (fill - f) * pr[i]
                for j in range(i + 1, len(nodes)):
                    d = nodes[j] - nodes[i]
                    if d <= fill:
                        best[j][fill - d] = min(best[j][fill - d], cost)
    ans = min(best[-1])
    return None if ans == INF else ans


class FuelPlanTests(SimpleTestCase):
    def test_single_stop_cost_and_gallons(self):
        route = meridian_route(600)
        plan = build_fuel_plan(route, idx((300, "3.500", 0)), CFG)
        self.assertEqual(len(plan.stops), 1)
        s = plan.stops[0]
        self.assertAlmostEqual(s.route_mile, 300, delta=0.6)
        # arrives with 150 miles left, needs 600-300=300 to finish -> buys 150 miles = 15 gal
        self.assertAlmostEqual(float(s.gallons), 15.0, delta=0.1)
        self.assertEqual(plan.total_cost, s.cost)
        self.assertAlmostEqual(float(s.cost), 15.0 * 3.5, delta=0.5)

    def test_prefers_cheaper_station_even_if_further(self):
        route = meridian_route(800)
        plan = build_fuel_plan(route, idx((100, "4.000", 0), (400, "3.000", 0)), CFG)
        self.assertEqual([s.station.opis_id for s in plan.stops], [1])

    def test_station_outside_corridor_is_ignored(self):
        route = meridian_route(700)
        far = idx((300, "2.500", 30), (320, "3.800", 2))  # cheap one is ~30 miles off-route
        plan = build_fuel_plan(route, far, CFG)
        self.assertEqual([s.station.opis_id for s in plan.stops], [1])
        self.assertEqual(plan.candidates_in_corridor, 1)

    def test_infeasible_when_no_stations_on_long_route(self):
        with self.assertRaises(InfeasibleRouteError):
            build_fuel_plan(meridian_route(700), idx(), CFG)

    def test_total_equals_sum_of_stop_costs(self):
        route = meridian_route(2000)
        stations = [(m, f"{3 + (m % 7) / 10:.3f}", 0) for m in range(60, 2000, 90)]
        plan = build_fuel_plan(route, idx(*stations), CFG)
        self.assertGreater(len(plan.stops), 2)
        self.assertEqual(plan.total_cost, sum((s.cost for s in plan.stops), Decimal("0")))
        # never run dry: each leg <= usable range
        for s in plan.stops:
            self.assertLessEqual(s.leg_miles, 450 + 1e-6)
