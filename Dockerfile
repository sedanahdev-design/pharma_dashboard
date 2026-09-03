FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/media /app/staticfiles \
    && chmod +x /app/docker-entrypoint.sh \
    && python manage.py collectstatic --noinput

EXPOSE 8060

ENTRYPOINT ["/app/docker-entrypoint.sh"]
