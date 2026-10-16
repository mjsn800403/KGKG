# KGKG backend image. Built by ops/deploy/deploy.sh from a clean checkout of
# one commit (context = repo root). Code sits at the same path as on the host
# so paths shared with host jobs line up. All data (DB, warehouses, model
# cache, logs) is bind-mounted, never baked in. The container has no host
# access: host-side work goes through ops/hostjobs (see api/hostjobs.py).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false

# WeasyPrint (PDF reports) needs pango + fonts; curl is for the healthcheck.
RUN apt-get update -q && apt-get install -yq --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-dejavu-core \
      curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Exact versions frozen from the production venv.
COPY ops/docker/backend-requirements.lock /tmp/req.lock
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r /tmp/req.lock && rm /tmp/req.lock

WORKDIR /opt/KGKG/KG_backend
COPY KG_backend/ /opt/KGKG/KG_backend/

ARG KG_RELEASE=dev
ENV KG_RELEASE=$KG_RELEASE
# Health goes through a socket private to THIS container: during a deploy the
# old and new release share the TCP port, so the port alone can't say which
# one answered.
HEALTHCHECK --interval=10s --timeout=5s --start-period=180s --retries=4 \
  CMD curl -fsS -o /dev/null --unix-socket /tmp/kg.sock http://127.0.0.1/api/health/ || exit 1
# --reuse-port lets the next release bind the same port while this one
# drains, so a backend deploy has no gap.
CMD exec gunicorn KG_backend.wsgi:application --bind ${KG_BIND:-127.0.0.1}:${KG_PORT:-8000} \
    --bind unix:/tmp/kg.sock --reuse-port \
    --workers ${KG_WORKERS:-3} --worker-class gthread --threads ${KG_THREADS:-8} --timeout 300 \
    --max-requests 2000 --max-requests-jitter 200 --graceful-timeout 30
