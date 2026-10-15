import hashlib
import json

from django.core.management import call_command
from django.urls import reverse

from play.games import GAMES


def build(tmp_path):
    call_command("build_bundle", "--out", str(tmp_path))
    return json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))


def test_bundle_contains_app(tmp_path, vocab):
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
    first = build(tmp_path / "a")["version"]
    assert build(tmp_path / "b")["version"] == first


def test_bundle_rebuild_removes_stale_blobs(tmp_path, vocab):
    build(tmp_path)
    (tmp_path / "blobs" / ("0" * 64)).write_bytes(b"old")
    manifest = build(tmp_path)
    used = {f["sha"] for f in manifest["files"].values()}
    assert {p.name for p in (tmp_path / "blobs").iterdir()} == used


def test_bundle_is_served_for_updates(client, tmp_path, vocab, settings):
    settings.BUNDLE_DIR = tmp_path
    manifest = build(tmp_path)
    r = client.get(reverse("play:bundle", args=["manifest.json"]))
    assert json.loads(b"".join(r.streaming_content))["version"] == manifest["version"]
    sha = manifest["files"]["/"]["sha"]
    r = client.get(reverse("play:bundle", args=[f"blobs/{sha}"]))
    assert r.status_code == 200 and "immutable" in r["Cache-Control"]
    assert client.get(reverse("play:bundle", args=["../settings.py"])).status_code == 404
    assert client.get(reverse("play:bundle", args=["blobs/" + "f" * 64])).status_code == 404
