import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from stations.models import FuelStation
from stations.services.geocoding import US_STATES, geocode_city
from stations.services.station_index import reset_station_index

PRICE_STRATEGIES = {"min": min, "max": max, "mean": lambda xs: sum(xs) / len(xs)}


class Command(BaseCommand):
    help = "Load the OPIS fuel price CSV: dedupe by station ID, drop non-US rows, geocode to city centroid."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=str(Path(settings.BASE_DIR) / "data" / "fuel-prices-for-be-assessment.csv"))
        parser.add_argument("--price-strategy", choices=sorted(PRICE_STRATEGIES), default="min",
                            help="Some stations list several prices (multiple rows); how to collapse them.")
        parser.add_argument("--truncate", action="store_true", help="Delete existing stations first.")

    def handle(self, *args, **opts):
        path = Path(opts["csv"])
        if not path.exists():
            raise CommandError(f"CSV not found: {path}")

        groups: dict[int, list[dict]] = defaultdict(list)
        rows = 0
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                rows += 1
                groups[int(row["OPIS Truckstop ID"])].append(row)

        collapse = PRICE_STRATEGIES[opts["price_strategy"]]
        stations, non_us, ungeocoded = [], 0, []
        for opis_id, grp in groups.items():
            first = max(grp, key=lambda r: len(r["Truckstop Name"]))  # most descriptive name
            state = first["State"].strip().upper()
            if state not in US_STATES:
                non_us += 1
                continue
            coords = geocode_city(first["City"], state)
            if coords is None:
                ungeocoded.append(f"{first['City']}, {state}")
                continue
            price = Decimal(str(round(collapse([float(r["Retail Price"]) for r in grp]), 8)))
            stations.append(FuelStation(
                opis_id=opis_id, name=first["Truckstop Name"].strip(), address=first["Address"].strip(),
                city=first["City"].strip(), state=state, rack_id=int(first["Rack ID"]), price=price,
                latitude=coords[0], longitude=coords[1],
            ))

        with transaction.atomic():
            if opts["truncate"]:
                FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(
                stations, batch_size=1000, update_conflicts=True, unique_fields=["opis_id"],
                update_fields=["name", "address", "city", "state", "rack_id", "price", "latitude", "longitude"],
            )
        reset_station_index()

        self.stdout.write(self.style.SUCCESS(
            f"rows={rows} unique_stations={len(groups)} loaded={len(stations)} "
            f"skipped_non_us={non_us} skipped_ungeocoded={len(ungeocoded)}"
        ))
        if ungeocoded:
            self.stdout.write(self.style.WARNING("Ungeocoded: " + "; ".join(sorted(set(ungeocoded))[:20])))
