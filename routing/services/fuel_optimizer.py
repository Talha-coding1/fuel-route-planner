"""Pure-local fuel stop optimisation. No I/O, no network.

Pipeline
  1. ``find_corridor_candidates``: KD-tree over the densified route; every station within
     ``corridor_miles`` of the path is snapped to its nearest route point -> (route_mile, offset).
  2. ``plan_purchases``: exact greedy for the fixed-capacity gas-station problem on a line
       * a cheaper station is reachable on a full tank -> buy only enough to reach the NEAREST one;
       * otherwise                                     -> fill up, then go to the cheapest reachable station.
     This is optimal for (position, price) stations with tank capacity R (verified against a DP in tests).
  3. ``build_fuel_plan``: converts purchases into Decimal-accurate stops and totals.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
from scipy.spatial import cKDTree

from routing.services.exceptions import InfeasibleRouteError
from routing.services.geo import RoutePath, chord_to_miles, miles_to_chord, to_unit_xyz
from stations.services.station_index import StationIndex, StationRecord

EPS = 1e-9
CENT = Decimal("0.01")
MILLI = Decimal("0.001")


@dataclass(frozen=True)
class OptimizerConfig:
    max_range_miles: float = 450.0  # 500-mile tank minus a 50-mile safety buffer
    mpg: float = 10.0
    corridor_miles: float = 10.0
    densify_step_miles: float = 0.5
    starting_fuel_miles: float | None = None  # None => full usable tank, not billed

    @classmethod
    def from_settings(cls) -> "OptimizerConfig":
        from django.conf import settings

        c = settings.FUEL_ROUTING
        start = c["STARTING_FUEL_MILES"]
        return cls(
            max_range_miles=float(c["VEHICLE_MAX_RANGE_MILES"]) - float(c["SAFETY_BUFFER_MILES"]),
            mpg=float(c["MPG"]),
            corridor_miles=float(c["CORRIDOR_MILES"]),
            densify_step_miles=float(c["ROUTE_DENSIFY_STEP_MILES"]),
            starting_fuel_miles=None if start is None else float(start),
        )


@dataclass(frozen=True)
class Candidates:
    """Stations inside the corridor, sorted by position along the route."""

    station_idx: np.ndarray  # indices into StationIndex
    route_mile: np.ndarray
    offset_miles: np.ndarray
    price: np.ndarray

    def __len__(self) -> int:
        return len(self.station_idx)


@dataclass(frozen=True)
class Purchase:
    node: int  # index into Candidates
    miles_bought: float
    arrival_fuel_miles: float


@dataclass(frozen=True)
class FuelStop:
    station: StationRecord
    route_mile: float
    offset_miles: float
    leg_miles: float  # distance since previous stop (or origin)
    arrival_fuel_gallons: Decimal
    gallons: Decimal
    price_per_gallon: Decimal
    cost: Decimal


@dataclass(frozen=True)
class FuelPlan:
    total_miles: float
    stops: list[FuelStop]
    total_cost: Decimal
    total_gallons_purchased: Decimal
    trip_gallons_required: Decimal
    candidates_in_corridor: int
    assumptions: dict = field(default_factory=dict)


def find_corridor_candidates(route: RoutePath, index: StationIndex, corridor_miles: float) -> Candidates:
    if len(index) == 0:
        empty = np.empty(0)
        return Candidates(empty.astype(int), empty, empty, empty)
    tree = cKDTree(to_unit_xyz(route.lat, route.lon))
    chord, nearest = tree.query(index.xyz, k=1, distance_upper_bound=miles_to_chord(corridor_miles))
    hit = np.isfinite(chord)
    station_idx = np.flatnonzero(hit)
    mile = route.mile[nearest[hit]]
    price = index.price[station_idx]
    order = np.lexsort((price, mile))  # by mile, cheapest first on ties
    return Candidates(
        station_idx=station_idx[order],
        route_mile=mile[order],
        offset_miles=chord_to_miles(chord[hit])[order],
        price=price[order],
    )


def plan_purchases(positions, prices, total_miles: float, max_range: float,
                   start_fuel: float | None = None) -> list[Purchase]:
    """Cheapest way to drive ``total_miles`` with stations at sorted ``positions`` (miles) and ``prices`` ($/gal).

    Fuel is tracked in miles of range. The vehicle starts with ``start_fuel`` (default: full) which can only
    be burned, not bought. Returns only nodes where fuel is actually purchased.
    """
    n = len(positions)
    pos = [min(float(p), total_miles) for p in positions] + [float(total_miles)]  # last node = destination
    price = [float(p) for p in prices] + [0.0]  # destination is "free" => always the cheapest target
    START = -1
    cur, cur_pos = START, 0.0
    fuel = max_range if start_fuel is None else min(float(start_fuel), max_range)
    purchases: list[Purchase] = []

    while cur != n:
        lo = cur + 1
        reach = fuel if cur == START else max_range
        hi = bisect_right(pos, cur_pos + reach + EPS, lo)
        if hi == lo:
            raise InfeasibleRouteError(
                f"No fuel station within {reach:.0f} miles after route mile {cur_pos:.0f} "
                f"(next one is {pos[lo] - cur_pos:.0f} miles away).",
                at_mile=cur_pos, gap_miles=pos[lo] - cur_pos,
            )

        nxt = None
        if cur != START:
            nxt = next((j for j in range(lo, hi) if price[j] < price[cur]), None)
        if nxt is not None:  # cheaper fuel ahead: buy only what is needed to get there
            buy = max(0.0, pos[nxt] - cur_pos - fuel)
        else:  # cheapest reachable (ties -> farthest); fill up first unless we cannot buy here
            nxt = lo
            for j in range(lo, hi):
                if price[j] <= price[nxt]:
                    nxt = j
            buy = 0.0 if cur == START else max_range - fuel

        if buy > EPS:
            purchases.append(Purchase(node=cur, miles_bought=buy, arrival_fuel_miles=fuel))
            fuel += buy
        fuel = max(0.0, fuel - (pos[nxt] - cur_pos))
        cur, cur_pos = nxt, pos[nxt]
    return purchases


def build_fuel_plan(route: RoutePath, index: StationIndex, config: OptimizerConfig) -> FuelPlan:
    cands = find_corridor_candidates(route, index, config.corridor_miles)
    purchases = plan_purchases(cands.route_mile, cands.price, route.total_miles,
                               config.max_range_miles, config.starting_fuel_miles)
    mpg = Decimal(str(config.mpg))
    stops: list[FuelStop] = []
    prev_mile = 0.0
    for p in purchases:
        rec = index.records[cands.station_idx[p.node]]
        gallons = (Decimal(str(p.miles_bought)) / mpg).quantize(MILLI, ROUND_HALF_UP)
        mile = float(cands.route_mile[p.node])
        stops.append(FuelStop(
            station=rec, route_mile=mile, offset_miles=float(cands.offset_miles[p.node]),
            leg_miles=mile - prev_mile,
            arrival_fuel_gallons=(Decimal(str(p.arrival_fuel_miles)) / mpg).quantize(MILLI, ROUND_HALF_UP),
            gallons=gallons, price_per_gallon=rec.price,
            cost=(gallons * rec.price).quantize(CENT, ROUND_HALF_UP),
        ))
        prev_mile = mile

    start = config.max_range_miles if config.starting_fuel_miles is None else config.starting_fuel_miles
    return FuelPlan(
        total_miles=route.total_miles,
        stops=stops,
        total_cost=sum((s.cost for s in stops), Decimal("0.00")),
        total_gallons_purchased=sum((s.gallons for s in stops), Decimal("0.000")),
        trip_gallons_required=(Decimal(str(route.total_miles)) / mpg).quantize(MILLI, ROUND_HALF_UP),
        candidates_in_corridor=len(cands),
        assumptions={
            "usable_range_miles": config.max_range_miles, "mpg": config.mpg,
            "corridor_miles": config.corridor_miles, "starting_fuel_miles": start,
            "initial_tank_billed": False, "station_location_precision": "city centroid",
        },
    )
