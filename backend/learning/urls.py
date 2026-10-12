from django.urls import path

from . import views

app_name = "learning"

urlpatterns = [
    path("", views.home, name="home"),
    path("lesson/<int:lesson_id>/start/", views.lesson_start, name="lesson_start"),
    path("lesson/<int:lesson_id>/", views.lesson_play, name="lesson_play"),
    path("lesson/<int:lesson_id>/answer/", views.lesson_answer, name="lesson_answer"),
    path("lesson/<int:lesson_id>/next/", views.lesson_next, name="lesson_next"),
    path("lesson/<int:lesson_id>/result/", views.lesson_result, name="lesson_result"),
]
