# Журнал событий заменён сохранениями (accounts.Profile.save_data), попытки уже свёрнуты в них.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("play", "0001_initial"),
        ("accounts", "0005_profile_save"),
    ]

    operations = [
        migrations.DeleteModel(name="Attempt"),
    ]
