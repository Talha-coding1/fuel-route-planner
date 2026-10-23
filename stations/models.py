from django.db import models


class FuelStation(models.Model):
    """One physical truck stop (deduplicated on the OPIS Truckstop ID).

    Coordinates are *city-level* (the source CSV has no lat/lon); see
    ``stations.services.geocoding``.
    """

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=8, help_text="USD per gallon")
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        indexes = [
            models.Index(fields=["latitude", "longitude"], name="station_latlon_idx"),
            models.Index(fields=["state", "city"], name="station_state_city_idx"),
            models.Index(fields=["price"], name="station_price_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) ${self.price:.3f}"
