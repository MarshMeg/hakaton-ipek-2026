import pytest
from django.core.management import call_command


@pytest.fixture
def vocab(db):
    """Словарь из seeds/vocab.yaml."""
    call_command("seed")
