"""Gunicorn settings. Station index + gazetteer are warmed per worker so no request pays the cold start."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = 60
accesslog = "-"


def post_worker_init(worker):
    # The WSGI app is loaded by now (Django is set up); build the in-memory indexes once per worker.
    from stations.services.geocoding import get_gazetteer
    from stations.services.station_index import get_station_index

    get_gazetteer()
    n = len(get_station_index())
    worker.log.info("station index warmed: %d stations", n)
