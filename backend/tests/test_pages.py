import pytest
from django.urls import reverse

from play.management.commands.build_bundle import page_urls


@pytest.mark.parametrize(
    "name",
    ["play:home", "vocab:topics", "play:games", "play:profile", "play:settings", "play:report"],
)
def test_main_sections_open(client, vocab, name):
    response = client.get(reverse(name))
    assert response.status_code == 200
    # Нижнее меню с четырьмя разделами из ТЗ.
    for section in ("Обучение", "Игры", "Профиль", "Настройки"):
        assert section in response.content.decode()


def test_pages_do_not_depend_on_player(client, vocab):
    """Страницы кладутся в офлайн-снимок, поэтому не должны зависеть от посетителя."""
    for url in page_urls():
        first = client.get(url).content
        client.cookies.clear()
        assert client.get(url).content == first, url
        assert b"csrfmiddlewaretoken" not in first, url


def test_topic_cards(client, vocab):
    html = client.get(reverse("vocab:topic", args=["wild-animals"])).content.decode()
    assert "гондыр" in html and "медведь" in html


def test_unknown_game_404(client, vocab):
    assert client.get(reverse("play:game", args=["chess"])).status_code == 404
