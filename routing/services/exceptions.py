class RoutePlanningError(Exception):
    """Base class; the API layer maps subclasses to HTTP status codes."""


class LocationError(RoutePlanningError):
    """Start/finish could not be resolved or is outside the USA (HTTP 400)."""


class RoutingProviderError(RoutePlanningError):
    """The external routing API failed or returned no route (HTTP 502)."""


class InfeasibleRouteError(RoutePlanningError):
    """No fuel station within range at some point on the route (HTTP 422)."""

    def __init__(self, message: str, at_mile: float | None = None, gap_miles: float | None = None):
        super().__init__(message)
        self.at_mile = at_mile
        self.gap_miles = gap_miles
