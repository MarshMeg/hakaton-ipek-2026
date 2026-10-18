import importlib

import pytest
from django.apps import apps as django_apps
from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command
from django.urls import reverse

from vocab.management.commands.seed import SEEDS_DIR
from vocab.models import Fact, SortingSet, Topic, Word


def test_seed_is_idempotent_and_keeps_word_ids(vocab):
    ids = dict(Word.objects.values_list("udm", "id"))
    assert len(ids) > 50
    call_command("seed")
    call_command("seed", "--update")
    assert dict(Word.objects.values_list("udm", "id")) == ids


def test_seed_does_not_overwrite_admin_edits_without_update(vocab):
    word = Word.objects.get(udm="гондыр")
    word.ru = "мишка"
    word.save()
    call_command("seed")
    word.refresh_from_db()
    assert word.ru == "мишка"
    call_command("seed", "--update")
    word.refresh_from_db()
    assert word.ru == "медведь"


def test_seed_attaches_new_images_without_update(vocab):
    word = Word.objects.get(udm="гондыр")
    assert word.image.name.startswith("words/bear")
    # Слово загрузили раньше, чем в файл добавили картинку: seed без --update её докладывает.
    word.image = ""
    word.save()
    call_command("seed")
    word.refresh_from_db()
    assert word.image.name.startswith("words/bear")
    # А картинку, заменённую в админке, без --update не трогает.
    word.image = "words/custom.webp"
    word.save()
    call_command("seed")
    word.refresh_from_db()
    assert word.image.name == "words/custom.webp"


def test_seed_replaces_outdated_seed_images(vocab):
    """Картинку перерисовали в seeds/media/ — seed без --update меняет и уже загруженную."""
    word = Word.objects.get(udm="гондыр")
    word.image.save("bear.webp", ContentFile(b"old"), save=True)
    call_command("seed")
    word.refresh_from_db()
    assert word.image.name.startswith("words/bear")
    assert word.image.size == (SEEDS_DIR / "media" / "words" / "bear.webp").stat().st_size


def test_seed_images_exist(vocab):
    assert Word.objects.exclude(image="").count() == 83


def test_sorting_sets_reference_existing_topics(vocab):
    slugs = set(Topic.objects.values_list("slug", flat=True))
    for s in SortingSet.objects.all():
        for group in s.groups:
            assert set(group["topics"]) <= slugs


def test_vegetables_berries_set_renamed(db):
    # Клубника (боры) — садовая ягода, поэтому набор не делит слова на «огород» и «лес».
    migration = importlib.import_module("vocab.migrations.0002_rename_vegetables_berries_set")
    SortingSet.objects.create(title=migration.OLD, groups=[])
    migration.rename(django_apps, None)
    assert list(SortingSet.objects.values_list("title", flat=True)) == [migration.NEW]
    call_command("seed")
    assert not SortingSet.objects.filter(title=migration.OLD).exists()
    assert SortingSet.objects.filter(title=migration.NEW).count() == 1


def test_udmurt_letters_are_cyrillic(vocab):
    # В материалах кейса встречались латинские ö и ü вместо удмуртских ӧ и ӥ.
    for udm in Word.objects.values_list("udm", flat=True):
        assert not set(udm) & set("öüëïÖÜËÏ"), udm


def test_facts_are_plain_strings(vocab):
    # Факт с «: » без кавычек YAML превращает в словарь, и в профиле выводилось {'…': '…'}.
    texts = list(Fact.objects.values_list("text", flat=True))
    assert texts
    for text in texts:
        assert not text.startswith("{"), text


def test_seed_rejects_non_string_facts(db, tmp_path):
    vocab_file = tmp_path / "vocab.yaml"
    vocab_file.write_text("topics: []\nfacts:\n  - В алфавите 38 букв: Ӝ, Ӟ.\n", encoding="utf-8")
    with pytest.raises(CommandError, match="строкой"):
        call_command("seed", "--file", str(vocab_file))
    assert not Fact.objects.exists()


def test_content_json(client, vocab):
    data = client.get(reverse("vocab:content")).json()
    assert {t["slug"] for t in data["topics"]} >= {"numbers", "colors", "family"}
    word = next(w for w in data["words"] if w["udm"] == "кык")
    assert word == {
        "id": word["id"],
        "topic": "numbers",
        "udm": "кык",
        "ru": "два",
        "number": 2,
        "img": "/media/words/two.webp",
    }
    assert data["sorting"] and data["facts"] and data["version"]
    # Версия зависит только от содержимого.
    assert client.get(reverse("vocab:content")).json()["version"] == data["version"]
