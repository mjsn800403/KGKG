#!/usr/bin/env sh
# Backend container startup: prepare DB + static, then run the app server.
set -e

echo "[entrypoint] applying migrations..."
python manage.py migrate --noinput

# Seed the Car list from the committed fixture (db.sqlite3 is no longer in git).
# loaddata upserts by primary key, so this is safe to run on every boot.
if [ -f api/fixtures/cars.json ]; then
    echo "[entrypoint] loading car fixture..."
    python manage.py loaddata api/fixtures/cars.json || echo "[entrypoint] loaddata skipped/failed (continuing)"
fi

echo "[entrypoint] collecting static files..."
python manage.py collectstatic --noinput

echo "[entrypoint] starting gunicorn on :8000"
exec gunicorn KG_backend.wsgi:application --bind 0.0.0.0:8000 --workers 3
