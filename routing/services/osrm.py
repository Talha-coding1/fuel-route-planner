"""OSRM client. ``get_route`` performs EXACTLY ONE HTTP request and never retries."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import requests
from django.conf import settings

from routing.services.exceptions import RoutingProviderError

METERS_PER_MILE = 1609.344


@dataclass(frozen=True)
class OSRMRoute:
    lat: np.ndarray
    lon: np.ndarray
    distance_m: float
    duration_s: float


def decode_polyline(encoded: str, precision: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """Decode a Google-style encoded polyline into (lat[], lon[])."""
    factor = 10.0 ** precision
    coords: list[int] = []
    idx, n = 0, len(encoded)
    while idx < n:
        for _ in range(2):  # lat delta, lon delta
            shift = result = 0
            while True:
                b = ord(encoded[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            coords.append(~(result >> 1) if result & 1 else result >> 1)
    arr = np.array(coords, dtype=np.int64).reshape(-1, 2).cumsum(axis=0) / factor
    return arr[:, 0], arr[:, 1]


def encode_polyline(lat, lon, precision: int = 6) -> str:
    """Inverse of decode_polyline (used by tests and fixtures)."""
    factor, out, prev = 10.0 ** precision, [], [0, 0]
    for la, lo in zip(lat, lon):
        for i, v in enumerate((round(la * factor), round(lo * factor))):
            delta, prev[i] = v - prev[i], v
            delta = ~(delta << 1) if delta < 0 else delta << 1
            while delta >= 0x20:
                out.append(chr((0x20 | (delta & 0x1F)) + 63))
                delta >>= 5
            out.append(chr(delta + 63))
    return "".join(out)


_session = requests.Session()
_session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0, pool_connections=4, pool_maxsize=16))
_session.mount("http://", requests.adapters.HTTPAdapter(max_retries=0))


class OSRMClient:
    def __init__(self, base_url: str | None = None, timeout: tuple[float, float] | None = None, session=None):
        cfg = settings.FUEL_ROUTING
        self.base_url = (base_url or cfg["OSRM_BASE_URL"]).rstrip("/")
        self.timeout = timeout or (cfg["OSRM_CONNECT_TIMEOUT"], cfg["OSRM_READ_TIMEOUT"])
        self.session = session or _session

    def get_route(self, start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> OSRMRoute:
        url = f"{self.base_url}/route/v1/driving/{start_lon:.6f},{start_lat:.6f};{end_lon:.6f},{end_lat:.6f}"
        params = {"overview": "full", "geometries": "polyline6", "steps": "false", "alternatives": "false"}
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise RoutingProviderError(f"Routing provider request failed: {exc}") from exc

        if payload.get("code") != "Ok" or not payload.get("routes"):
            raise RoutingProviderError(f"No route found ({payload.get('code')}): {payload.get('message', '')}".strip())
        route = payload["routes"][0]
        lat, lon = decode_polyline(route["geometry"], precision=6)
        if len(lat) < 2:
            raise RoutingProviderError("Routing provider returned a degenerate geometry.")
        return OSRMRoute(lat=lat, lon=lon, distance_m=float(route["distance"]), duration_s=float(route["duration"]))
