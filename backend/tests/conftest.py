import pytest
from django.core.cache import cache
from django.core.management import call_command


@pytest.fixture(autouse=True)
def _clear_cache():
    """Счётчики ограничения частоты (play.api.rate_limit) не переходят из теста в тест."""
    cache.clear()


@pytest.fixture
def vocab(db):
    """Словарь из seeds/vocab.yaml."""
    call_command("seed")
