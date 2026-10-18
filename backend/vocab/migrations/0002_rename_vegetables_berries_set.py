"""Набор сортировки «Огород или лес?» переименован в «Овощи или ягоды?»: клубника (боры) —
садовая ягода, а набор отправлял её «в лес». seed ищет наборы по названию, поэтому без
переименования в базе остался бы и старый набор."""

from django.db import migrations

OLD, NEW = "Огород или лес?", "Овощи или ягоды?"


def rename(apps, schema_editor):
    SortingSet = apps.get_model("vocab", "SortingSet")
    if SortingSet.objects.filter(title=NEW).exists():
        SortingSet.objects.filter(title=OLD).delete()
    else:
        SortingSet.objects.filter(title=OLD).update(title=NEW)


class Migration(migrations.Migration):
    dependencies = [("vocab", "0001_initial")]

    operations = [migrations.RunPython(rename, migrations.RunPython.noop)]
