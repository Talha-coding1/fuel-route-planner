"""Vectorised spherical geometry helpers (numpy only, no network)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def to_unit_xyz(lat, lon) -> np.ndarray:
    """Points on the unit sphere; Euclidean (chord) distance is monotone with great-circle distance,
    so a KD-tree over these vectors gives exact nearest-neighbour search without projection error."""
    phi, lmb = np.radians(np.asarray(lat, dtype=float)), np.radians(np.asarray(lon, dtype=float))
    return np.column_stack((np.cos(phi) * np.cos(lmb), np.cos(phi) * np.sin(lmb), np.sin(phi)))


def miles_to_chord(miles: float) -> float:
    return 2.0 * np.sin(miles / (2.0 * EARTH_RADIUS_MILES))


def chord_to_miles(chord):
    return 2.0 * EARTH_RADIUS_MILES * np.arcsin(np.clip(np.asarray(chord) / 2.0, 0.0, 1.0))


@dataclass(frozen=True)
class RoutePath:
    """Route geometry. ``vertex_*`` are the provider's vertices (for drawing);
    ``lat/lon/mile`` are the same path densified to <= step miles (for proximity maths)."""

    vertex_lat: np.ndarray
    vertex_lon: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    mile: np.ndarray  # cumulative distance along route for each densified point

    @property
    def total_miles(self) -> float:
        return float(self.mile[-1])


def build_route_path(lat, lon, step_miles: float = 0.5) -> RoutePath:
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    if len(lat) < 2:
        raise ValueError("Route needs at least two vertices.")
    seg = haversine_miles(lat[:-1], lon[:-1], lat[1:], lon[1:])
    seg_start = np.concatenate(([0.0], np.cumsum(seg)[:-1]))
    counts = np.maximum(1, np.ceil(seg / step_miles)).astype(int)
    seg_idx = np.repeat(np.arange(len(seg)), counts)
    first = np.cumsum(counts) - counts
    t = (np.arange(counts.sum()) - np.repeat(first, counts)) / counts[seg_idx]
    d_lat = lat[seg_idx] + t * (lat[seg_idx + 1] - lat[seg_idx])
    d_lon = lon[seg_idx] + t * (lon[seg_idx + 1] - lon[seg_idx])
    d_mile = seg_start[seg_idx] + t * seg[seg_idx]
    return RoutePath(
        vertex_lat=lat, vertex_lon=lon,
        lat=np.append(d_lat, lat[-1]), lon=np.append(d_lon, lon[-1]),
        mile=np.append(d_mile, seg.sum()),
    )
