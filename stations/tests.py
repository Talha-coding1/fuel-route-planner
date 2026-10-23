import io
import tempfile
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from routing.services.exceptions import LocationError
from stations.models import FuelStation
from stations.services.geocoding import normalize_city, resolve_location

CSV = """OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price
20,PILOT #1243,"I-8, EXIT 119",Gila Bend,AZ,930,3.899
20,PILOT TRAVEL CENTER #1243,"I-8, EXIT 119",Gila Bend,AZ,930,3.799
105,TA SAGINAW,"I-75, EXIT 144-B",Bridgeport,MI,260,3.429
105,TA SAGINAW,"I-75, EXIT 144-B",Bridgeport,MI,260,3.269
900,CANADIAN STOP,HWY 1,Calgary,AB,1,1.5
901,DEFOREST STOP,"I-90, EXIT 1",De Forest,WI,2,3.1
"""


class GeocodingTests(SimpleTestCase):
    def test_normalisation(self):
        self.assertEqual(normalize_city("St. Louis"), normalize_city("Saint Louis"))
        self.assertEqual(normalize_city("De Forest"), normalize_city("DeForest"))

    def test_resolve_formats(self):
        self.assertAlmostEqual(resolve_location("Dallas, TX").lat, 32.8, delta=0.3)
        self.assertAlmostEqual(resolve_location("Dallas, Texas").lat, resolve_location("dallas,tx").lat)
        self.assertAlmostEqual(resolve_location("75201").lon, -96.8, delta=0.2)
        self.assertEqual(resolve_location("34.05,-118.24").lat, 34.05)

    def test_rejects_outside_usa_and_garbage(self):
        for bad in ["51.5,-0.12", "Calgary, AB", "", "nowhere land"]:
            with self.assertRaises(LocationError, msg=bad):
                resolve_location(bad)


class LoadCommandTests(TestCase):
    def test_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "f.csv")
            p.write_text(CSV)
            call_command("load_fuel_data", csv=str(p), truncate=True, stdout=io.StringIO())
            call_command("load_fuel_data", csv=str(p), stdout=io.StringIO())  # idempotent
        self.assertEqual(FuelStation.objects.count(), 3)  # Canadian row dropped, dupes merged
        self.assertEqual(FuelStation.objects.get(opis_id=20).price, Decimal("3.79900000"))  # min price
        self.assertEqual(FuelStation.objects.get(opis_id=20).name, "PILOT TRAVEL CENTER #1243")
        self.assertTrue(FuelStation.objects.filter(opis_id=901).exists())  # "De Forest" geocoded
