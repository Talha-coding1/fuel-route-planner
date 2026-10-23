"""Offline, zero-network gazetteer built from the bundled ``zipcodes`` dataset.

The fuel CSV carries only City/State, so station coordinates are the centroid
of that city's ZIP codes. The same gazetteer resolves user-supplied start /
finish text ("Dallas, TX", "75201", "32.77,-96.79") without any external call.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import zipcodes

from routing.services.exceptions import LocationError

US_STATES = {
    "AL": "ALABAMA", "AK": "ALASKA", "AZ": "ARIZONA", "AR": "ARKANSAS", "CA": "CALIFORNIA",
    "CO": "COLORADO", "CT": "CONNECTICUT", "DE": "DELAWARE", "DC": "DISTRICT OF COLUMBIA",
    "FL": "FLORIDA", "GA": "GEORGIA", "HI": "HAWAII", "ID": "IDAHO", "IL": "ILLINOIS",
    "IN": "INDIANA", "IA": "IOWA", "KS": "KANSAS", "KY": "KENTUCKY", "LA": "LOUISIANA",
    "ME": "MAINE", "MD": "MARYLAND", "MA": "MASSACHUSETTS", "MI": "MICHIGAN",
    "MN": "MINNESOTA", "MS": "MISSISSIPPI", "MO": "MISSOURI", "MT": "MONTANA",
    "NE": "NEBRASKA", "NV": "NEVADA", "NH": "NEW HAMPSHIRE", "NJ": "NEW JERSEY",
    "NM": "NEW MEXICO", "NY": "NEW YORK", "NC": "NORTH CAROLINA", "ND": "NORTH DAKOTA",
    "OH": "OHIO", "OK": "OKLAHOMA", "OR": "OREGON", "PA": "PENNSYLVANIA",
    "RI": "RHODE ISLAND", "SC": "SOUTH CAROLINA", "SD": "SOUTH DAKOTA", "TN": "TENNESSEE",
    "TX": "TEXAS", "UT": "UTAH", "VT": "VERMONT", "VA": "VIRGINIA", "WA": "WASHINGTON",
    "WV": "WEST VIRGINIA", "WI": "WISCONSIN", "WY": "WYOMING",
}
_STATE_BY_NAME = {name: abbr for abbr, name in US_STATES.items()}

# Contiguous-US bounding box (OSRM cannot route to AK/HI from the mainland).
CONUS_LAT = (24.0, 50.0)
CONUS_LON = (-125.5, -66.5)

_TOKEN_ABBREV = {"SAINT": "ST", "SAINTE": "STE", "FORT": "FT", "MOUNT": "MT"}
_LATLON_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_ZIP_RE = re.compile(r"^\d{5}$")


@dataclass(frozen=True, slots=True)
class Coordinate:
    lat: float
    lon: float
    label: str = ""

    def validate_conus(self) -> "Coordinate":
        if not (CONUS_LAT[0] <= self.lat <= CONUS_LAT[1] and CONUS_LON[0] <= self.lon <= CONUS_LON[1]):
            raise LocationError(f"Location ({self.lat:.4f}, {self.lon:.4f}) is outside the contiguous USA.")
        return self


def normalize_city(name: str) -> str:
    """'St. Louis' == 'Saint Louis'; 'De Forest' == 'DeForest'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    tokens = re.sub(r"[^A-Z0-9 ]", " ", s).split()
    return "".join(_TOKEN_ABBREV.get(t, t) for t in tokens)


@dataclass(frozen=True)
class Gazetteer:
    cities: dict[tuple[str, str], tuple[float, float]]
    zips: dict[str, tuple[float, float]]


@lru_cache(maxsize=1)
def get_gazetteer() -> Gazetteer:
    sums: dict[tuple[str, str], list[float]] = {}
    zips: dict[str, tuple[float, float]] = {}
    for rec in zipcodes.list_all():
        if not rec.get("lat") or not rec.get("long"):
            continue
        lat, lon = float(rec["lat"]), float(rec["long"])
        zips[rec["zip_code"]] = (lat, lon)
        for city in [rec["city"], *rec.get("acceptable_cities", [])]:
            acc = sums.setdefault((normalize_city(city), rec["state"]), [0.0, 0.0, 0])
            acc[0] += lat
            acc[1] += lon
            acc[2] += 1
    cities = {k: (v[0] / v[2], v[1] / v[2]) for k, v in sums.items()}
    return Gazetteer(cities=cities, zips=zips)


def geocode_city(city: str, state: str) -> tuple[float, float] | None:
    return get_gazetteer().cities.get((normalize_city(city), state.strip().upper()))


def resolve_location(text: str) -> Coordinate:
    """Resolve 'lat,lon' | 'ZIP' | 'City, ST' | 'City, State Name' to a Coordinate."""
    text = (text or "").strip()
    if not text:
        raise LocationError("Location is empty.")

    if m := _LATLON_RE.match(text):
        return Coordinate(float(m[1]), float(m[2]), text).validate_conus()

    gaz = get_gazetteer()
    if _ZIP_RE.match(text):
        if text not in gaz.zips:
            raise LocationError(f"Unknown ZIP code '{text}'.")
        lat, lon = gaz.zips[text]
        return Coordinate(lat, lon, text).validate_conus()

    if "," in text:
        city, _, state = text.rpartition(",")
        state = state.strip().upper()
        state = _STATE_BY_NAME.get(state, state)
        if coords := geocode_city(city, state):
            return Coordinate(*coords, label=f"{city.strip()}, {state}").validate_conus()
    raise LocationError(
        f"Could not resolve '{text}'. Use 'City, ST', a 5-digit ZIP, or 'lat,lon'."
    )
