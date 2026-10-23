from django.urls import path

from routing import views

urlpatterns = [
    path("api/route/", views.RoutePlanView.as_view(), name="route-plan"),
    path("route-map/", views.RouteMapView.as_view(), name="route-map"),
]
