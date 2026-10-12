FROM debian:bookworm-slim

# Python ставится через mise по backend/mise.toml — та же версия, что и локально.
ENV MISE_DATA_DIR=/mise \
    MISE_CONFIG_DIR=/mise \
    MISE_CACHE_DIR=/mise/cache \
    MISE_INSTALL_PATH=/usr/local/bin/mise \
    MISE_TRUSTED_CONFIG_PATHS=/app \
    MISE_DISABLE_TOOLS=github:tailwindlabs/tailwindcss \
    MISE_VERSION=v2026.10.8 \
    PATH=/mise/shims:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://mise.run | sh

WORKDIR /app

# Только Python: Tailwind в образе не нужен (MISE_DISABLE_TOOLS), CSS уже скомпилирован
# и лежит в репозитории.
COPY mise.toml .
RUN mise install python

COPY requirements.txt .
RUN mise exec -- python -m pip install -r requirements.txt

COPY . .
RUN DJANGO_DEBUG=0 mise exec -- python manage.py collectstatic --noinput

EXPOSE 8000
# mise exec активирует venv из mise.toml для entrypoint и gunicorn.
ENTRYPOINT ["mise", "exec", "--", "./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
