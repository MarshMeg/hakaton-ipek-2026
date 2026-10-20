from django.contrib import admin

from .models import Profile


# В списке видно имя ребёнка и время последнего сохранения. Само сохранение (save_data)
# открывается на странице профиля как JSON.
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "avatar", "updated")
    search_fields = ("user__username", "display_name")
