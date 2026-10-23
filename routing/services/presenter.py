"""Turns a TripPlan into the public JSON payload."""
from __future__ import annotations

import numpy as np

from routing.services.trip_planner import TripPlan
from stations.services.geocoding import Coordinate


def _geojson_line(lat: np.ndarray, lon: np.ndarray, max_points: int) -> dict:
    n = len(lat)
    if n > max_points:  # uniform stride (always keeping both endpoints) is plenty for map display
        keep = np.unique(np.linspace(0, n - 1, max_points).astype(int))
        lat, lon = lat[keep], lon[keep]
    coords = np.column_stack((lon, lat)).round(5).tolist()  # GeoJSON order: [lon, lat]
    return {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": coords}}


def _point(c: Coordinate) -> dict:
    return {"label": c.label, "lat": round(c.lat, 5), "lon": round(c.lon, 5)}


def trip_to_payload(plan: TripPlan, max_geometry_points: int = 2500) -> dict:
    fuel = plan.fuel
    return {
        "start": _point(plan.start),
        "finish": _point(plan.end),
        "route": {
            "distance_miles": round(plan.osrm_distance_miles, 1),
            "duration_hours": round(plan.osrm_duration_s / 3600, 2),
            "geojson": _geojson_line(plan.route.vertex_lat, plan.route.vertex_lon, max_geometry_points),
        },
        "fuel_stops": [
            {
                "order": i,
                "name": s.station.name,
                "address": s.station.address,
                "city": s.station.city,
                "state": s.station.state,
                "price_per_gallon": round(float(s.price_per_gallon), 3),
                "gallons": float(s.gallons),
                "cost": float(s.cost),
                "route_mile": round(s.route_mile, 1),
                "miles_since_previous_stop": round(s.leg_miles, 1),
                "offset_from_route_miles": round(s.offset_miles, 1),
                "location": {"lat": round(s.station.lat, 5), "lon": round(s.station.lon, 5)},
            }
            for i, s in enumerate(fuel.stops, start=1)
        ],
        "summary": {
            "total_fuel_cost_usd": float(fuel.total_cost),
            "total_gallons_purchased": float(fuel.total_gallons_purchased),
            "trip_gallons_required": float(fuel.trip_gallons_required),
            "stop_count": len(fuel.stops),
            "stations_in_corridor": fuel.candidates_in_corridor,
        },
        "assumptions": fuel.assumptions,
        "timings_ms": plan.timings_ms,
    }
