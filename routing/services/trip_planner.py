"""Orchestrates one request: 1 routing call -> local spatial optimisation."""
from __future__ import annotations

import time
from dataclasses import dataclass

from routing.services.fuel_optimizer import FuelPlan, OptimizerConfig, build_fuel_plan
from routing.services.geo import RoutePath, build_route_path
from routing.services.osrm import METERS_PER_MILE, OSRMClient
from stations.services.geocoding import Coordinate
from stations.services.station_index import StationIndex, get_station_index


@dataclass(frozen=True)
class TripPlan:
    start: Coordinate
    end: Coordinate
    route: RoutePath
    osrm_distance_miles: float
    osrm_duration_s: float
    fuel: FuelPlan
    timings_ms: dict


def plan_trip(start: Coordinate, end: Coordinate, *, osrm: OSRMClient | None = None,
              index: StationIndex | None = None, config: OptimizerConfig | None = None) -> TripPlan:
    osrm = osrm or OSRMClient()
    index = index if index is not None else get_station_index()
    config = config or OptimizerConfig.from_settings()

    t0 = time.perf_counter()
    raw = osrm.get_route(start.lat, start.lon, end.lat, end.lon)  # the ONLY external call
    t1 = time.perf_counter()
    route = build_route_path(raw.lat, raw.lon, config.densify_step_miles)
    fuel = build_fuel_plan(route, index, config)
    t2 = time.perf_counter()

    return TripPlan(
        start=start, end=end, route=route,
        osrm_distance_miles=raw.distance_m / METERS_PER_MILE, osrm_duration_s=raw.duration_s,
        fuel=fuel,
        timings_ms={"routing_api": round((t1 - t0) * 1000, 1), "local_compute": round((t2 - t1) * 1000, 1)},
    )
