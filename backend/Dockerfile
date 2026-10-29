FROM python:3.10.9-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend /app/backend

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port \"${LISTINGO_PORT:-8000}\" --proxy-headers --forwarded-allow-ips \"${LISTINGO_TRUSTED_PROXIES:-127.0.0.1}\""]

