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

    # Результаты создаёт только игра: в админке их можно смотреть (и удалять), но не править.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
