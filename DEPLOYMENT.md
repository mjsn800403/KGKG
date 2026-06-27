# Deployment & data bootstrap

This repo holds **code only**. The car content (per-car SQLite warehouses and
per-car media) is large (~17 GB locally) and lives **outside git** — it is
mounted/provided at runtime. This document explains what data is needed, where
it goes, and how to run the stack in production.

## Components

| Part | Path | Role |
|------|------|------|
| Backend | `KG_backend/` | Django + gunicorn API (browse + `/healthz`) |
| Frontend | `kg_frontend/` | Next.js (standalone) UI |
| Relational DB | Postgres (prod) / SQLite (dev) | the `Car` list (`main_db` table) |
| Warehouses | `KG_backend/Database_warehouse/`, `KG_backend/static_warehouse/` | per-car content DBs + images (**not in git**) |

## What is tracked vs what you must provide

**In git:** all source, Dockerfiles, `docker-compose.yml`, CI, and
`KG_backend/api/fixtures/cars.json` (the Car list, so the relational DB is
reproducible).

**NOT in git — provide at runtime** (gitignored, mounted as volumes):
- `KG_backend/Database_warehouse/*.db` — one SQLite DB per car (the node tree).
- `KG_backend/static_warehouse/<car>/…` — per-car images served at `/media/`.
- `Cars_database/`, `.venv/` — local build inputs / virtualenv.

`Car.db_address` (in the fixture) points at the matching
`Database_warehouse/<car>.db`; the warehouse files must be present for the
model-level endpoints to return content. The brand/year browse endpoints work
from the relational DB alone.

## Reseeding the relational DB

`db.sqlite3` is no longer committed. Recreate the Car list from the fixture:

```bash
python manage.py migrate
python manage.py loaddata api/fixtures/cars.json   # restores the 3 cars
```

The backend container's `entrypoint.sh` does this automatically on boot.
To refresh the fixture after editing cars: `python manage.py dumpdata api.Car
--indent 2 -o api/fixtures/cars.json`.

## Running

### Local development
```bash
cp .env.example .env            # DJANGO_DEBUG=True, SQLite
cd KG_backend && python manage.py migrate && python manage.py runserver
cd kg_frontend && npm install && npm run dev
```

### Production-like (Docker)
```bash
cp .env.example .env            # set a real DJANGO_SECRET_KEY (see below)
docker compose up --build       # Postgres + gunicorn backend + Next frontend
```
Compose runs the backend with `DEBUG=False`, behind gunicorn, with the
warehouses mounted from the host. The backend has a `/healthz` healthcheck;
the frontend waits for it to report healthy.

Generate a real secret key:
```bash
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

## Configuration (environment)

| Var | Purpose |
|-----|---------|
| `DJANGO_SECRET_KEY` | required in prod |
| `DJANGO_DEBUG` | `False` in prod |
| `DJANGO_ALLOWED_HOSTS` | comma-separated hostnames |
| `DJANGO_CORS_ORIGINS` | allowed frontend origins (DEBUG off) |
| `DJANGO_SECURE_SSL` | `True` behind HTTPS (HSTS, secure cookies, redirect) |
| `DATABASE_URL` | `postgres://…` in prod; unset = SQLite |
| `POSTGRES_USER/PASSWORD/DB` | compose `db` service |
| `NEXT_PUBLIC_API_BASE` | backend origin the **browser** uses (build-time) |

## Reverse proxy / TLS (recommended front)

gunicorn + WhiteNoise serve the app and static/admin assets directly, which is
sufficient for an internal tool. For a public deployment, terminate TLS at a
reverse proxy (nginx/Caddy/Traefik) and forward to the backend on `:8000` and
frontend on `:3000`. When the proxy terminates HTTPS:
- set `DJANGO_SECURE_SSL=True`,
- ensure the proxy sends `X-Forwarded-Proto: https` (Django already trusts it
  via `SECURE_PROXY_SSL_HEADER`).

Per-car media (`/media/`) is served by Django regardless of `DEBUG`; for high
traffic, serve `static_warehouse/` straight from the proxy/CDN instead.

## Building the RAG / diagnostic index (optional)

The heavy ML dependencies are **not** in `requirements.txt`. They are pinned
separately in `KG_backend/requirements-rag.txt` and installed on demand by
`run_rag_build.sh` (which also runs fully offline against the cached `bge-m3`
model). Run the index build from a machine that has the warehouse data.
