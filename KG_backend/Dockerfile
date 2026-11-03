# KGKG Django backend. Data (Database_warehouse, static_warehouse, db.sqlite3)
# is NOT baked in: it is mounted from the host at runtime (see docker-compose.yml).
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
    KG_LOG_DIR=/var/log/kgkg
WORKDIR /app

# CPU-only torch first (the default wheel pulls ~2 GB of CUDA libs);
# graphify is a dev-only code-graph tool, not imported by the app.
COPY requirements.txt .
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.2" \
 && grep -v "^graphify" requirements.txt > /tmp/req.txt \
 && pip install -r /tmp/req.txt "gunicorn>=23"

COPY . .
RUN DJANGO_DEBUG=true DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
 && useradd -r -u 1000 kgkg && mkdir -p /var/log/kgkg && chown -R kgkg /var/log/kgkg /app
USER kgkg
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
  CMD python -c "import urllib.request,sys;urllib.request.urlopen('http://127.0.0.1:8000/admin/login/',timeout=4)" || exit 1
CMD ["gunicorn", "KG_backend.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--worker-class", "gthread", "--threads", "8", "--timeout", "300", \
     "--max-requests", "2000", "--max-requests-jitter", "200", "--graceful-timeout", "30"]
