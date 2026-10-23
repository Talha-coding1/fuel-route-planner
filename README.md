# Fuel Route Planner

Django API that takes a start and finish inside the contiguous USA and returns the driving route, the
cost-optimal fuel stops along it, and the total fuel spend.

* Vehicle: 500-mile max range (planned with a **450-mile usable leg**, i.e. a 50-mile safety buffer), **10 MPG**.
* Prices: `data/fuel-prices-for-be-assessment.csv`.
* Routing: [OSRM](https://project-osrm.org/) public API, **exactly one HTTP call per request**, no retries.
* Stack: Django 6.1, Django REST Framework 3.18, NumPy/SciPy, Leaflet for the map.

## Quick start

### Docker

```bash
docker compose up --build
```

On first boot the entrypoint runs migrations and loads the fuel data (a few seconds). Then open:

* Map UI: <http://localhost:8000/route-map/>
* API: `POST http://localhost:8000/api/route/`

Set `DJANGO_SECRET_KEY`, `OSRM_BASE_URL`, `PORT` etc. in your shell or a `.env` file (see `.env.example`).
Data lives in the `fuel_data` volume.

### Local (venv)

Python 3.12+ required.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_fuel_data
python manage.py runserver
```

### Tests

```bash
python manage.py test
```

## API

`POST /api/route/` (also `GET /api/route/?start=...&finish=...`)

```bash
curl -X POST http://localhost:8000/api/route/ \
  -H 'Content-Type: application/json' \
  -d '{"start": "Los Angeles, CA", "finish": "New York, NY"}'
```

Locations may be `"City, ST"` (or full state name), a 5-digit ZIP, `"lat,lon"`, or `{"lat": .., "lon": ..}`.
They are resolved **locally** (no geocoding API), and must be in the contiguous USA.

Response (abridged):

```jsonc
{
  "start":  {"label": "Chicago, IL", "lat": 41.85068, "lon": -87.67915},
  "finish": {"label": "Dallas, TX",  "lat": 32.78941, "lon": -96.7896},
  "route": {
    "distance_miles": 967.4, "duration_hours": 17.1,
    "geojson": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-87.67916, 41.85], "..."]}}
  },
  "fuel_stops": [
    {"order": 1, "name": "HUCKS FOOD & FUEL #379", "address": "I-57, EXIT 53", "city": "Marion", "state": "IL",
     "price_per_gallon": 2.929, "gallons": 31.787, "cost": 93.1,
     "route_mile": 317.9, "miles_since_previous_stop": 317.9, "offset_from_route_miles": 1.6,
     "location": {"lat": 37.7257, "lon": -88.9294}}
    // ... 4 more stops
  ],
  "summary": {"total_fuel_cost_usd": 149.71, "total_gallons_purchased": 51.746,
              "trip_gallons_required": 96.746, "stop_count": 5, "stations_in_corridor": 188},
  "assumptions": {"usable_range_miles": 450.0, "mpg": 10.0, "corridor_miles": 10.0,
                  "starting_fuel_miles": 450.0, "initial_tank_billed": false,
                  "station_location_precision": "city centroid"},
  "timings_ms": {"routing_api": 1496.0, "local_compute": 16.5}
}
```

| Status | `error`                  | Meaning                                                   |
|--------|--------------------------|-----------------------------------------------------------|
| 400    | field errors             | Unresolvable / non-US location, or start == finish        |
| 422    | `no_fuel_in_range`       | A gap on the route longer than the usable range           |
| 502    | `routing_provider_error` | OSRM failed or found no route                             |

## How it works

```
request ─▶ validate + resolve locations (local gazetteer)
        ─▶ OSRM: ONE call, full route as polyline6          routing/services/osrm.py
        ─▶ densify route to 0.5-mile points, KD-tree        routing/services/geo.py
        ─▶ snap stations within 10 mi of route -> mile marker   routing/services/fuel_optimizer.py
        ─▶ optimal purchase plan (greedy, DP-verified)          "
        ─▶ JSON + GeoJSON                                    routing/services/presenter.py
```

* **One external call.** Everything after the OSRM response is local NumPy/SciPy; typical local compute is
  single-digit milliseconds. Stations (~6.6k) are held in memory per worker, so requests never hit the DB.
* **Optimizer.** Stations in the corridor become `(route_mile, price)` points. At each station: if a cheaper
  station is reachable on a full tank, buy only enough to reach the *nearest* one; otherwise fill up and drive to
  the cheapest reachable station. This is optimal for the fixed-capacity gas-station problem, and the test suite
  checks it against a brute-force DP on 400 random instances.
* **Money** is computed with `Decimal`; the total equals the sum of the stop costs.

### Project layout

```
config/                     settings, urls, wsgi
stations/                   FuelStation model, load_fuel_data command, gazetteer, in-memory station index
routing/
  services/                 osrm.py, geo.py, fuel_optimizer.py, trip_planner.py, presenter.py, exceptions.py
  serializers.py, views.py  DRF layer (thin)
  templates/routing/        Leaflet map page
  tests/                    optimizer, OSRM client, API tests
docker/entrypoint.sh        migrate + first-boot data load
```

## Assumptions and limitations (please read)

1. **Station coordinates are city-level.** The CSV has no lat/lon, only city/state, so each station is placed at
   its city's ZIP-centroid (offline `zipcodes` dataset). A 10-mile corridor and the 50-mile range buffer absorb
   the error, but a station's reported position can be a few miles off its real exit.
2. **Starting tank.** The vehicle departs with a full usable tank (450 mi) that is *not billed*; trips shorter
   than that cost $0. Override with `STARTING_FUEL_MILES`.
3. **Duplicate rows.** 597 stations have several prices (multiple rows). The lowest is used
   (`load_fuel_data --price-strategy min|mean|max`). The 112 Canadian stations are excluded.
4. **Detours** to reach a station (its offset from the route) are reported but their fuel is not billed.
5. **Public OSRM demo server** is rate-limited and not for production; point `OSRM_BASE_URL` at your own instance.
6. Contiguous USA only (OSRM cannot route to Alaska/Hawaii from the mainland).
7. The optimizer is cost-optimal, so it can emit tiny top-ups (< 1 gal) when a slightly cheaper station is next.

## Configuration

| Env var                  | Default                              | Purpose                              |
|--------------------------|--------------------------------------|--------------------------------------|
| `OSRM_BASE_URL`          | `https://router.project-osrm.org`    | Routing provider                     |
| `VEHICLE_MAX_RANGE_MILES`| `500`                                | Tank range                           |
| `SAFETY_BUFFER_MILES`    | `50`                                 | Usable leg = range − buffer          |
| `VEHICLE_MPG`            | `10`                                 | Fuel efficiency                      |
| `CORRIDOR_MILES`         | `10`                                 | Max station distance from route      |
| `STARTING_FUEL_MILES`    | full usable tank                     | Initial fuel, not billed             |
| `MAP_MAX_GEOMETRY_POINTS`| `2500`                               | Route points returned for drawing    |
| `DJANGO_SECRET_KEY`      | —                                    | Required when `DJANGO_DEBUG=0`       |
| `WEB_CONCURRENCY`        | `2`                                  | Gunicorn workers                     |
| `SQLITE_PATH`            | `./db.sqlite3` (`/data/db.sqlite3` in Docker) | Database file             |

## Demo checklist (Loom, ≤ 5 min)

1. `docker compose up --build`; show the map page.
2. Postman: `POST /api/route/` for a long trip (LA → New York) and a short one; point out the stops, total cost
   and `timings_ms`. Show a 400 (bad location) and note that bad input never reaches OSRM.
3. Code tour: `osrm.py` (single call) → `fuel_optimizer.py` (corridor snap + greedy) → `tests/` (DP check).
