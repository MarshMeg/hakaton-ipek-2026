# Прогресс — одним сохранением на аккаунт вместо журнала событий play.Attempt.

from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import migrations, models

# Дни считаем по часовому поясу Ижевска: часовой пояс телефона на сервере неизвестен.
TZ = ZoneInfo("Europe/Samara")


def day_key(ts):
    return datetime.fromtimestamp(ts / 1000, TZ).strftime("%Y-%m-%d")


def build_save(attempts, name="", avatar="", profile_updated=0):
    """Сохранение v2 из попыток (word_id, game, correct, ts) — та же свёртка, что на телефоне
    при переходе с журнала событий (static/js/app.js, fromEvents)."""
    words = defaultdict(lambda: {"ok": 0, "bad": 0, "seen": 0, "last": 0})
    days = defaultdict(lambda: {"ok": 0, "bad": 0, "seen": 0})
    games = {}
    updated = profile_updated
    for word_id, game, correct, ts in attempts:
        updated = max(updated, ts)
        w = words[str(word_id)]
        d = days[day_key(ts)]
        w["last"] = max(w["last"], ts)
        if correct is None:
            w["seen"] += 1
            d["seen"] += 1
            continue
        g = games.setdefault(game, {"ok": 0, "bad": 0, "played": 0, "best": 0})
        key = "ok" if correct else "bad"
        w[key] += 1
        d[key] += 1
        g[key] += 1
    return {
        "v": 2,
        "updated": updated,
        "profile": {"name": name, "avatar": avatar},
        "words": dict(words),
        "days": dict(days),
        "games": games,
    }


def attempts_to_saves(apps, schema_editor):
    Attempt = apps.get_model("play", "Attempt")
    Profile = apps.get_model("accounts", "Profile")
    user_ids = Attempt.objects.values_list("user_id", flat=True).distinct()
    for user_id in user_ids:
        profile, _ = Profile.objects.get_or_create(user_id=user_id)
        rows = (
            Attempt.objects.filter(user_id=user_id)
            .order_by("ts")
            .values_list("word_id", "game", "correct", "ts")
        )
        save = build_save(rows, profile.display_name, profile.avatar, profile.updated)
        profile.save_data = save
        profile.updated = save["updated"]
        profile.save(update_fields=["save_data", "updated"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_cloud_profile"),
        ("play", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="save_data",
            field=models.JSONField(blank=True, default=dict, verbose_name="сохранение"),
        ),
        migrations.RunPython(attempts_to_saves, migrations.RunPython.noop),
    ]
