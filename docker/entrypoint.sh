#!/bin/sh
set -e

python manage.py migrate --noinput

# Load the fuel dataset on first boot (idempotent upsert; skip if already populated).
COUNT=$(python manage.py shell -v0 -c "from stations.models import FuelStation as F; print(F.objects.count())" | tail -n1)
if [ "$COUNT" = "0" ]; then
  echo "Empty station table -> loading fuel data"
  python manage.py load_fuel_data
fi

exec "$@"
