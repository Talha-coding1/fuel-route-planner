"""In-memory station table, loaded once per process (~6.6k rows) so requests never touch the DB."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

import numpy as np

from routing.services.geo import to_unit_xyz

_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class StationRecord:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    price: Decimal
    lat: float
    lon: float


class StationIndex:
    def __init__(self, records: list[StationRecord]):
        self.records = tuple(records)
        self.lat = np.array([r.lat for r in records], dtype=float)
        self.lon = np.array([r.lon for r in records], dtype=float)
        self.price = np.array([float(r.price) for r in records], dtype=float)
        self.xyz = to_unit_xyz(self.lat, self.lon) if records else np.empty((0, 3))

    def __len__(self) -> int:
        return len(self.records)


@lru_cache(maxsize=1)
def _load() -> StationIndex:
    from stations.models import FuelStation

    rows = FuelStation.objects.values_list("opis_id", "name", "address", "city", "state", "price", "latitude", "longitude")
    return StationIndex([StationRecord(*row) for row in rows.iterator()])


def get_station_index() -> StationIndex:
    with _lock:
        return _load()


def reset_station_index() -> None:
    _load.cache_clear()
