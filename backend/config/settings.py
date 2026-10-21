"""Настройки проекта. Значения, зависящие от окружения, читаются из переменных окружения."""

from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
# .env лежит в корне репозитория (рядом с docker-compose.yml), а не в backend/.
environ.Env.read_env(BASE_DIR.parent / ".env")

DEBUG = env.bool("DJANGO_DEBUG", default=True)
# Ключом подписаны токены входа (play.api) — без DEBUG ключ по умолчанию не годится, его надо
# задать явно. docker-compose.yml подставляет свой для локального запуска, а
# docker-compose.prod.yml без DJANGO_SECRET_KEY в .env не стартует.
SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Задайте DJANGO_SECRET_KEY (обязателен при DJANGO_DEBUG=0)")
    SECRET_KEY = "dev-insecure-change-me"
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
# За обратным прокси (nginx/caddy с HTTPS) Django узнаёт протокол из этого заголовка.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Сайт открыт только по HTTPS (прод за Caddy, см. docker-compose.prod.yml): cookie лишь по HTTPS
# и HSTS. Не привязано к DEBUG — локальный `docker compose up` работает с DEBUG=0 по HTTP.
HTTPS_ONLY = env.bool("DJANGO_HTTPS_ONLY", default=False)
if HTTPS_ONLY:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=60 * 60 * 24 * 365)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "vocab",
    "play",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# По умолчанию SQLite — чтобы быстрый локальный запуск работал без Docker.
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}

AUTH_PASSWORD_VALIDATORS = [
    # Та же минимальная длина, что и при регистрации через API (play.api.signup).
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 6},
    },
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Samara"  # Ижевск, UTC+4
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Медиа (аудио, картинки) хранятся в S3-совместимом MinIO, если он настроен.
USE_S3 = env.bool("USE_S3", default=False)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
if USE_S3:
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("S3_BUCKET", default="votes-media"),
            "endpoint_url": env("S3_ENDPOINT_URL", default="http://minio:9000"),
            # Адрес, по которому браузер/телефон видит MinIO (для presigned-ссылок).
            "custom_domain": env("S3_PUBLIC_DOMAIN", default=None),
            "url_protocol": env("S3_PUBLIC_PROTOCOL", default="http:"),
            "access_key": env("S3_ACCESS_KEY", default="minioadmin"),
            "secret_key": env("S3_SECRET_KEY", default="minioadmin"),
            "addressing_style": "path",
            "signature_version": "s3v4",
            "querystring_auth": True,
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Офлайн-снимок приложения (manage.py build_bundle): отсюда телефон скачивает обновления.
BUNDLE_DIR = Path(env("BUNDLE_DIR", default=str(BASE_DIR / "bundle")))
