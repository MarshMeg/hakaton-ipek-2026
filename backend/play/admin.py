from django.contrib import admin

from .models import Attempt


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "game", "word_id", "correct", "ts")
    list_filter = ("game", "correct")
    search_fields = ("user__username",)
