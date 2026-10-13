# Python 3.12 и uv 0.13 — те же версии, что локально (backend/.python-version, backend/mise.toml).
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Зависимости строго по uv.lock, без dev-группы; слой кэшируется, пока lock не менялся.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev

COPY . .
RUN DJANGO_DEBUG=0 python manage.py collectstatic --noinput

EXPOSE 8000
# /app/.venv/bin в PATH, поэтому python и gunicorn берутся из окружения uv.
ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
