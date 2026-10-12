from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "is_guest", "xp", "streak", "last_active")
    list_filter = ("is_guest",)
