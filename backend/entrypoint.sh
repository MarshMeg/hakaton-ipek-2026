#!/bin/sh
# При старте контейнера: применяем миграции и загружаем стартовый контент (если его ещё нет).
set -e
python manage.py migrate --noinput
python manage.py seed
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
  python manage.py createsuperuser --noinput 2>/dev/null || true
fi
exec "$@"
