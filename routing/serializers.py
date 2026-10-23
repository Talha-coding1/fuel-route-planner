from rest_framework import serializers

from routing.services.exceptions import LocationError
from stations.services.geocoding import Coordinate, resolve_location


class LocationField(serializers.Field):
    """Accepts 'City, ST' | 'ZIP' | 'lat,lon' | {"lat":..,"lon":..}; yields a validated Coordinate."""

    default_error_messages = {"invalid": "Could not resolve location."}

    def to_internal_value(self, data):
        try:
            if isinstance(data, dict):
                try:
                    coord = Coordinate(float(data["lat"]), float(data["lon"]), f'{data["lat"]},{data["lon"]}')
                except (KeyError, TypeError, ValueError):
                    raise LocationError('Object locations need numeric "lat" and "lon".')
                return coord.validate_conus()
            if isinstance(data, str):
                return resolve_location(data)
            raise LocationError("Location must be a string or {lat, lon} object.")
        except LocationError as exc:
            raise serializers.ValidationError(str(exc))

    def to_representation(self, value):
        return {"lat": value.lat, "lon": value.lon, "label": value.label}


class RouteRequestSerializer(serializers.Serializer):
    start = LocationField()
    finish = LocationField()

    def validate(self, attrs):
        s, f = attrs["start"], attrs["finish"]
        if abs(s.lat - f.lat) < 1e-4 and abs(s.lon - f.lon) < 1e-4:
            raise serializers.ValidationError("Start and finish must be different locations.")
        return attrs
