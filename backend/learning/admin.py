from django.contrib import admin

from .models import LessonResult


@admin.register(LessonResult)
class LessonResultAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "lesson",
        "xp",
        "score",
        "accuracy",
        "max_combo",
        "mistakes",
        "completed_at",
    )
    list_filter = ("lesson__unit",)
