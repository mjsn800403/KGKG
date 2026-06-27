# Backend image — Django served by gunicorn.
# Build context is KG_backend/ (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python deps first for layer caching. psycopg[binary] needs no apt extras.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (warehouses/.venv excluded via .dockerignore; mounted at runtime).
COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

# entrypoint runs migrate + loaddata + collectstatic, then execs gunicorn.
ENTRYPOINT ["./entrypoint.sh"]
