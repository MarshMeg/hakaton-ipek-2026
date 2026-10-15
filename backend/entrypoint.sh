#!/bin/sh
# При старте контейнера: миграции, словарь (если его ещё нет) и офлайн-снимок для телефонов.
set -e
python manage.py migrate --noinput
python manage.py seed
python manage.py build_bundle
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
  python manage.py createsuperuser --noinput 2>/dev/null || true
fi
exec "$@"
