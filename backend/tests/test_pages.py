import pytest
from django.urls import reverse

from play.management.commands.build_bundle import page_urls


@pytest.mark.parametrize(
    "name",
    ["play:home", "vocab:topics", "play:games", "play:profile", "play:settings", "play:report"],
)
def test_main_sections_open(client, vocab, name):
    """Основные экраны открываются, и в каждом есть нижнее меню."""
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
    """На странице темы есть слова и переводы."""
    html = client.get(reverse("vocab:topic", args=["wild-animals"])).content.decode()
    assert "гондыр" in html and "медведь" in html


def test_unknown_game_404(client, vocab):
    """Неизвестная игра — 404."""
    assert client.get(reverse("play:game", args=["chess"])).status_code == 404


def test_hard_words_mode(client, vocab):
    """«Трудные слова» — та же механика, что «Выбери перевод», слова выбирает JS."""
    html = client.get(reverse("play:game", args=["hard"])).content.decode()
    assert 'x-data="hard"' in html
    assert "optionText(opt)" in html  # разметка «Выбери перевод»
    assert "Трудных слов нет!" in html and "Трудных слов пока мало" in html
    assert reverse("play:game", args=["choose"]) in html  # обычная игра вместо пустого режима
    assert "Все темы" not in html  # слова не по темам


def test_hard_words_mode_is_linked(client, vocab):
    """На «Трудные слова» есть ссылки со списка игр и из профиля."""
    url = reverse("play:game", args=["hard"])
    assert url in client.get(reverse("play:games")).content.decode()
    assert url in client.get(reverse("play:profile")).content.decode()
