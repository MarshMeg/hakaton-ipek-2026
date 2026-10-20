import hashlib
import json

from django.core.management import call_command
from django.urls import reverse

from play.games import GAMES
from play.mime import guess_type
from vocab.models import Word, media_url


def build(tmp_path):
    """Собирает снимок в tmp_path и возвращает его manifest.json."""
    call_command("build_bundle", "--out", str(tmp_path))
    return json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))


def test_bundle_contains_app(tmp_path, vocab):
    """В снимке есть страницы, игры, словарь и статика (без админки); sha блобов верные."""
    manifest = build(tmp_path)
    files = manifest["files"]
    for url in [
        "/",
        "/learn/",
        "/learn/family/",
        "/games/",
        "/profile/",
        "/settings/",
        "/report/",
        "/games/hard/",
        "/content.json",
    ]:
        assert url in files, url
    for game in GAMES:
        assert f"/games/{game.slug}/" in files
    assert any(url.startswith("/static/js/app") for url in files)
    assert any(url.endswith(".woff2") for url in files)
    assert not any(url.startswith("/static/admin/") for url in files)
    assert files["/"]["type"].startswith("text/html")
    for meta in files.values():
        blob = (tmp_path / "blobs" / meta["sha"]).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == meta["sha"]


def test_bundle_version_is_deterministic(tmp_path, vocab):
    """Две сборки одного и того же дают одинаковую версию."""
    first = build(tmp_path / "a")["version"]
    assert build(tmp_path / "b")["version"] == first


def test_bundle_rebuild_removes_stale_blobs(tmp_path, vocab):
    """При пересборке лишние блобы удаляются."""
    build(tmp_path)
    (tmp_path / "blobs" / ("0" * 64)).write_bytes(b"old")
    manifest = build(tmp_path)
    used = {f["sha"] for f in manifest["files"].values()}
    assert {p.name for p in (tmp_path / "blobs").iterdir()} == used


def test_bundle_is_served_for_updates(client, tmp_path, vocab, settings):
    """/bundle/ отдаёт манифест и блобы, а чужие пути — 404."""
    settings.BUNDLE_DIR = tmp_path
    manifest = build(tmp_path)
    r = client.get(reverse("play:bundle", args=["manifest.json"]))
    assert json.loads(b"".join(r.streaming_content))["version"] == manifest["version"]
    sha = manifest["files"]["/"]["sha"]
    r = client.get(reverse("play:bundle", args=[f"blobs/{sha}"]))
    assert r.status_code == 200 and "immutable" in r["Cache-Control"]
    assert client.get(reverse("play:bundle", args=["../settings.py"])).status_code == 404
    assert client.get(reverse("play:bundle", args=["blobs/" + "f" * 64])).status_code == 404


def test_media_types_without_os_table(monkeypatch):
    """В Docker-образе mimetypes не знает .webp — тип всё равно правильный."""
    monkeypatch.setattr("mimetypes.guess_type", lambda *a, **k: (None, None))
    assert guess_type("words/bear.webp") == "image/webp"
    assert guess_type("words/BEAR.WEBP") == "image/webp"
    assert guess_type("audio/a.mp3") == "audio/mpeg"
    assert guess_type("fonts/x.woff2") == "font/woff2"
    assert guess_type("js/app.js") == "text/javascript; charset=utf-8"
    assert guess_type("blob.unknown") == "application/octet-stream"


def test_media_served_with_type(client, vocab):
    """/media/ отдаёт картинку с правильным Content-Type."""
    word = Word.objects.exclude(image="").first()
    r = client.get(media_url(word.image))
    assert r.status_code == 200
    assert r["Content-Type"] == "image/webp"


def test_bundle_media_type(tmp_path, vocab):
    """В манифесте у .webp тип image/webp."""
    files = build(tmp_path)["files"]
    media = [meta for url, meta in files.items() if url.endswith(".webp")]
    assert media
    assert all(meta["type"] == "image/webp" for meta in media)
