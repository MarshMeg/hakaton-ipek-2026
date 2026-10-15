from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Ӟеч-а бур-а удмурт кыл? — администрирование контента"
admin.site.site_title = "Ӟеч-а бур-а удмурт кыл?"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("vocab.urls")),
    path("", include("play.urls")),
]
