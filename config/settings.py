"""Django settings. Everything environment-specific is read from env vars."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
if not DEBUG and SECRET_KEY == "dev-insecure-key-change-me":
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0.")
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "stations",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_PATH", BASE_DIR / "db.sqlite3"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}

# --- Fuel routing domain configuration -------------------------------------
FUEL_ROUTING = {
    "OSRM_BASE_URL": os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org"),
    "OSRM_CONNECT_TIMEOUT": env_float("OSRM_CONNECT_TIMEOUT", 3.05),
    "OSRM_READ_TIMEOUT": env_float("OSRM_READ_TIMEOUT", 20),
    "VEHICLE_MAX_RANGE_MILES": env_float("VEHICLE_MAX_RANGE_MILES", 500),
    "SAFETY_BUFFER_MILES": env_float("SAFETY_BUFFER_MILES", 50),  # usable leg = 450
    "MPG": env_float("VEHICLE_MPG", 10),
    "MAP_MAX_GEOMETRY_POINTS": int(os.environ.get("MAP_MAX_GEOMETRY_POINTS", 2500)),
    "CORRIDOR_MILES": env_float("CORRIDOR_MILES", 10),
    "ROUTE_DENSIFY_STEP_MILES": env_float("ROUTE_DENSIFY_STEP_MILES", 0.5),
    # None => vehicle departs with a full (usable) tank, which is not billed.
    "STARTING_FUEL_MILES": os.environ.get("STARTING_FUEL_MILES") or None,
}
