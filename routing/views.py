import logging

from django.conf import settings
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.serializers import RouteRequestSerializer
from routing.services.exceptions import InfeasibleRouteError, LocationError, RoutingProviderError
from routing.services.presenter import trip_to_payload
from routing.services.trip_planner import plan_trip

log = logging.getLogger(__name__)


class RoutePlanView(APIView):
    """POST /api/route/  {"start": "Los Angeles, CA", "finish": "New York, NY"}
    GET  /api/route/?start=...&finish=...  (same thing, handy for the browser/map page)."""

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request):
        return self._plan({"start": request.query_params.get("start"), "finish": request.query_params.get("finish")})

    def post(self, request):
        return self._plan(request.data)

    def _plan(self, data):
        ser = RouteRequestSerializer(data=data)
        ser.is_valid(raise_exception=True)  # -> 400 with per-field errors
        try:
            plan = plan_trip(ser.validated_data["start"], ser.validated_data["finish"])
        except LocationError as exc:
            return Response({"error": "invalid_location", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InfeasibleRouteError as exc:
            return Response({"error": "no_fuel_in_range", "detail": str(exc), "at_route_mile": exc.at_mile,
                             "gap_miles": exc.gap_miles}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except RoutingProviderError as exc:
            log.warning("routing provider failure: %s", exc)
            return Response({"error": "routing_provider_error", "detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(trip_to_payload(plan, settings.FUEL_ROUTING["MAP_MAX_GEOMETRY_POINTS"]))


class RouteMapView(TemplateView):
    template_name = "routing/route_map.html"
