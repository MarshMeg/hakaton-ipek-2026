from django.urls import path

from . import api, views

app_name = "play"

urlpatterns = [
    path("", views.home, name="home"),
    path("games/", views.games, name="games"),
    path("games/<slug:slug>/", views.game, name="game"),
    path("profile/", views.profile, name="profile"),
    path("settings/", views.settings_page, name="settings"),
    path("report/", views.report, name="report"),
    path("media/<path:path>", views.media, name="media"),
    path("bundle/<path:name>", views.bundle_file, name="bundle"),
    path("api/signup", api.signup, name="api_signup"),
    path("api/login", api.login, name="api_login"),
    path("api/sync", api.sync, name="api_sync"),
]
