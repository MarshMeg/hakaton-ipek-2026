from django.urls import path

from . import views

app_name = "vocab"

urlpatterns = [
    path("learn/", views.topics, name="topics"),
    path("learn/<slug:slug>/", views.topic, name="topic"),
    path("content.json", views.content_json, name="content"),
]
