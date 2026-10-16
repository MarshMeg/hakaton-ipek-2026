#!/bin/sh
# Переключение web на сервере (вызывает задача deploy в .github/workflows/ci.yml):
#   deploy/deploy.sh ghcr.io/…/web:<sha>   скачать образ и перезапустить на нём
#   deploy/deploy.sh --rollback            вернуть образ, который работал до последнего деплоя
#
# docker-compose.prod.yml запускает web из локального тега votes-web:current, поэтому и ручной
# `docker compose … up -d` на сервере поднимает последний выкаченный (или откаченный) образ.
# Перед переключением работающий образ получает тег votes-web:previous — к нему и откатываемся.
# Миграции БД откат не отменяет: новая версия могла их уже применить.
set -eu
cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
CURRENT=votes-web:current
PREVIOUS=votes-web:previous

if [ "${1:-}" = "--rollback" ]; then
  if ! docker image inspect "$PREVIOUS" >/dev/null 2>&1; then
    echo "Нет образа $PREVIOUS — откатывать некуда" >&2
    exit 1
  fi
  docker tag "$PREVIOUS" "$CURRENT"
  $COMPOSE up -d --no-build web
  exit 0
fi

IMAGE=$1
docker pull "$IMAGE"

running=$($COMPOSE ps -q web)
if [ -n "$running" ]; then
  old=$(docker inspect -f '{{.Image}}' "$running")
  new=$(docker image inspect -f '{{.Id}}' "$IMAGE")
  # Повторный деплой того же образа не должен затирать образ для отката.
  if [ "$old" != "$new" ]; then
    docker tag "$old" "$PREVIOUS"
  fi
fi

docker tag "$IMAGE" "$CURRENT"
# Снимаем только тег с sha: образ остаётся под votes-web:current, а теги не копятся.
docker image rm "$IMAGE" >/dev/null
$COMPOSE up -d --no-build --remove-orphans
docker image prune -f
